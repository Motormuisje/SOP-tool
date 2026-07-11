"""Fase 1.2 — bulk edit endpoint + grouped undo/redo (real engine)."""

from flask import Flask

from modules.models import LineType
from modules.planning_engine import PlanningEngine
from ui.routes.edits import create_edits_blueprint
from ui.volume_change import apply_volume_change


def _build_engine(golden_fixture_path):
    engine = PlanningEngine(
        str(golden_fixture_path),
        planning_month="2025-12",
        months_actuals=11,
        months_forecast=12,
    )
    engine.run()
    return engine


def _make_app(engine):
    sess = {
        "id": "bulk", "engine": engine, "pending_edits": {},
        "undo_stack": [], "redo_stack": [], "value_aux_overrides": {},
        "capacity_overrides": {}, "inventory_overrides": {},
    }

    def get_active():
        return sess, engine

    def crash(*a, **k):
        raise RuntimeError("unexpected callback in bulk test")

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_edits_blueprint(
        get_active,
        set(),
        {},
        apply_volume_change,
        crash,                # ensure_reset_baseline (real apply_volume_change uses its own)
        crash,                # recalculate_value_results
        lambda: None,         # save_sessions_to_disk
        crash, crash, crash, crash, crash,
    ))
    return app, sess


def _first_demand_materials(engine, n):
    rows = engine.results.get(LineType.DEMAND_FORECAST.value, [])
    return [r.material_number for r in rows[:n]]


def _l01_value(engine, mat, period):
    for r in engine.results.get(LineType.DEMAND_FORECAST.value, []):
        if r.material_number == mat:
            return r.values.get(period, 0.0)
    return None


def test_bulk_edit_applies_group_and_undo_redo_round_trip(golden_fixture_path):
    engine = _build_engine(golden_fixture_path)
    app, sess = _make_app(engine)
    client = app.test_client()

    period = engine.data.periods[3]
    mats = _first_demand_materials(engine, 3)
    baseline = {m: _l01_value(engine, m, period) for m in mats}
    targets = {m: (baseline[m] or 0.0) + 250.0 for m in mats}

    resp = client.post("/api/update_volume_bulk", json={
        "cells": [
            {"line_type": LineType.DEMAND_FORECAST.value, "material_number": m,
             "aux_column": "", "period": period, "new_value": targets[m]}
            for m in mats
        ]
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["applied"] == 3
    assert body["failed"] == []
    for m in mats:
        assert abs(_l01_value(engine, m, period) - targets[m]) < 1e-6

    # One group undo reverts ALL three cells.
    assert len(sess["undo_stack"]) == 3
    undo = client.post("/api/undo")
    assert undo.status_code == 200
    for m in mats:
        assert abs(_l01_value(engine, m, period) - (baseline[m] or 0.0)) < 1e-6
    assert sess["undo_stack"] == []
    assert len(sess["redo_stack"]) == 3

    # One group redo reapplies ALL three.
    redo = client.post("/api/redo")
    assert redo.status_code == 200
    for m in mats:
        assert abs(_l01_value(engine, m, period) - targets[m]) < 1e-6
    assert len(sess["undo_stack"]) == 3


def test_bulk_edit_equals_sequential_single_edits(golden_fixture_path):
    """TP1-04: a bulk apply must equal applying the same cells one by one."""
    period_idx = 4
    eng_bulk = _build_engine(golden_fixture_path)
    eng_seq = _build_engine(golden_fixture_path)
    app_bulk, _ = _make_app(eng_bulk)
    app_seq, sess_seq = _make_app(eng_seq)

    period = eng_bulk.data.periods[period_idx]
    mats = _first_demand_materials(eng_bulk, 3)
    targets = {m: (_l01_value(eng_bulk, m, period) or 0.0) + 137.0 for m in mats}

    app_bulk.test_client().post("/api/update_volume_bulk", json={
        "cells": [
            {"line_type": LineType.DEMAND_FORECAST.value, "material_number": m,
             "aux_column": "", "period": period, "new_value": targets[m]}
            for m in mats
        ]
    })

    with app_seq.test_request_context():
        for m in mats:
            apply_volume_change(
                sess_seq, eng_seq, LineType.DEMAND_FORECAST.value, m, period,
                targets[m], aux_column="", push_undo=False,
            )

    # Compare every line type / material / period between the two engines.
    for lt in eng_bulk.results:
        bulk_rows = {(r.material_number, r.aux_column): r for r in eng_bulk.results[lt]}
        seq_rows = {(r.material_number, r.aux_column): r for r in eng_seq.results.get(lt, [])}
        assert bulk_rows.keys() == seq_rows.keys(), lt
        for key, br in bulk_rows.items():
            sr = seq_rows[key]
            for p, bv in br.values.items():
                assert abs(bv - sr.values.get(p, 0.0)) < 1e-6, (lt, key, p)


def test_bulk_edit_rejects_empty_and_reports_failures(golden_fixture_path):
    engine = _build_engine(golden_fixture_path)
    app, _ = _make_app(engine)
    client = app.test_client()

    assert client.post("/api/update_volume_bulk", json={"cells": []}).status_code == 400

    # A non-editable line type fails per-cell, not the whole request.
    mats = _first_demand_materials(engine, 1)
    period = engine.data.periods[0]
    resp = client.post("/api/update_volume_bulk", json={"cells": [
        {"line_type": LineType.DEMAND_FORECAST.value, "material_number": mats[0],
         "aux_column": "", "period": period, "new_value": 123.0},
        {"line_type": LineType.DEPENDENT_DEMAND.value, "material_number": mats[0],
         "aux_column": "", "period": period, "new_value": 5.0},
    ]})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["applied"] == 1
    assert len(body["failed"]) == 1


def test_bulk_all_failed_preserves_redo_stack(golden_fixture_path):
    """F6: a fully-failed batch must not destroy redo history."""
    engine = _build_engine(golden_fixture_path)
    app, sess = _make_app(engine)
    client = app.test_client()

    period = engine.data.periods[2]
    mat = _first_demand_materials(engine, 1)[0]
    baseline = _l01_value(engine, mat, period)

    # One valid bulk edit, then undo -> redo stack holds the group.
    client.post("/api/update_volume_bulk", json={"cells": [
        {"line_type": LineType.DEMAND_FORECAST.value, "material_number": mat,
         "aux_column": "", "period": period, "new_value": (baseline or 0.0) + 10}]})
    client.post("/api/undo")
    assert len(sess["redo_stack"]) == 1

    # A batch where every cell fails (non-editable line type) -> 400, redo intact.
    resp = client.post("/api/update_volume_bulk", json={"cells": [
        {"line_type": LineType.DEPENDENT_DEMAND.value, "material_number": mat,
         "aux_column": "", "period": period, "new_value": 5.0}]})
    assert resp.status_code == 400
    assert len(sess["redo_stack"]) == 1  # still redoable


def test_bulk_runs_capacity_recalc_once(golden_fixture_path, monkeypatch):
    """E1: bulk defers the whole-plan capacity+value recalc to ONE final pass."""
    import ui.routes.edits as edits_mod
    import ui.volume_change as vc_mod

    engine = _build_engine(golden_fixture_path)
    app, _ = _make_app(engine)
    client = app.test_client()

    calls = {"inner": 0, "final": 0}
    real = vc_mod.recalculate_capacity_and_values

    def counting_inner(eng, sess):
        calls["inner"] += 1
        real(eng, sess)

    def counting_final(eng, sess):
        calls["final"] += 1
        real(eng, sess)

    monkeypatch.setattr(vc_mod, "recalculate_capacity_and_values", counting_inner)
    monkeypatch.setattr(edits_mod, "recalculate_capacity_and_values", counting_final)

    period = engine.data.periods[5]
    mats = _first_demand_materials(engine, 3)
    resp = client.post("/api/update_volume_bulk", json={"cells": [
        {"line_type": LineType.DEMAND_FORECAST.value, "material_number": m,
         "aux_column": "", "period": period, "new_value": 111.0}
        for m in mats]})
    assert resp.status_code == 200

    assert calls["final"] == 1          # one batch-level recalc
    assert calls["inner"] == 0          # no per-cell whole-plan recalcs
