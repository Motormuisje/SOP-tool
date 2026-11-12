"""State fixes from the 2026-11 re-check of the bug register.

The common thread: what the user sees, what the engine holds and what a
restart replays must be the same thing. Each test names the entry it pins.
"""

from types import SimpleNamespace

import pytest

from modules.models import LineType
from ui import replay as replay_module
from ui.pending_edits import pending_edit_key
from ui.volume_change import apply_volume_change

# Fixtures defined next to the route tests they were written for.
from tests.test_routes_config import config_engine_app  # noqa: F401
from tests.test_routes_edit_state import edit_state_app  # noqa: F401
from tests.test_routes_edits import edits_mock_app  # noqa: F401
from tests.test_routes_pap import pap_route_app  # noqa: F401


# ---------------------------------------------------------------------------
# M18: an edited starting stock survives every later recalculation
# ---------------------------------------------------------------------------

def _status(response):
    if isinstance(response, tuple):
        return response[1]
    return response.status_code


def _row(engine, line_type, material):
    return next(r for r in engine.results.get(line_type, []) if r.material_number == material)


def _material_with_stock_and_forecast(engine):
    forecast_materials = {r.material_number for r in engine.results.get(LineType.DEMAND_FORECAST.value, [])}
    for row in engine.results.get(LineType.INVENTORY.value, []):
        if float(row.starting_stock or 0) > 0 and row.material_number in forecast_materials:
            return row.material_number
    raise AssertionError("No material with both a starting stock and a forecast row")


def _edit_forecast(app, sess, engine, material, delta=10.0):
    forecast_row = _row(engine, LineType.DEMAND_FORECAST.value, material)
    period = engine.data.periods[0]
    with app.app_context():
        return apply_volume_change(
            sess, engine, LineType.DEMAND_FORECAST.value, material, period,
            float(forecast_row.get_value(period)) + delta,
            aux_column=forecast_row.aux_column,
        )


def _edit_stock(app, sess, engine, material, value):
    with app.app_context():
        return apply_volume_change(
            sess, engine, LineType.INVENTORY.value, material, "starting_stock", value)


def test_edited_starting_stock_survives_a_later_forecast_edit(edit_route_app):
    """BUGS.md M18. The corrected stock used to fall back to the workbook
    value as soon as the same material was recalculated for another reason,
    while the cell kept its edit marker."""
    sess = edit_route_app.make_session()
    engine = sess["engine"]
    material = _material_with_stock_and_forecast(engine)
    edited = float(_row(engine, LineType.INVENTORY.value, material).starting_stock) + 1000.0

    assert _status(_edit_stock(edit_route_app.app, sess, engine, material, edited)) == 200
    assert _status(_edit_forecast(edit_route_app.app, sess, engine, material)) == 200

    assert _row(engine, LineType.INVENTORY.value, material).starting_stock == pytest.approx(edited)
    assert sess["inventory_overrides"][material] == pytest.approx(edited)


def test_live_edits_and_replay_agree_on_the_starting_stock(edit_route_app):
    """Replay is what a restart shows, so live and replay must hold the same
    inventory after 'starting stock, then forecast' on one material."""
    sess = edit_route_app.make_session()
    engine = sess["engine"]
    material = _material_with_stock_and_forecast(engine)
    edited = float(_row(engine, LineType.INVENTORY.value, material).starting_stock) + 1000.0
    _edit_stock(edit_route_app.app, sess, engine, material, edited)
    _edit_forecast(edit_route_app.app, sess, engine, material)
    live = _row(engine, LineType.INVENTORY.value, material)

    fresh = edit_route_app.make_session(session_id="replay-m18")
    fresh_engine = fresh["engine"]
    with edit_route_app.app.app_context():
        for key, edit in dict(sess["pending_edits"]).items():
            line_type, mat, aux, period = key.split("||")
            apply_volume_change(
                fresh, fresh_engine, line_type, mat, period, float(edit["new_value"]),
                aux_column=aux, push_undo=False)
    replayed = _row(fresh_engine, LineType.INVENTORY.value, material)

    assert replayed.starting_stock == pytest.approx(live.starting_stock) == pytest.approx(edited)
    for period in engine.data.periods:
        assert replayed.get_value(period) == pytest.approx(live.get_value(period)), period


def test_reverted_starting_stock_does_not_come_back(edit_route_app):
    """The other direction: once the stock edit is reverted, a later edit must
    compute from the workbook stock again, not from a leftover override."""
    sess = edit_route_app.make_session()
    engine = sess["engine"]
    material = _material_with_stock_and_forecast(engine)
    original = float(_row(engine, LineType.INVENTORY.value, material).starting_stock)

    _edit_stock(edit_route_app.app, sess, engine, material, original + 1000.0)
    _edit_stock(edit_route_app.app, sess, engine, material, original)
    _edit_forecast(edit_route_app.app, sess, engine, material)

    assert material not in sess.get("inventory_overrides", {})
    assert _row(engine, LineType.INVENTORY.value, material).starting_stock == pytest.approx(original)


# ---------------------------------------------------------------------------
# Replay must not die on an edit that removes its own pending key
# ---------------------------------------------------------------------------

@pytest.mark.no_fixture
def test_replay_survives_an_edit_that_removes_its_own_pending_key(monkeypatch):
    """A replayed edit that equals the fresh engine's value is a revert, and
    apply_volume_change then pops its key from pending_edits. Iterating the
    live dict raised 'dictionary changed size during iteration' and failed
    the whole rebuild (switch, calculate, warmup)."""
    # raising=False: this hook only exists in editions that carry the workbench.
    monkeypatch.setattr(replay_module, "recalculate_fte_results", lambda engine, sess: None, raising=False)
    lt = LineType.DEMAND_FORECAST.value
    sess = {"pending_edits": {
        pending_edit_key(lt, "MAT-A", "", "2025-01"): {"original": 1.0, "new_value": 2.0},
        pending_edit_key(lt, "MAT-B", "", "2025-01"): {"original": 3.0, "new_value": 4.0},
        pending_edit_key(lt, "MAT-C", "", "2025-01"): {"original": 5.0, "new_value": 6.0},
    }}
    applied = []

    def apply_and_drop_key(sess_arg, engine, line_type, material, period, new_value,
                           aux_column="", push_undo=True):
        applied.append(material)
        sess_arg["pending_edits"].pop(pending_edit_key(line_type, material, aux_column, period), None)
        return SimpleNamespace(status_code=200, get_json=lambda silent=True: {"success": True})

    replay_module.replay_pending_edits(
        sess, SimpleNamespace(), apply_and_drop_key,
        lambda engine, overrides: False, lambda engine, sess_arg: None)

    assert applied == ["MAT-A", "MAT-B", "MAT-C"]


# ---------------------------------------------------------------------------
# M21: the undo/redo stacks follow the engine
# ---------------------------------------------------------------------------

def _stack_entry(material, old=40.0, new=50.0):
    return {
        "line_type": LineType.DEMAND_FORECAST.value, "material_number": material,
        "period": "2025-12", "old_value": old, "new_value": new, "aux_column": "",
    }


@pytest.mark.no_fixture
def test_refused_undo_is_dropped_and_never_reaches_the_redo_stack(edits_mock_app):  # noqa: F811
    """BUGS.md M21. The entry used to be moved to redo before it was applied;
    a refusal then left an 'undone' step on the redo stack that was never
    undone, and redo bounced it back for ever."""
    edits_mock_app.make_session()
    older, refused = _stack_entry("MAT-0"), _stack_entry("MAT-1")
    edits_mock_app.sess["undo_stack"] = [older, refused]
    edits_mock_app.sess["redo_stack"] = []
    edits_mock_app.fail_next_volume_call = True

    response = edits_mock_app.client.post("/api/undo")

    assert response.status_code == 400
    assert edits_mock_app.sess["undo_stack"] == [older]
    assert edits_mock_app.sess["redo_stack"] == []
    assert edits_mock_app.volume_calls == []

    # The step below it is still reachable.
    response = edits_mock_app.client.post("/api/undo")
    assert response.status_code == 200
    assert edits_mock_app.sess["undo_stack"] == []
    assert edits_mock_app.sess["redo_stack"] == [older]


@pytest.mark.no_fixture
def test_refused_redo_is_dropped_and_never_reaches_the_undo_stack(edits_mock_app):  # noqa: F811
    edits_mock_app.make_session()
    edits_mock_app.sess["undo_stack"] = []
    edits_mock_app.sess["redo_stack"] = [_stack_entry("MAT-1")]
    edits_mock_app.fail_next_volume_call = True

    response = edits_mock_app.client.post("/api/redo")

    assert response.status_code == 400
    assert edits_mock_app.sess["redo_stack"] == []
    assert edits_mock_app.sess["undo_stack"] == []


# ---------------------------------------------------------------------------
# L13 / L14: malformed and out-of-range numbers are refused with a 400
# ---------------------------------------------------------------------------

@pytest.mark.no_fixture
@pytest.mark.parametrize("bad", ["abc", None, "nan", "inf", "-inf"])
def test_update_volume_refuses_a_malformed_or_non_finite_value(edits_mock_app, bad):  # noqa: F811
    edits_mock_app.make_session()

    response = edits_mock_app.client.post("/api/update_volume", json={
        "line_type": LineType.DEMAND_FORECAST.value, "material_number": "MAT-1",
        "period": "2025-12", "new_value": bad,
    })

    assert response.status_code == 400
    assert edits_mock_app.volume_calls == []


@pytest.mark.no_fixture
@pytest.mark.parametrize("bad", [50, -0.1, 1.01, "nan", "inf"])
def test_pap_fraction_outside_zero_to_one_is_refused(pap_route_app, bad):  # noqa: F811
    """BUGS.md L13. 50 instead of 0.5 planned production at fifty times the
    need and turned the raw-material cost negative, without any error."""
    response = pap_route_app.client.post("/api/pap", json={"material_number": "MAT-1", "fraction": bad})

    assert response.status_code == 400
    assert pap_route_app.engine.data.purchased_and_produced == {"MAT-1": 0.25}
    assert pap_route_app.baseline_calls == []
    assert pap_route_app.recalc_calls == []


@pytest.mark.no_fixture
@pytest.mark.parametrize("ok", [0, 0.5, 1])
def test_pap_fraction_bounds_are_inclusive(pap_route_app, ok):  # noqa: F811
    response = pap_route_app.client.post("/api/pap", json={"material_number": "MAT-1", "fraction": ok})

    assert response.status_code == 200, response.get_json()
    assert pap_route_app.engine.data.purchased_and_produced["MAT-1"] == pytest.approx(float(ok))


@pytest.mark.no_fixture
def test_settings_refuse_an_out_of_range_pap_before_touching_anything(config_engine_app):  # noqa: F811
    before = dict(config_engine_app.global_config)

    response = config_engine_app.client.post(
        "/api/config/settings", json={"purchased_and_produced": "MAT-1:50"})

    assert response.status_code == 400
    assert "MAT-1:50" in response.get_json()["error"]
    assert config_engine_app.global_config == before
    assert config_engine_app.pap_calls == []


@pytest.mark.no_fixture
def test_persist_edit_refuses_a_malformed_number(edit_state_app):  # noqa: F811
    session_id = edit_state_app.add_session()

    response = edit_state_app.client.post("/api/sessions/edits/persist", json={
        "session_id": session_id, "key": "01. Demand forecast||MAT-1||||2025-12",
        "original": 1, "new_value": "abc",
    })

    assert response.status_code == 400
    assert edit_state_app.sessions[session_id]["pending_edits"] == {}


@pytest.mark.no_fixture
def test_sync_edits_is_all_or_nothing_and_uses_canonical_keys(edit_state_app):  # noqa: F811
    session_id = edit_state_app.add_session()
    kept = {"01. Demand forecast||MAT-0||||2025-12": {"original": 1.0, "new_value": 2.0}}
    edit_state_app.sessions[session_id]["pending_edits"] = dict(kept)

    response = edit_state_app.client.post("/api/sessions/edits/sync", json={
        "session_id": session_id,
        "edits": {
            "01. Demand forecast||MAT-1||||2025-12": {"original": 1, "new_value": 2},
            "01. Demand forecast||MAT-2||||2025-12": {"original": 1, "new_value": "abc"},
        },
    })
    assert response.status_code == 400
    assert edit_state_app.sessions[session_id]["pending_edits"] == kept

    response = edit_state_app.client.post("/api/sessions/edits/sync", json={
        "session_id": session_id,
        "edits": {"01. Demand forecast||MAT-1|| 150 ||2025-12": {"original": 1, "new_value": 2}},
    })
    assert response.status_code == 200
    assert edit_state_app.sessions[session_id]["pending_edits"] == {
        "01. Demand forecast||MAT-1||150||2025-12": {"original": 1.0, "new_value": 2.0}}
