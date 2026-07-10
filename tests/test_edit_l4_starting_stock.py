"""Integration tests for L4 starting-stock edits via apply_volume_change.

Only the sentinel period 'starting_stock' is editable for L4. Period values
are derived from the inventory engine and remain read-only.
"""

import pytest

from modules.models import LineType
from ui.volume_change import apply_volume_change


def _response_parts(response):
    if isinstance(response, tuple):
        body, status = response
        return status, body.get_json()
    return response.status_code, response.get_json()


def _l4_row_with_stock(engine):
    for row in engine.results.get(LineType.INVENTORY.value, []):
        if float(row.starting_stock or 0) > 0:
            return row
    raise AssertionError("No L4 inventory row with positive starting stock")


def test_l4_starting_stock_edit_updates_inventory(edit_route_app):
    sess = edit_route_app.make_session()
    engine = sess["engine"]
    target_row = _l4_row_with_stock(engine)
    period = engine.data.periods[0]
    old_period_value = target_row.get_value(period)
    new_starting = float(target_row.starting_stock) + 1000.0

    with edit_route_app.app.app_context():
        response = apply_volume_change(
            sess,
            engine,
            LineType.INVENTORY.value,
            target_row.material_number,
            "starting_stock",
            new_starting,
        )

    status, payload = _response_parts(response)
    assert status == 200
    assert payload["success"] is True
    # Re-locate row after recalc.
    refreshed = next(
        r for r in engine.results.get(LineType.INVENTORY.value, [])
        if r.material_number == target_row.material_number
    )
    assert refreshed.starting_stock == pytest.approx(new_starting)
    # Increasing starting stock must change the projected period values.
    assert refreshed.get_value(period) != pytest.approx(old_period_value)


def test_l4_period_edit_returns_403(edit_route_app):
    sess = edit_route_app.make_session()
    engine = sess["engine"]
    target_row = _l4_row_with_stock(engine)
    period = engine.data.periods[0]

    with edit_route_app.app.app_context():
        response = apply_volume_change(
            sess,
            engine,
            LineType.INVENTORY.value,
            target_row.material_number,
            period,
            123.0,
        )

    status, payload = _response_parts(response)
    assert status == 403
    assert "starting stock" in payload["error"].lower()


def test_l4_starting_stock_edit_persists_in_inventory_overrides(edit_route_app):
    sess = edit_route_app.make_session()
    engine = sess["engine"]
    target_row = _l4_row_with_stock(engine)
    new_starting = float(target_row.starting_stock) + 250.0

    with edit_route_app.app.app_context():
        apply_volume_change(
            sess,
            engine,
            LineType.INVENTORY.value,
            target_row.material_number,
            "starting_stock",
            new_starting,
        )

    assert sess["inventory_overrides"][target_row.material_number] == pytest.approx(new_starting)


def test_l4_starting_stock_undo(edit_route_app):
    sess = edit_route_app.make_session()
    engine = sess["engine"]
    target_row = _l4_row_with_stock(engine)
    original = float(target_row.starting_stock)
    new_starting = original + 500.0

    with edit_route_app.app.app_context():
        apply_volume_change(
            sess,
            engine,
            LineType.INVENTORY.value,
            target_row.material_number,
            "starting_stock",
            new_starting,
        )
        # Undo by reapplying the original value.
        apply_volume_change(
            sess,
            engine,
            LineType.INVENTORY.value,
            target_row.material_number,
            "starting_stock",
            original,
        )

    refreshed = next(
        r for r in engine.results.get(LineType.INVENTORY.value, [])
        if r.material_number == target_row.material_number
    )
    assert refreshed.starting_stock == pytest.approx(original)
    # Setting back to the original removes the pending edit. The override
    # store still records the explicit user-supplied value (now == original);
    # the important invariant is determinism on replay, covered separately.
    assert (
        sess["inventory_overrides"].get(target_row.material_number, original)
        == pytest.approx(original)
    )


def test_l4_starting_stock_replay_deterministic(edit_route_app):
    sess = edit_route_app.make_session()
    engine = sess["engine"]
    target_row = _l4_row_with_stock(engine)
    period = engine.data.periods[0]
    v1 = float(target_row.starting_stock) + 100.0
    v2 = v1 + 50.0

    with edit_route_app.app.app_context():
        apply_volume_change(
            sess, engine, LineType.INVENTORY.value,
            target_row.material_number, "starting_stock", v1,
        )
        apply_volume_change(
            sess, engine, LineType.INVENTORY.value,
            target_row.material_number, "starting_stock", v2,
        )

    live_starting = next(
        r for r in engine.results.get(LineType.INVENTORY.value, [])
        if r.material_number == target_row.material_number
    ).starting_stock
    live_period = next(
        r for r in engine.results.get(LineType.INVENTORY.value, [])
        if r.material_number == target_row.material_number
    ).get_value(period)
    pending = dict(sess["pending_edits"])

    # Rebuild a clean engine and replay pending_edits.
    fresh_sess = edit_route_app.make_session(session_id="replay-l4")
    fresh_engine = fresh_sess["engine"]
    with edit_route_app.app.app_context():
        for key, edit in pending.items():
            lt, mat, aux, period_key = key.split("||")
            apply_volume_change(
                fresh_sess, fresh_engine, lt, mat, period_key,
                float(edit["new_value"]),
                aux_column=aux, push_undo=False,
            )

    replayed = next(
        r for r in fresh_engine.results.get(LineType.INVENTORY.value, [])
        if r.material_number == target_row.material_number
    )
    assert replayed.starting_stock == pytest.approx(live_starting)
    assert replayed.get_value(period) == pytest.approx(live_period)
