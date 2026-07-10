"""Replay and value recalculation helpers for UI session rebuilds."""

from typing import Callable

from modules.value_planning_engine import ValuePlanningEngine


def get_value_aux_override_values(sess) -> dict:
    overrides = {}
    for key, item in (sess or {}).get('value_aux_overrides', {}).items():
        try:
            if isinstance(item, dict):
                overrides[key] = float(item.get('new_value', 0))
            else:
                overrides[key] = float(item)
        except (TypeError, ValueError):
            continue
    return overrides


def recalculate_value_results(engine, sess=None) -> None:
    aux_overrides = get_value_aux_override_values(sess)
    engine.value_engine = ValuePlanningEngine(
        engine.data,
        engine.results,
        aux_overrides=aux_overrides,
    )
    engine.value_results = engine.value_engine.calculate()
    engine._iq_cache = None


def replay_pending_edits(
    sess: dict,
    engine,
    apply_volume_change: Callable,
    apply_machine_overrides: Callable[[object, dict], bool],
    recalculate_capacity_and_values: Callable[[object, dict], None],
) -> None:
    """Re-apply saved pending_edits onto a freshly-run engine."""
    # Pre-clear the override stores: replay re-populates them as it walks
    # pending_edits through apply_volume_change. Skipping this would double
    # any L4/L7/L9/L11/L12 entry that was already in the saved session JSON
    # before the rebuild.
    sess['inventory_overrides'] = {}
    sess['capacity_overrides'] = {}

    pending = sess.get('pending_edits', {})
    overrides_present = bool((sess or {}).get('value_aux_overrides'))
    machine_overrides_present = bool((sess or {}).get('machine_overrides'))
    if not pending:
        if overrides_present:
            recalculate_value_results(engine, sess)
        if machine_overrides_present and apply_machine_overrides(engine, sess.get('machine_overrides') or {}):
            recalculate_capacity_and_values(engine, sess)
        return

    for key, edit in pending.items():
        try:
            parts = key.split('||')
            if len(parts) != 4:
                continue
            lt, mat, aux, period = parts
            new_val = float(edit.get('new_value', 0))
            response = apply_volume_change(
                sess,
                engine,
                lt,
                mat,
                period,
                new_val,
                aux_column=aux,
                push_undo=False,
            )
            # apply_volume_change always returns a Response object (error
            # paths included), so every non-success outcome can be logged.
            # A payload without success=True (e.g. {'error': ...} from a
            # 403/404) means the edit was NOT applied — say so instead of
            # dropping it silently, but keep replaying the remaining edits.
            payload = response.get_json(silent=True) if hasattr(response, 'get_json') else None
            if not isinstance(payload, dict) or payload.get('success') is not True:
                detail = payload if payload is not None else getattr(response, 'status_code', response)
                print(f'[replay_pending_edits] skipped "{key}": {detail}')
        except Exception as exc:
            print(f'[replay_pending_edits] failed "{key}": {exc}')
    if machine_overrides_present and apply_machine_overrides(engine, sess.get('machine_overrides') or {}):
        recalculate_capacity_and_values(engine, sess)

    if overrides_present:
        recalculate_value_results(engine, sess)
