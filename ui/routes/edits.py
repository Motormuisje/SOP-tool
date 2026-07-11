"""Planning edit routes.

The volume cascade itself stays in ui.app for now and is injected here as
apply_volume_change. This keeps this module as route orchestration only.
"""

import io
import json
import uuid
from datetime import datetime
from typing import Callable

from flask import Blueprint, jsonify, request, send_file

from modules.models import LineType
from ui.pending_edits import trim_stack_group_aware
from ui.volume_change import recalculate_capacity_and_values


def _engine_state_response(current_engine, extra: dict | None = None) -> dict:
    """Full results/value_results/consolidation payload built from the engine.
    Shared by bulk edit and group undo/redo so a batch returns one final
    state rather than one response per cell."""
    payload = {
        'success': True,
        'results': {
            lt: [r.to_dict() for r in rows]
            for lt, rows in current_engine.results.items()
        },
        'value_results': {
            lt: [r.to_dict() for r in rows]
            for lt, rows in current_engine.value_results.items()
        },
        'consolidation': [
            r.to_dict()
            for r in current_engine.value_results.get(LineType.CONSOLIDATION.value, [])
        ],
    }
    if extra:
        payload.update(extra)
    return payload


def create_edits_blueprint(
    get_active: Callable[[], tuple],
    value_aux_editable_line_types: set,
    global_config: dict,
    apply_volume_change: Callable[..., object],
    ensure_reset_baseline: Callable[[dict, object], None],
    recalculate_value_results: Callable[[object, dict], None],
    save_sessions_to_disk: Callable[[], None],
    valuation_params_from_config: Callable[[object], object],
    restore_engine_state: Callable[[object, dict], None],
    snapshot_has_manual_edits: Callable[[dict], bool],
    build_clean_engine_for_session: Callable[[dict], object],
    install_clean_engine_baseline: Callable[[dict, object], None],
) -> Blueprint:
    bp = Blueprint('edits', __name__)

    def _valuation_params_dict(engine):
        vp = getattr(getattr(engine, 'data', None), 'valuation_params', None)
        if vp is None:
            return {str(k): float(v) for k, v in (global_config.get('valuation_params') or {}).items()}
        if isinstance(vp, dict):
            return {str(k): float(v) for k, v in vp.items()}
        return {
            '1': vp.direct_fte_cost_per_month,
            '2': vp.indirect_fte_cost_per_month,
            '3': vp.overhead_cost_per_month,
            '4': vp.sga_cost_per_month,
            '5': vp.depreciation_per_year,
            '6': vp.net_book_value,
            '7': vp.days_sales_outstanding,
            '8': vp.days_payable_outstanding,
        }

    @bp.route('/api/update_volume', methods=['POST'])
    def update_volume():
        sess, current_engine = get_active()
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400

        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON body'}), 400

        line_type = data.get('line_type')
        material_number = data.get('material_number')
        period = data.get('period')
        aux_column = str(data.get('aux_column', '') or '')
        new_value = float(data.get('new_value', 0))

        return apply_volume_change(
            sess,
            current_engine,
            line_type,
            material_number,
            period,
            new_value,
            aux_column=aux_column,
            push_undo=True,
        )

    @bp.route('/api/update_value_aux', methods=['POST'])
    def update_value_aux():
        sess, current_engine = get_active()
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400

        data = request.get_json() or {}
        line_type = data.get('line_type')
        material_number = data.get('material_number')
        try:
            new_value = float(data.get('new_value', 0))
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid aux value'}), 400

        if line_type not in value_aux_editable_line_types:
            return jsonify({'error': f'Value aux for line type "{line_type}" is not editable'}), 403

        rows = current_engine.value_results.get(line_type, [])
        target_row = next((row for row in rows if row.material_number == material_number), None)
        if target_row is None:
            return jsonify({'error': 'Value row not found'}), 404
        ensure_reset_baseline(sess, current_engine)

        try:
            old_value = float(target_row.aux_column or 0)
        except (TypeError, ValueError):
            return jsonify({'error': 'Current aux value is not numeric'}), 400

        override_key = f'{line_type}||{material_number}'
        overrides = sess.setdefault('value_aux_overrides', {})
        existing = overrides.get(override_key, {})
        original_value = float(existing.get('original', old_value)) if isinstance(existing, dict) else old_value

        if abs(new_value - original_value) < 1e-9:
            overrides.pop(override_key, None)
        else:
            overrides[override_key] = {
                'original': original_value,
                'new_value': new_value,
            }

        recalculate_value_results(current_engine, sess)
        save_sessions_to_disk()

        value_results_dict = {
            line_type_key: [row.to_dict() for row in rows_value]
            for line_type_key, rows_value in current_engine.value_results.items()
        }
        consolidation = [
            row.to_dict()
            for row in current_engine.value_results.get(LineType.CONSOLIDATION.value, [])
        ]
        delta_pct = round((new_value - original_value) / abs(original_value) * 100, 2) if original_value != 0 else 0.0

        return jsonify({
            'success': True,
            'value_results': value_results_dict,
            'consolidation': consolidation,
            'edit_meta': {
                'old_value': old_value,
                'new_value': new_value,
                'original_value': original_value,
                'delta_pct': delta_pct,
            },
            'value_aux_overrides': sess.get('value_aux_overrides', {}),
        })

    @bp.route('/api/reset_value_planning_edits', methods=['POST'])
    def reset_value_planning_edits():
        sess, current_engine = get_active()
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400

        sess['value_aux_overrides'] = {}

        recalculate_value_results(current_engine, sess)
        save_sessions_to_disk()

        value_results_dict = {
            line_type_key: [row.to_dict() for row in rows_value]
            for line_type_key, rows_value in current_engine.value_results.items()
        }
        consolidation = [
            row.to_dict()
            for row in current_engine.value_results.get(LineType.CONSOLIDATION.value, [])
        ]

        resp = {
            'success': True,
            'value_results': value_results_dict,
            'consolidation': consolidation,
            'value_aux_overrides': {},
        }
        return jsonify(resp)

    def _pop_group(from_stack: list) -> list:
        """Pop the last entry and, if it belongs to a bulk group, every further
        contiguous entry sharing its group_id (bulk pushes them together)."""
        entry = from_stack.pop()
        popped = [entry]
        gid = entry.get('group_id')
        if gid:
            while from_stack and from_stack[-1].get('group_id') == gid:
                popped.append(from_stack.pop())
        return popped

    def _apply_entries(sess, current_engine, entries, value_key):
        """Re-apply a batch of undo/redo entries and return one combined
        response. Single edits keep returning apply_volume_change's own
        response (preserving edit_meta for the caller). Grouped entries
        defer the whole-plan capacity+value recalc to one final pass."""
        if len(entries) == 1:
            e = entries[0]
            return apply_volume_change(
                sess, current_engine,
                e['line_type'], e['material_number'], e['period'],
                e[value_key], aux_column=e.get('aux_column', ''), push_undo=False,
            )
        for e in entries:
            apply_volume_change(
                sess, current_engine,
                e['line_type'], e['material_number'], e['period'],
                e[value_key], aux_column=e.get('aux_column', ''), push_undo=False,
                defer_recalc=True,
            )
        recalculate_capacity_and_values(current_engine, sess)
        return jsonify(_engine_state_response(current_engine, {'group_size': len(entries)}))

    @bp.route('/api/undo', methods=['POST'])
    def undo_edit():
        sess, current_engine = get_active()
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400
        undo_stack = sess.get('undo_stack', [])
        redo_stack = sess.setdefault('redo_stack', [])
        if not undo_stack:
            return jsonify({'error': 'Nothing to undo'}), 400

        entries = _pop_group(undo_stack)
        redo_stack.extend(entries)
        trim_stack_group_aware(redo_stack)
        # Reverting applies old_values in stack (reverse) order so cells that
        # share a material unwind to the true pre-bulk state.
        return _apply_entries(sess, current_engine, entries, 'old_value')

    @bp.route('/api/redo', methods=['POST'])
    def redo_edit():
        sess, current_engine = get_active()
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400
        undo_stack = sess.setdefault('undo_stack', [])
        redo_stack = sess.get('redo_stack', [])
        if not redo_stack:
            return jsonify({'error': 'Nothing to redo'}), 400

        entries = _pop_group(redo_stack)
        undo_stack.extend(entries)
        trim_stack_group_aware(undo_stack)
        # Reapply in forward (application) order.
        return _apply_entries(sess, current_engine, list(reversed(entries)), 'new_value')

    @bp.route('/api/update_volume_bulk', methods=['POST'])
    def update_volume_bulk():
        """Apply a batch of cell edits as one undoable group (Fase 1.2).

        Each cell goes through the same apply_volume_change cascade as a single
        edit, so a bulk result is identical to applying the cells one by one.
        The whole batch is one undo step (shared group_id)."""
        sess, current_engine = get_active()
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400

        data = request.get_json() or {}
        cells = data.get('cells', [])
        if not isinstance(cells, list) or not cells:
            return jsonify({'error': 'No cells to update'}), 400

        group_id = uuid.uuid4().hex
        undo_stack = sess.setdefault('undo_stack', [])
        applied = 0
        failed = []
        for cell in cells:
            try:
                line_type = cell['line_type']
                material_number = str(cell['material_number'])
                period = cell['period']
                aux_column = str(cell.get('aux_column', '') or '')
                new_value = float(cell['new_value'])
            except (KeyError, TypeError, ValueError):
                failed.append({'cell': cell, 'error': 'invalid cell payload'})
                continue
            resp = apply_volume_change(
                sess, current_engine, line_type, material_number, period,
                new_value, aux_column=aux_column, push_undo=False,
                defer_recalc=True,
            )
            payload = resp.get_json(silent=True) if hasattr(resp, 'get_json') else None
            if getattr(resp, 'status_code', 200) >= 400 or not (isinstance(payload, dict) and payload.get('success')):
                failed.append({'cell': cell, 'error': (payload or {}).get('error', 'apply failed')})
                continue
            if applied == 0:
                # First successful apply: only now is the batch a real edit
                # action, so only now may it invalidate redo history. A batch
                # that fails entirely must leave redo intact.
                sess.setdefault('redo_stack', []).clear()
            em = payload.get('edit_meta', {})
            undo_stack.append({
                'line_type': line_type,
                'material_number': material_number,
                'aux_column': aux_column,
                'period': period,
                'old_value': em.get('old_value', 0.0),
                'new_value': em.get('new_value', new_value),
                'group_id': group_id,
            })
            applied += 1
        trim_stack_group_aware(undo_stack)

        if applied == 0:
            return jsonify({'error': 'No cells could be updated', 'failed': failed}), 400

        # One whole-plan capacity+value recalc for the entire batch (the
        # per-cell volume cascades already ran with defer_recalc=True).
        recalculate_capacity_and_values(current_engine, sess)
        save_sessions_to_disk()
        return jsonify(_engine_state_response(current_engine, {
            'applied': applied,
            'failed': failed,
            'group_id': group_id,
        }))

    @bp.route('/api/edits/export')
    def export_edits():
        sess, current_engine = get_active()
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400

        edits = []
        for _, rows in current_engine.results.items():
            for row in rows:
                if row.manual_edits:
                    for period, edit_data in row.manual_edits.items():
                        original = edit_data.get('original', 0.0)
                        new_value = edit_data.get('new', 0.0)
                        delta_pct = round((new_value - original) / abs(original) * 100, 2) if original != 0 else 0.0
                        edits.append({
                            'line_type': row.line_type,
                            'material_number': row.material_number,
                            'aux_column': getattr(row, 'aux_column', '') or '',
                            'period': period,
                            'original': original,
                            'new': new_value,
                            'delta_pct': delta_pct,
                        })

        value_aux_edits = []
        for key, item in (sess or {}).get('value_aux_overrides', {}).items():
            try:
                line_type, material_number = key.split('||', 1)
                original = float(item.get('original', 0))
                new_value = float(item.get('new_value', original))
            except (AttributeError, TypeError, ValueError):
                continue
            delta_pct = round((new_value - original) / abs(original) * 100, 2) if original != 0 else 0.0
            value_aux_edits.append({
                'line_type': line_type,
                'material_number': material_number,
                'original': original,
                'new': new_value,
                'delta_pct': delta_pct,
            })

        export_data = {
            'exported_at': datetime.now().isoformat(),
            'edits': edits,
            'value_aux_edits': value_aux_edits,
        }
        buf = io.BytesIO(json.dumps(export_data, indent=2).encode('utf-8'))
        buf.seek(0)
        return send_file(buf, mimetype='application/json', as_attachment=True, download_name='edits.json')

    @bp.route('/api/edits/import', methods=['POST'])
    def import_edits():
        sess, current_engine = get_active()
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400

        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No JSON body'}), 400

            edits = data.get('edits', [])
            for edit in edits:
                line_type = edit.get('line_type')
                material_number = edit.get('material_number')
                period = edit.get('period')
                new_value = float(edit.get('new', 0))
                aux_column = str(edit.get('aux_column', '') or '')
                resp = apply_volume_change(
                    sess,
                    current_engine,
                    line_type,
                    material_number,
                    period,
                    new_value,
                    aux_column=aux_column,
                    push_undo=False,
                )
                if resp.status_code >= 400:
                    payload = resp.get_json(silent=True) or {}
                    return jsonify({'error': f'Could not import edit: {payload.get("error", "unknown error")}'}), resp.status_code

            value_aux_edits = data.get('value_aux_edits', [])
            if value_aux_edits:
                overrides = sess.setdefault('value_aux_overrides', {})
                for edit in value_aux_edits:
                    line_type = edit.get('line_type')
                    material_number = edit.get('material_number')
                    if line_type not in value_aux_editable_line_types:
                        continue
                    try:
                        original = float(edit.get('original', 0))
                        new_value = float(edit.get('new', original))
                    except (TypeError, ValueError):
                        continue
                    key = f'{line_type}||{material_number}'
                    if abs(new_value - original) < 1e-9:
                        overrides.pop(key, None)
                    else:
                        overrides[key] = {
                            'original': original,
                            'new_value': new_value,
                        }

            recalculate_value_results(current_engine, sess)
            save_sessions_to_disk()

            results_dict = {
                line_type_key: [row.to_dict() for row in rows]
                for line_type_key, rows in current_engine.results.items()
            }
            value_results_dict = {
                line_type_key: [row.to_dict() for row in rows]
                for line_type_key, rows in current_engine.value_results.items()
            }
            consolidation = [
                row.to_dict()
                for row in current_engine.value_results.get(LineType.CONSOLIDATION.value, [])
            ]

            return jsonify({
                'success': True,
                'results': results_dict,
                'value_results': value_results_dict,
                'consolidation': consolidation,
                'value_aux_overrides': sess.get('value_aux_overrides', {}),
            })
        except Exception as exc:
            import traceback
            return jsonify({'error': str(exc), 'trace': traceback.format_exc()}), 500

    @bp.route('/api/reset_edits', methods=['POST'])
    def reset_edits():
        sess, current_engine = get_active()
        if current_engine is None:
            return jsonify({'error': 'No calculations run'}), 400

        current_vp = _valuation_params_dict(current_engine)
        baseline = sess.get('reset_baseline')
        baseline_is_clean = (
            isinstance(baseline, dict)
            and baseline.get('results')
            and not snapshot_has_manual_edits(baseline)
        )
        if baseline_is_clean:
            restore_engine_state(current_engine, baseline)
            engine = current_engine
        else:
            engine = build_clean_engine_for_session(sess)
            if engine is None:
                return jsonify({'error': 'No clean reset baseline available. Recalculate this session first.'}), 400
            sess['engine'] = engine

        if getattr(engine, 'data', None) is not None:
            engine.data.valuation_params = valuation_params_from_config(current_vp) if current_vp else None
            global_config['valuation_params'] = current_vp
        sess['pending_edits'] = {}
        sess['value_aux_overrides'] = {}
        sess['undo_stack'] = []
        sess['redo_stack'] = []
        recalculate_value_results(engine, sess)
        install_clean_engine_baseline(sess, engine)
        save_sessions_to_disk()

        results_dict = {
            line_type_key: [row.to_dict() for row in rows]
            for line_type_key, rows in engine.results.items()
        }
        value_results_dict = {
            line_type_key: [row.to_dict() for row in rows]
            for line_type_key, rows in engine.value_results.items()
        }
        consolidation = [
            row.to_dict()
            for row in engine.value_results.get(LineType.CONSOLIDATION.value, [])
        ]

        resp = {
            'success': True,
            'results': results_dict,
            'value_results': value_results_dict,
            'consolidation': consolidation,
        }
        return jsonify(resp)

    return bp
