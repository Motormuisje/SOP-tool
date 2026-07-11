"""Financial-metrics deviation + drilldown routes (Fase 2.4).

Read-only views over the value-planning consolidation rows. The deviation
reference is the session's own reset baseline (the clean, pre-edit state) — it
is always available and independent of the cross-cycle MoM pipeline. Each
consolidation row already carries its source value line type in ``aux_column``
(e.g. TURNOVER -> "01. Demand forecast"), which drives an exact drilldown to
the underlying material rows; rows with no source (aux_column None) are pure
derived aggregates (GROSS MARGIN, EBIT, ...).
"""

from typing import Callable

from flask import Blueprint, jsonify, request

from modules.models import LineType


def _row_values(row):
    """values dict from either a PlanningRow or a serialized row payload."""
    if isinstance(row, dict):
        return row.get('values', {}) or {}
    return getattr(row, 'values', {}) or {}


def _row_attr(row, name, default=None):
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _trend(values, periods):
    seq = [float(values.get(p, 0.0) or 0.0) for p in periods]
    if len(seq) < 2:
        return 'flat'
    diff = seq[-1] - seq[0]
    scale = max(abs(seq[0]), 1.0)
    if diff > 0.01 * scale:
        return 'up'
    if diff < -0.01 * scale:
        return 'down'
    return 'flat'


def create_financials_blueprint(get_active: Callable[[], tuple]) -> Blueprint:
    bp = Blueprint('financials', __name__)

    @bp.route('/api/financial_metrics')
    def financial_metrics():
        sess, engine = get_active()
        if engine is None:
            return jsonify({'error': 'No calculations run'}), 400
        periods = list(getattr(engine.data, 'periods', []) or [])
        current = engine.value_results.get(LineType.CONSOLIDATION.value, [])
        baseline_rows = ((sess or {}).get('reset_baseline') or {}).get('value_results', {}) or {}
        baseline_consol = {
            str(_row_attr(r, 'material_number', '')): r
            for r in baseline_rows.get(LineType.CONSOLIDATION.value, [])
        }

        metrics = []
        for row in current:
            mat = str(_row_attr(row, 'material_number', ''))
            name = mat.replace('ZZZZZZ_', '')
            cur_vals = _row_values(row)
            base_row = baseline_consol.get(mat)
            base_vals = _row_values(base_row) if base_row is not None else {}
            delta, delta_pct = {}, {}
            for p in periods:
                c = float(cur_vals.get(p, 0.0) or 0.0)
                b = float(base_vals.get(p, 0.0) or 0.0)
                delta[p] = round(c - b, 2)
                delta_pct[p] = round((c - b) / abs(b) * 100, 1) if b != 0 else 0.0
            metrics.append({
                'name': name,
                'source_line_type': _row_attr(row, 'aux_column', None),
                'current': {p: round(float(cur_vals.get(p, 0.0) or 0.0), 2) for p in periods},
                'baseline': {p: round(float(base_vals.get(p, 0.0) or 0.0), 2) for p in periods},
                'delta': delta,
                'delta_pct': delta_pct,
                'trend': _trend(cur_vals, periods),
                'has_baseline': base_row is not None,
            })
        return jsonify({'periods': periods, 'metrics': metrics,
                        'baseline_available': bool(baseline_consol)})

    @bp.route('/api/financial_metrics/drill')
    def financial_metrics_drill():
        _, engine = get_active()
        if engine is None:
            return jsonify({'error': 'No calculations run'}), 400
        metric = (request.args.get('metric') or '').strip()
        if not metric:
            return jsonify({'error': 'metric is required'}), 400
        target = 'ZZZZZZ_' + metric if not metric.startswith('ZZZZZZ_') else metric
        consol = engine.value_results.get(LineType.CONSOLIDATION.value, [])
        row = next((r for r in consol if str(_row_attr(r, 'material_number', '')) == target), None)
        if row is None:
            return jsonify({'error': f'metric {metric} not found'}), 404
        source_lt = _row_attr(row, 'aux_column', None)
        if not source_lt:
            return jsonify({'metric': metric, 'derived': True,
                            'message': 'Afgeleide metric — samengesteld uit onderliggende regels.'})
        periods = list(getattr(engine.data, 'periods', []) or [])
        contributors = []
        for r in engine.value_results.get(source_lt, []):
            vals = _row_values(r)
            total = sum(float(vals.get(p, 0.0) or 0.0) for p in periods)
            if abs(total) < 1e-9:
                continue
            contributors.append({
                'material_number': str(_row_attr(r, 'material_number', '')),
                'material_name': str(_row_attr(r, 'material_name', '') or ''),
                'total': round(total, 2),
                'values': {p: round(float(vals.get(p, 0.0) or 0.0), 2) for p in periods},
            })
        contributors.sort(key=lambda x: abs(x['total']), reverse=True)
        return jsonify({'metric': metric, 'derived': False, 'source_line_type': source_lt,
                        'periods': periods, 'contributors': contributors[:15]})

    return bp
