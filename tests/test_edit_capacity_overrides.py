"""Integration tests for editable capacity lines via apply_volume_change."""

import pytest

from modules.models import LineType
from ui.volume_change import apply_volume_change


def _response_parts(response):
    if isinstance(response, tuple):
        body, status = response
        return status, body.get_json()
    return response.status_code, response.get_json()


def _first_row_with_value(engine, line_type):
    for row in engine.results.get(line_type, []):
        for period, value in row.values.items():
            if value is not None:
                return row, period, float(value or 0.0)
    raise AssertionError(f"No row with values for {line_type}")


def _matching_row(engine, line_type, material_number, aux_column):
    rows = [
        row for row in engine.results.get(line_type, [])
        if row.material_number == material_number
    ]
    for row in rows:
        if str(row.aux_column or "") == str(aux_column or ""):
            return row
    if len(rows) == 1:
        return rows[0]
    raise AssertionError(f"No matching row for {line_type} / {material_number} / {aux_column}")


def test_l9_edit_restores_manual_edit_marker_after_capacity_recalc(edit_route_app):
    sess = edit_route_app.make_session()
    engine = sess["engine"]
    target_row, period, original = _first_row_with_value(
        engine, LineType.AVAILABLE_CAPACITY.value
    )
    new_value = original + 0.01

    with edit_route_app.app.app_context():
        response = apply_volume_change(
            sess,
            engine,
            LineType.AVAILABLE_CAPACITY.value,
            target_row.material_number,
            period,
            new_value,
            aux_column=target_row.aux_column or "",
        )

    status, payload = _response_parts(response)
    assert status == 200
    assert payload["success"] is True

    refreshed = _matching_row(
        engine,
        LineType.AVAILABLE_CAPACITY.value,
        target_row.material_number,
        target_row.aux_column,
    )
    assert refreshed.manual_edits[period] == {
        "original": pytest.approx(original),
        "new": pytest.approx(new_value),
    }


def test_l7_edit_then_revert_clears_capacity_override_and_pending_edit(edit_route_app):
    """Undoing an L07 edit must unpin the capacity override (live == replay)."""
    sess = edit_route_app.make_session()
    engine = sess["engine"]
    target_row, period, original = _first_row_with_value(
        engine, LineType.CAPACITY_UTILIZATION.value
    )
    material = target_row.material_number
    aux = target_row.aux_column or ""
    line_type = LineType.CAPACITY_UTILIZATION.value

    with edit_route_app.app.app_context():
        response = apply_volume_change(
            sess, engine, line_type, material, period, original + 5.0, aux_column=aux,
        )
    status, payload = _response_parts(response)
    assert status == 200
    assert payload["success"] is True
    assert sess["capacity_overrides"][line_type][material][period] == pytest.approx(original + 5.0)
    assert sess["pending_edits"]

    # Simulate undo: apply the original value back (within float tolerance).
    with edit_route_app.app.app_context():
        response = apply_volume_change(
            sess, engine, line_type, material, period, original + 1e-12, aux_column=aux,
        )
    status, payload = _response_parts(response)
    assert status == 200
    assert payload["success"] is True
    # No leftover override entry — empty inner dicts must be pruned too,
    # otherwise the value stays pinned against upstream cascades on the live
    # engine while a restart (replay from pending_edits) leaves it unpinned.
    assert sess["capacity_overrides"] == {}
    assert sess["pending_edits"] == {}

    refreshed = _matching_row(engine, line_type, material, target_row.aux_column)
    assert period not in refreshed.manual_edits


def test_l4_edit_then_revert_clears_inventory_override_and_pending_edit(edit_route_app):
    """Undoing an L04 starting-stock edit must unpin the inventory override."""
    sess = edit_route_app.make_session()
    engine = sess["engine"]
    target_row = next(
        row for row in engine.results.get(LineType.INVENTORY.value, [])
        if float(row.starting_stock or 0.0) > 0
    )
    original = float(target_row.starting_stock)
    material = target_row.material_number

    with edit_route_app.app.app_context():
        response = apply_volume_change(
            sess, engine, LineType.INVENTORY.value, material, "starting_stock", original + 10.0,
        )
    status, payload = _response_parts(response)
    assert status == 200
    assert payload["success"] is True
    assert sess["inventory_overrides"][material] == pytest.approx(original + 10.0)
    assert sess["pending_edits"]

    # Simulate undo: apply the original starting stock back.
    with edit_route_app.app.app_context():
        response = apply_volume_change(
            sess, engine, LineType.INVENTORY.value, material, "starting_stock", original,
        )
    status, payload = _response_parts(response)
    assert status == 200
    assert payload["success"] is True
    assert sess["inventory_overrides"] == {}
    assert sess["pending_edits"] == {}

    refreshed = _matching_row(
        engine, LineType.INVENTORY.value, material, target_row.aux_column
    )
    assert float(refreshed.starting_stock) == pytest.approx(original)
    assert "starting_stock" not in refreshed.manual_edits


def test_l4_edit_restores_starting_stock_manual_edit_marker(edit_route_app):
    sess = edit_route_app.make_session()
    engine = sess["engine"]
    target_row = next(
        row for row in engine.results.get(LineType.INVENTORY.value, [])
        if float(row.starting_stock or 0.0) > 0
    )
    original = float(target_row.starting_stock)
    new_value = original + 10.0

    with edit_route_app.app.app_context():
        response = apply_volume_change(
            sess,
            engine,
            LineType.INVENTORY.value,
            target_row.material_number,
            "starting_stock",
            new_value,
        )

    status, payload = _response_parts(response)
    assert status == 200
    assert payload["success"] is True

    refreshed = _matching_row(
        engine,
        LineType.INVENTORY.value,
        target_row.material_number,
        target_row.aux_column,
    )
    assert refreshed.manual_edits["starting_stock"] == {
        "original": pytest.approx(original),
        "new": pytest.approx(new_value),
    }
