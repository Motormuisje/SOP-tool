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
    edits_mock_app.fail_status = 404  # row gone: can never apply
    edits_mock_app.fail_next_volume_call = True

    response = edits_mock_app.client.post("/api/undo")

    assert response.status_code == 404
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
    edits_mock_app.fail_status = 404  # row gone: can never apply
    edits_mock_app.fail_next_volume_call = True

    response = edits_mock_app.client.post("/api/redo")

    assert response.status_code == 404
    assert edits_mock_app.sess["redo_stack"] == []
    assert edits_mock_app.sess["undo_stack"] == []


@pytest.mark.no_fixture
def test_undo_with_a_non_permanent_error_keeps_the_step(edits_mock_app):  # noqa: F811
    """Only 403/404 mean 'can never apply'. Any other error leaves the step
    on the stack it came from, to be tried again."""
    edits_mock_app.make_session()
    entry = _stack_entry("MAT-1")
    edits_mock_app.sess["undo_stack"] = [entry]
    edits_mock_app.sess["redo_stack"] = []
    edits_mock_app.fail_status = 400
    edits_mock_app.fail_next_volume_call = True

    response = edits_mock_app.client.post("/api/undo")

    assert response.status_code == 400
    assert edits_mock_app.sess["undo_stack"] == [entry]
    assert edits_mock_app.sess["redo_stack"] == []


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


# ---------------------------------------------------------------------------
# Round 2 (review by a second model): bulk undo is all-or-nothing
# ---------------------------------------------------------------------------

def _forecast_cells(engine, count=3):
    cells = []
    for row in engine.results.get(LineType.DEMAND_FORECAST.value, []):
        period = engine.data.periods[1]
        if float(row.get_value(period)) > 0:
            cells.append((row.material_number, row.aux_column, period, float(row.get_value(period))))
        if len(cells) == count:
            return cells
    raise AssertionError("not enough forecast cells with a value")


def _snapshot_numbers(engine):
    from ui.pending_edits import aux_str
    out = {}
    for lt, rows in engine.results.items():
        for r in rows:
            out.setdefault((lt, str(r.material_number), aux_str(r.aux_column)), []).append(
                {p: round(float(v), 6) for p, v in r.values.items()})
    return out


def _undo_client(sess, apply_fn):
    """The real edits blueprint around one live session, with the real
    engine snapshot/restore (the shared fixture stubs those out)."""
    from flask import Flask

    from ui.routes.edits import create_edits_blueprint
    from ui.state_snapshot import restore_engine_state

    def unused(*args, **kwargs):
        raise AssertionError("not expected in this test")

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = True
    app.register_blueprint(create_edits_blueprint(
        lambda: (sess, sess["engine"]), set(), {}, apply_fn,
        unused, unused, lambda: None, unused,
        lambda engine, snapshot: restore_engine_state(engine, snapshot, {}),
        unused, unused, unused,
    ))
    return app.test_client()


def test_bulk_undo_that_fails_halfway_leaves_engine_and_history_untouched(edit_route_app):
    """A bulk undo applies its cells one by one. When the third raises, the
    first two used to stay applied while both stacks were put back: the
    history then described a plan the engine no longer held."""
    sess = edit_route_app.make_session()
    engine = sess["engine"]
    cells = _forecast_cells(engine)
    group = "bulk-1"
    with edit_route_app.app.app_context():
        for mat, aux, period, value in cells:
            apply_volume_change(sess, engine, LineType.DEMAND_FORECAST.value, mat, period,
                                value + 100.0, aux_column=aux)
    for entry in sess["undo_stack"][-3:]:
        entry["group_id"] = group
    before_numbers = _snapshot_numbers(engine)
    before_pending = dict(sess["pending_edits"])
    before_undo = [dict(e) for e in sess["undo_stack"]]

    calls = {"n": 0}

    def failing_apply(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("injected failure on the third cell")
        return apply_volume_change(*args, **kwargs)

    client = _undo_client(sess, failing_apply)
    with pytest.raises(RuntimeError):
        client.post("/api/undo")
    assert calls["n"] == 3

    assert _snapshot_numbers(engine) == before_numbers
    assert sess["pending_edits"] == before_pending
    assert [dict(e) for e in sess["undo_stack"]] == before_undo
    assert sess.get("redo_stack", []) == []


def test_bulk_undo_completes_and_moves_the_whole_group(edit_route_app):
    sess = edit_route_app.make_session()
    engine = sess["engine"]
    cells = _forecast_cells(engine)
    before_numbers = _snapshot_numbers(engine)
    with edit_route_app.app.app_context():
        for mat, aux, period, value in cells:
            apply_volume_change(sess, engine, LineType.DEMAND_FORECAST.value, mat, period,
                                value + 100.0, aux_column=aux)
    for entry in sess["undo_stack"][-3:]:
        entry["group_id"] = "bulk-2"

    response = _undo_client(sess, apply_volume_change).post("/api/undo")

    assert response.status_code == 200, response.get_json()
    assert len(sess["redo_stack"]) == 3
    assert sess["pending_edits"] == {}
    after_numbers = _snapshot_numbers(engine)
    for key, values in before_numbers.items():
        if key[0] == LineType.DEMAND_FORECAST.value:
            assert after_numbers[key] == values, key


@pytest.mark.no_fixture
@pytest.mark.parametrize("edits", [
    {"": {"original": 1, "new_value": 2}},
    {"01. Demand forecast||MAT-1||150||2025-12": {"original": 1, "new_value": 2},
     "01. Demand forecast||MAT-1|| 150 ||2025-12": {"original": 1, "new_value": 3}},
])
def test_sync_refuses_empty_or_conflicting_keys(edit_state_app, edits):  # noqa: F811
    session_id = edit_state_app.add_session()
    kept = {"01. Demand forecast||MAT-0||||2025-12": {"original": 1.0, "new_value": 2.0}}
    edit_state_app.sessions[session_id]["pending_edits"] = dict(kept)

    response = edit_state_app.client.post(
        "/api/sessions/edits/sync", json={"session_id": session_id, "edits": edits})

    assert response.status_code == 400
    assert edit_state_app.sessions[session_id]["pending_edits"] == kept



@pytest.mark.no_fixture
def test_a_number_too_large_for_a_float_is_refused_not_a_500(edit_state_app):  # noqa: F811
    """json.loads turns a 400-digit literal into a Python int; float() then
    raises OverflowError, which the first version of the helper did not catch."""
    session_id = edit_state_app.add_session()
    body = ('{"session_id": "%s", "key": "01. Demand forecast||MAT-1||||2025-12", '
            '"original": 1, "new_value": 1%s}') % (session_id, '0' * 400)

    response = edit_state_app.client.post('/api/sessions/edits/persist', data=body,
                                          content_type='application/json')

    assert response.status_code == 400


def test_failed_bulk_redo_removes_a_store_the_step_created(edit_route_app):
    """Mutation test gap: when a store did not exist before the step, the
    rollback must remove it again. Redo is the path that creates one: it
    applies a new starting stock, and the starting-stock store comes into
    being with it (undoing to the original never creates it)."""
    sess = edit_route_app.make_session()
    engine = sess["engine"]
    material = next(r.material_number for r in engine.results[LineType.INVENTORY.value]
                    if float(r.starting_stock or 0) > 0)
    original = float(_row(engine, LineType.INVENTORY.value, material).starting_stock)
    mat, aux, period, value = _forecast_cells(engine, count=1)[0]
    sess.pop("inventory_overrides", None)
    sess["undo_stack"] = []
    # _pop_group takes the top entry first and redo replays in reverse, so the
    # stack's bottom entry runs first: the starting stock, then the forecast.
    sess["redo_stack"] = [
        {"line_type": LineType.INVENTORY.value, "material_number": material, "aux_column": "",
         "period": "starting_stock", "old_value": original, "new_value": original + 500.0, "group_id": "g"},
        {"line_type": LineType.DEMAND_FORECAST.value, "material_number": mat, "aux_column": aux,
         "period": period, "old_value": value, "new_value": value + 100.0, "group_id": "g"},
    ]
    applied = []
    calls = {"n": 0}

    def failing_apply(*args, **kwargs):
        calls["n"] += 1
        applied.append(args[2])
        if calls["n"] == 2:
            raise RuntimeError("injected failure on the second cell")
        return apply_volume_change(*args, **kwargs)

    with pytest.raises(RuntimeError):
        _undo_client(sess, failing_apply).post("/api/redo")

    # The store was created by the first step; the test is only meaningful if so.
    assert applied == [LineType.INVENTORY.value, LineType.DEMAND_FORECAST.value]
    assert "inventory_overrides" not in sess
    assert _row(engine, LineType.INVENTORY.value, material).starting_stock == pytest.approx(original)
