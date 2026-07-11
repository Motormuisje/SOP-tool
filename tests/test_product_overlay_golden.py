"""Fase 3 — product overlay end-to-end on the golden fixture (TP3-01/02/03).

Two module-scoped engine runs:
- ``isolated_engine``: one added product WITHOUT BOM edges or routing —
  exercises the standalone pass and the strict parity claim (TP3-02: existing
  rows byte-identical, the export differs only in the new product's rows).
- ``integrated_engine``: one added product as BOM parent of an existing leaf
  component AND as child of an existing producer, routed over an existing
  machine, with a sales price — exercises dependent demand in both directions
  (TP3-03), capacity uptake and the value overlay (TP3-01).

TP3-05 (removal) is the complement of parity: building without the overlay IS
the baseline path, which tests/test_golden_pipeline.py already pins.
"""

import contextlib
import io

import pandas as pd
import pytest

from modules.models import LineType
from modules.planning_engine import PlanningEngine

MN = "900000001"
PARAMS = dict(planning_month="2025-12", months_actuals=11, months_forecast=12)


def _run(golden_fixture_path, added_products):
    with contextlib.redirect_stdout(io.StringIO()):
        engine = PlanningEngine(
            str(golden_fixture_path),
            config_overrides={"added_products": added_products},
            **PARAMS,
        )
        engine.run()
    return engine


@pytest.fixture(scope="module")
def isolated_engine(golden_fixture_path):
    return _run(golden_fixture_path, [{
        "material_number": MN,
        "name": "Testproduct isolated",
        "product_type": "other",
        "flat_volume": 100.0,
        "starting_stock": 50.0,
        "safety_stock": 20.0,
    }])


@pytest.fixture(scope="module")
def integration_partners(planning_engine_result):
    """Pick a deterministic existing producer P, leaf component X, machine."""
    data = planning_engine_result.data
    parents = {b.parent_material for b in data.bom}
    components = {b.component_material for b in data.bom}
    # X: a leaf component (never a parent) that exists in the material master
    # — a new edge MN → X can never close a cycle back to P.
    leaves = sorted(c for c in components - parents if c in data.materials)
    assert leaves, "golden fixture has no leaf components"
    x = leaves[0]
    # P: an existing producer with a non-zero production plan.
    producers = sorted(
        m for m, plan in planning_engine_result.all_production_plans.items()
        if sum(plan.values()) > 0 and m in data.materials
    )
    assert producers, "golden fixture has no producing materials"
    p = producers[0]
    wc = sorted(data.machines)[0]
    return {"parent": p, "component": x, "machine": wc}


@pytest.fixture(scope="module")
def integrated_engine(golden_fixture_path, integration_partners):
    return _run(golden_fixture_path, [{
        "material_number": MN,
        "name": "Testproduct integrated",
        "product_type": "bulk",
        "flat_volume": 120.0,
        "safety_stock": 0.0,
        "bom_as_parent": [{"component": integration_partners["component"],
                           "qty_per": 2.0}],
        "bom_as_child": [{"parent": integration_partners["parent"],
                          "qty_per": 0.5}],
        "routing": [{"work_center": integration_partners["machine"],
                     "base_quantity": 1000.0, "standard_time": 8.0}],
        "sales_price": 12.5,
    }])


def _rows(engine, line_type, mat=None):
    rows = engine.results.get(line_type.value, [])
    if mat is not None:
        rows = [r for r in rows if r.material_number == mat]
    return rows


# ------------------------------------------------------------------- TP3-02

def test_parity_existing_rows_unchanged(planning_engine_result, isolated_engine):
    base_df = planning_engine_result.to_dataframe().reset_index(drop=True)
    iso_df = isolated_engine.to_dataframe()
    mask = iso_df["Material number"].astype(str) == MN
    assert mask.any(), "added product missing from export dataframe"
    rest = iso_df[~mask].reset_index(drop=True)
    pd.testing.assert_frame_equal(rest, base_df)


# ------------------------------------------------------------------- TP3-01

def test_isolated_product_flows_through_standalone_pass(isolated_engine):
    # No BOM edges → the standalone safety-stock pass must pick it up.
    fc = _rows(isolated_engine, LineType.DEMAND_FORECAST, MN)
    assert len(fc) == 1
    assert all(v == 100.0 for v in fc[0].values.values())

    assert _rows(isolated_engine, LineType.TOTAL_DEMAND, MN)
    inv = _rows(isolated_engine, LineType.INVENTORY, MN)
    assert inv and inv[0].starting_stock == 50.0
    target = _rows(isolated_engine, LineType.MIN_TARGET_STOCK, MN)
    assert target and all(v >= 20.0 for v in target[0].values.values())
    # Pure-purchase branch (no BOM parent/routing): purchase receipt + plan.
    assert _rows(isolated_engine, LineType.PURCHASE_RECEIPT, MN)
    assert _rows(isolated_engine, LineType.PURCHASE_PLAN, MN)


def test_integrated_product_produces_and_takes_capacity(
        planning_engine_result, integrated_engine, integration_partners):
    # BOM parent + routing → production branch.
    prod = _rows(integrated_engine, LineType.PRODUCTION_PLAN, MN)
    assert prod and sum(prod[0].values.values()) > 0

    # Capacity uptake on the existing machine (L07 machine row hours rise).
    wc = integration_partners["machine"]

    def _machine_hours(engine):
        return sum(
            sum(r.values.values())
            for r in engine.results.get(LineType.CAPACITY_UTILIZATION.value, [])
            if r.material_name == wc
        )

    assert _machine_hours(integrated_engine) > _machine_hours(planning_engine_result)


def test_integrated_product_has_revenue_in_value_overlay(integrated_engine):
    val_rows = [
        r for r in integrated_engine.value_results.get(
            LineType.DEMAND_FORECAST.value, [])
        if r.material_number == MN
    ]
    assert val_rows, "added product missing from value overlay"
    assert sum(val_rows[0].values.values()) > 0, "sales price yielded no revenue"


# ------------------------------------------------------------------- TP3-03

def test_dependent_demand_parent_direction(integrated_engine, integration_partners):
    # MN is parent of X: X must gain an L02 row attributed to MN with
    # production_plan(MN) × qty_per volumes.
    x = integration_partners["component"]
    dd = [r for r in _rows(integrated_engine, LineType.DEPENDENT_DEMAND, x)
          if r.aux_column == MN]
    assert dd, "component did not receive dependent demand from added parent"
    prod = _rows(integrated_engine, LineType.PRODUCTION_PLAN, MN)[0]
    for period, qty in prod.values.items():
        assert dd[0].values.get(period) == pytest.approx(qty * 2.0)


def test_dependent_demand_child_direction(integrated_engine, integration_partners):
    # P is parent of MN: MN must have an L02 row attributed to P.
    p = integration_partners["parent"]
    dd = [r for r in _rows(integrated_engine, LineType.DEPENDENT_DEMAND, MN)
          if r.aux_column == p]
    assert dd, "added product did not receive dependent demand from existing parent"
    # And P's L08 dependent requirements now list MN as component.
    reqs = [r for r in _rows(integrated_engine, LineType.DEPENDENT_REQUIREMENTS, p)
            if r.aux_column == MN]
    assert reqs, "existing parent's L08 does not list the added component"


# ------------------------------------------------------------------- TP3-04

def test_restart_rebuild_and_replay_restore_product_and_edit(
        golden_fixture_path, tmp_path):
    """Restart simulation: session persisted to disk, engine rebuilt from the
    loaded dict, pending edit on the ADDED product replayed. Live state and
    post-restart replay must agree (replay is the source of truth)."""
    from flask import Flask

    from ui.engine_rebuild import build_clean_engine_for_session
    from ui.replay import replay_pending_edits
    from ui.session_store import load_sessions_from_disk, save_sessions_to_disk
    from ui.volume_change import apply_volume_change

    product = {"material_number": MN, "name": "Restartproduct",
               "product_type": "other", "flat_volume": 100.0, "safety_stock": 0.0}
    sess = {
        "id": "s-restart", "file_path": str(golden_fixture_path),
        "extract_files": None,
        "parameters": {"planning_month": "2025-12", "months_actuals": 11,
                       "months_forecast": 12},
        "added_products": [product],
        "pending_edits": {}, "value_aux_overrides": {}, "machine_overrides": {},
        "inventory_overrides": {}, "capacity_overrides": {},
        "undo_stack": [], "redo_stack": [], "engine": None,
    }

    app = Flask(__name__)
    with contextlib.redirect_stdout(io.StringIO()):
        engine1 = build_clean_engine_for_session(sess, {})
    assert engine1 is not None
    l01 = _rows(engine1, LineType.DEMAND_FORECAST, MN)
    assert l01, "added product missing after session rebuild"
    period = engine1.data.periods[2]
    aux = str(l01[0].aux_column or "")

    with app.app_context(), contextlib.redirect_stdout(io.StringIO()):
        resp = apply_volume_change(
            sess, engine1, LineType.DEMAND_FORECAST.value, MN, period, 999.0,
            aux_column=aux)
    assert (resp.get_json() or {}).get("success") is True, resp.get_json()
    assert sess["pending_edits"], "edit was not recorded as pending"
    live_l01 = _rows(engine1, LineType.DEMAND_FORECAST, MN)[0].values[period]
    assert live_l01 == pytest.approx(999.0)

    # --- restart: persist, reload, rebuild, replay ---
    sess["engine"] = engine1
    store = tmp_path / "sessions_store.json"
    save_sessions_to_disk({"s-restart": sess}, "s-restart", store, lambda s, e: {})
    loaded, _ = load_sessions_from_disk(store)
    sess2 = loaded["s-restart"]
    assert sess2["added_products"] == [product]

    with contextlib.redirect_stdout(io.StringIO()):
        engine2 = build_clean_engine_for_session(sess2, {})
        with app.app_context():
            replay_pending_edits(
                sess2, engine2, apply_volume_change,
                lambda e, o: False, lambda e, s: None)

    replay_l01 = _rows(engine2, LineType.DEMAND_FORECAST, MN)
    assert replay_l01, "added product missing after restart rebuild"
    assert replay_l01[0].values[period] == pytest.approx(live_l01)
