"""Capacity & FTE workbench routes (F2-CF).

Read side (`GET /api/fte`) serves the workbench result the engine already
computed as part of the normal cascade — no recalculation on a page view.

Write side is deliberately narrow: the only thing this blueprint mutates is
which machine COMBINATIONS are active. Everything else the workbench shows is
either master data (edited through /api/master_data) or a planning cell
(edited through the existing edit cascade), so there is exactly one owner per
number.

The comparison endpoint runs the FTE engine repeatedly over the SAME planning
results with different combination sets. That is what makes the variants
comparable: only the staffing assumption differs.
"""

from typing import Callable

from flask import Blueprint, jsonify, request

from modules.fte_engine import FteEngine

_NO_ENGINE = 'Nog geen berekening uitgevoerd.'


def _combination_catalog(engine) -> list:
    combos = getattr(getattr(engine, 'data', None), 'machine_combinations', None) or {}
    return [{
        'combination_id': combo.combination_id,
        'name': combo.name or combo.combination_id,
        'machine_codes': list(combo.machine_codes),
        'operators': combo.operators,
        'throughput_factor': combo.throughput_factor,
        'throughput_factor_by_machine': dict(combo.throughput_factor_by_machine),
        'function_group': combo.function_group,
        'is_active': combo.is_active,
    } for combo in sorted(combos.values(), key=lambda c: c.combination_id)]


def _summary(result) -> dict:
    """The KPI line of one variant: FTE, occupancy, cost, margin, t/FTE."""
    periods = result.periods
    impact = result.value_impact

    def _avg(values):
        return sum(values.get(p, 0.0) for p in periods) / len(periods) if periods else 0.0

    def _sum(values):
        return sum(values.get(p, 0.0) for p in periods)

    return {
        'fte_avg': _avg(result.total_fte),
        'direct_fte_avg': _avg(result.total_direct_fte),
        'indirect_fte_avg': _avg(result.total_indirect_fte),
        'staffed_fte_avg': (sum(result.staffed_fte(p) for p in periods) / len(periods)
                            if periods else 0.0),
        'hours_total': _sum(result.total_hours),
        'available_hours_total': _sum(result.total_available_hours),
        'utilization': (_sum(result.total_hours) / _sum(result.total_available_hours)
                        if _sum(result.total_available_hours) > 0 else 0.0),
        'labor_cost_total': _sum(result.total_cost),
        'volume_total': _sum(result.total_volume),
        'tons_per_fte': (_sum(result.total_volume) / _avg(result.total_fte)
                         if _avg(result.total_fte) > 0 else 0.0),
        'gross_margin_total': _sum(impact.gross_margin) if impact.available else None,
        'ebitda_total': _sum(impact.ebitda) if impact.available else None,
        'value_impact_available': impact.available,
    }


def create_fte_blueprint(
    get_active: Callable[[], tuple],
    save_sessions_to_disk: Callable[[], None],
) -> Blueprint:
    bp = Blueprint('fte', __name__)

    def _result(engine):
        """The current workbench result, computed on demand if never built."""
        result = getattr(engine, 'fte_results', None)
        if result is None and hasattr(engine, 'recalculate_fte'):
            engine.recalculate_fte()
            result = engine.fte_results
        return result

    @bp.route('/api/fte', methods=['GET'])
    def get_fte():
        sess, engine = get_active()
        if engine is None:
            return jsonify({'error': _NO_ENGINE}), 400
        result = _result(engine)
        if result is None:
            return jsonify({'error': 'De FTE-werkbank is niet beschikbaar voor deze sessie.'}), 400
        return jsonify({
            'success': True,
            'fte': result.to_dict(),
            'combinations': _combination_catalog(engine),
            'active_combinations': list((sess or {}).get('active_combinations') or []),
        })

    @bp.route('/api/fte/combinations', methods=['POST'])
    def set_combinations():
        """Turn machine combinations on/off for this session and recalculate.

        Session state, not master data: which combinations are ON is a
        what-if, the combinations themselves are master data.
        """
        sess, engine = get_active()
        if engine is None:
            return jsonify({'error': _NO_ENGINE}), 400
        body = request.get_json(silent=True) or {}
        requested = body.get('active_combinations')
        if not isinstance(requested, list):
            return jsonify({'error': 'Verwacht een lijst "active_combinations".'}), 400
        known = {c['combination_id'] for c in _combination_catalog(engine)}
        unknown = [str(c) for c in requested if str(c) not in known]
        if unknown:
            return jsonify({'error': 'Onbekende combinatie(s): ' + ', '.join(unknown)}), 400

        active = [str(c) for c in requested]
        sess['active_combinations'] = active
        engine.recalculate_fte(active)
        save_sessions_to_disk()
        return jsonify({
            'success': True,
            'fte': engine.fte_results.to_dict(),
            'active_combinations': active,
        })

    @bp.route('/api/fte/refresh', methods=['POST'])
    def refresh_master():
        """Re-read the F2-CF master datasets into the live engine.

        The workbench edits its norms through the normal master-data PATCH
        (one owner per number), but a running engine holds the datasets it was
        built with. Without this the workbench would keep showing yesterday's
        staffing until the next full recalculation. This is a read-through of
        the store, not new session state: a rebuild re-hydrates from the same
        source, so nothing can drift.
        """
        from modules.master_data import hydrate_fte_datasets
        from ui.master_store import get_current_master_record

        sess, engine = get_active()
        if engine is None or getattr(engine, 'data', None) is None:
            return jsonify({'error': _NO_ENGINE}), 400
        record = get_current_master_record()
        if record is None:
            return jsonify({'error': 'Geen masterdata in de app.'}), 400
        hydrate_fte_datasets(engine.data, record.get('master') or {})
        engine.recalculate_fte()
        return jsonify({
            'success': True,
            'fte': engine.fte_results.to_dict(),
            'combinations': _combination_catalog(engine),
            'active_combinations': list((sess or {}).get('active_combinations') or []),
        })

    @bp.route('/api/fte/compare', methods=['POST'])
    def compare():
        """Run several combination sets over the same planning results.

        Body: {"variants": [{"label": "...", "active_combinations": [...]}, ...]}
        The session's own set is prepended as the baseline when absent, so the
        comparison always has something to be measured against.
        """
        sess, engine = get_active()
        if engine is None:
            return jsonify({'error': _NO_ENGINE}), 400
        body = request.get_json(silent=True) or {}
        variants = body.get('variants')
        if not isinstance(variants, list) or not variants:
            return jsonify({'error': 'Verwacht een niet-lege lijst "variants".'}), 400
        known = {c['combination_id'] for c in _combination_catalog(engine)}

        current = sorted((sess or {}).get('active_combinations') or [])
        prepared = []
        for index, variant in enumerate(variants):
            if not isinstance(variant, dict):
                return jsonify({'error': f'Variant {index + 1} is geen object.'}), 400
            combos = variant.get('active_combinations') or []
            if not isinstance(combos, list):
                return jsonify({'error': f'Variant {index + 1}: "active_combinations" moet een lijst zijn.'}), 400
            unknown = [str(c) for c in combos if str(c) not in known]
            if unknown:
                return jsonify({'error': f'Variant {index + 1}: onbekende combinatie(s) '
                                         + ', '.join(unknown)}), 400
            prepared.append({
                'label': str(variant.get('label') or f'Variant {index + 1}'),
                'active_combinations': [str(c) for c in combos],
            })
        if not any(sorted(v['active_combinations']) == current for v in prepared):
            prepared.insert(0, {'label': 'Huidige instelling',
                                'active_combinations': list(current)})

        rows = []
        for variant in prepared:
            result = FteEngine(engine.data, engine.results,
                               active_combinations=variant['active_combinations'],
                               value_results=engine.value_results).calculate()
            rows.append({
                'label': variant['label'],
                'active_combinations': variant['active_combinations'],
                'summary': _summary(result),
                'warnings': result.warnings,
            })
        baseline = rows[0]['summary']
        for row in rows[1:]:
            row['delta'] = {
                key: (row['summary'][key] - baseline[key])
                for key, value in baseline.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
                and isinstance(row['summary'].get(key), (int, float))
            }
        return jsonify({'success': True, 'variants': rows,
                        'periods': engine.fte_results.periods
                        if getattr(engine, 'fte_results', None) else []})

    return bp
