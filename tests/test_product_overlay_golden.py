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


# --------------------------------------------------- sourcing combination matrix
# All purchase/production/mix field combinations in ONE engine run, including
# the deliberately "wrong" legacy combos (produced + MOQ, routing-only,
# BOM-only) that the engine resolves silently — nothing may crash and every
# product must land in the branch the engine rules dictate.

M_PURCHASED = "900000101"   # sourcing=purchased + MOQ + lead time
M_PRODUCED = "900000102"    # sourcing=produced (BOM + routing)
M_LEGACY_MOQ = "900000103"  # legacy: produced-looking + MOQ (user scenario)
M_ROUTING_ONLY = "900000104"  # legacy: routing but no BOM -> purchase branch
M_BOM_ONLY = "900000105"    # legacy: BOM parent but no routing -> purchase branch
M_MIX = "900000106"         # sourcing=mix (pap_fraction) + everything
M_VOLUMES = "900000107"     # purchased, per-period volumes only + starting stock


@pytest.fixture(scope="module")
def matrix_engine(golden_fixture_path, integration_partners):
    x = integration_partners["component"]
    wc = integration_partners["machine"]
    bom = [{"component": x, "qty_per": 1.5}]
    routing = [{"work_center": wc, "base_quantity": 1000.0, "standard_time": 8.0}]
    return _run(golden_fixture_path, [
        {"material_number": M_PURCHASED, "name": "Matrix inkoop",
         "product_type": "raw", "sourcing": "purchased",
         "flat_volume": 100.0, "safety_stock": 10.0, "moq": 30.0, "lead_time": 2,
         "sales_price": 12.0, "raw_material_cost": 3.0},
        {"material_number": M_PRODUCED, "name": "Matrix productie",
         "product_type": "bulk", "sourcing": "produced",
         "flat_volume": 80.0, "bom_as_parent": bom, "routing": routing,
         "sales_price": 15.0},
        {"material_number": M_LEGACY_MOQ, "name": "Matrix legacy moq",
         "product_type": "bulk",  # geen sourcing: legacy pad
         "flat_volume": 60.0, "moq": 25.0, "bom_as_parent": bom, "routing": routing},
        {"material_number": M_ROUTING_ONLY, "name": "Matrix routing zonder BOM",
         "product_type": "bulk", "flat_volume": 40.0, "routing": routing},
        {"material_number": M_BOM_ONLY, "name": "Matrix BOM zonder routing",
         "product_type": "bulk", "flat_volume": 30.0, "bom_as_parent": bom},
        {"material_number": M_MIX, "name": "Matrix mix",
         "product_type": "bulk", "sourcing": "mix", "pap_fraction": 0.6,
         "flat_volume": 50.0, "moq": 10.0, "bom_as_parent": bom, "routing": routing,
         "sales_price": 20.0, "raw_material_cost": 5.0},
        {"material_number": M_VOLUMES, "name": "Matrix per-periode",
         "product_type": "other", "sourcing": "purchased",
         "volumes": {}, "flat_volume": None, "starting_stock": 500.0,
         "safety_stock": 5.0, "default_inventory_value": 2.5},
    ])


def _line_totals(engine, mat):
    return {
        lt: sum(r.values.values())
        for lt, rows in engine.results.items()
        for r in rows if r.material_number == mat
    }


def test_matrix_every_product_processed_no_crash(matrix_engine):
    for mat in (M_PURCHASED, M_PRODUCED, M_LEGACY_MOQ, M_ROUTING_ONLY,
                M_BOM_ONLY, M_MIX, M_VOLUMES):
        totals = _line_totals(matrix_engine, mat)
        assert LineType.TOTAL_DEMAND.value in totals, mat
        assert LineType.INVENTORY.value in totals, mat
        assert LineType.MIN_TARGET_STOCK.value in totals, mat


def test_matrix_purchased_gets_purchase_rows_with_moq_ceiling(matrix_engine):
    totals = _line_totals(matrix_engine, M_PURCHASED)
    assert LineType.PURCHASE_RECEIPT.value in totals
    assert LineType.PURCHASE_PLAN.value in totals
    assert LineType.PRODUCTION_PLAN.value not in totals
    receipts = _rows(matrix_engine, LineType.PURCHASE_RECEIPT, M_PURCHASED)[0]
    nonzero = [v for v in receipts.values.values() if v > 1e-9]
    assert nonzero, "purchased product ordered nothing"
    for v in nonzero:  # MOQ 30 -> every order a multiple of 30
        assert abs(v / 30.0 - round(v / 30.0)) < 1e-6, v


def test_matrix_produced_gets_production_no_purchase(matrix_engine):
    totals = _line_totals(matrix_engine, M_PRODUCED)
    assert totals.get(LineType.PRODUCTION_PLAN.value, 0) > 0
    assert LineType.PURCHASE_RECEIPT.value not in totals
    assert LineType.PURCHASE_PLAN.value not in totals


def test_matrix_legacy_produced_with_moq_is_harmless(matrix_engine):
    """The user scenario: produced-looking product with an MOQ filled in.
    Engine rules: BOM parent + routing -> production branch; the MOQ is
    registered but never consulted. Nothing crashes, no purchase rows appear."""
    assert matrix_engine.data.purchase_moq.get(M_LEGACY_MOQ) == 25.0
    totals = _line_totals(matrix_engine, M_LEGACY_MOQ)
    assert totals.get(LineType.PRODUCTION_PLAN.value, 0) > 0
    assert LineType.PURCHASE_RECEIPT.value not in totals
    assert LineType.PURCHASE_PLAN.value not in totals


def test_matrix_routing_without_bom_falls_back_to_purchase(matrix_engine):
    totals = _line_totals(matrix_engine, M_ROUTING_ONLY)
    assert LineType.PRODUCTION_PLAN.value not in totals
    assert LineType.PURCHASE_RECEIPT.value in totals


def test_matrix_bom_without_routing_falls_back_to_purchase(matrix_engine, integration_partners):
    totals = _line_totals(matrix_engine, M_BOM_ONLY)
    assert LineType.PRODUCTION_PLAN.value not in totals
    assert LineType.PURCHASE_RECEIPT.value in totals
    # No production -> the component receives NO dependent demand from it.
    x = integration_partners["component"]
    dd = [r for r in _rows(matrix_engine, LineType.DEPENDENT_DEMAND, x)
          if r.aux_column == M_BOM_ONLY]
    assert not dd, "purchase-branch product must not create dependent demand"


def test_matrix_mix_gets_both_branches(matrix_engine):
    totals = _line_totals(matrix_engine, M_MIX)
    assert LineType.PRODUCTION_PLAN.value in totals
    assert LineType.PURCHASE_RECEIPT.value in totals


def test_matrix_starting_stock_covers_demandless_product(matrix_engine):
    inv = _rows(matrix_engine, LineType.INVENTORY, M_VOLUMES)
    assert inv and inv[0].starting_stock == 500.0
    # No volumes anywhere: L01 row absent, demand zero, inventory stays flat.
    assert not _rows(matrix_engine, LineType.DEMAND_FORECAST, M_VOLUMES)
    assert all(abs(v - 500.0) < 1e-6 for v in inv[0].values.values())


# ------------------------------------------------- financial data end-to-end
# Financial fields of added products must land EXACTLY in the value overlay:
# revenue = sales_price × L01 volume, raw-material cost = cost × total demand
# (× (1 − productiefractie) for mix), purchase-receipt value = cost × receipt,
# inventory value = default_inventory_value × quantity, and the consolidated
# turnover rises by precisely the products' combined revenue.

def _value_rows(engine, line_type, mat):
    return [r for r in engine.value_results.get(line_type.value, [])
            if r.material_number == mat]


@pytest.mark.parametrize("mat, price, volume", [
    (M_PURCHASED, 12.0, 100.0),
    (M_PRODUCED, 15.0, 80.0),
    (M_MIX, 20.0, 50.0),
])
def test_matrix_revenue_is_price_times_volume(matrix_engine, mat, price, volume):
    rows = _value_rows(matrix_engine, LineType.DEMAND_FORECAST, mat)
    assert len(rows) == 1, f"{mat}: expected one value L01 row"
    assert float(rows[0].aux_column) == pytest.approx(price)  # unit price shown
    for period, v in rows[0].values.items():
        assert v == pytest.approx(price * volume), (mat, period)


def test_matrix_product_without_price_yields_zero_revenue(matrix_engine):
    rows = _value_rows(matrix_engine, LineType.DEMAND_FORECAST, M_ROUTING_ONLY)
    assert rows and all(v == 0 for v in rows[0].values.values())


def test_matrix_raw_material_cost_purchased_and_mix(matrix_engine):
    # Purchased: total demand 100 × cost 3 (no PAP factor).
    rows = _value_rows(matrix_engine, LineType.TOTAL_DEMAND, M_PURCHASED)
    assert len(rows) == 1
    for v in rows[0].values.values():
        assert v == pytest.approx(3.0 * 100.0)
    # Mix: × (1 − productiefractie 0.6) — only the purchased share carries cost.
    rows = _value_rows(matrix_engine, LineType.TOTAL_DEMAND, M_MIX)
    assert len(rows) == 1
    for v in rows[0].values.values():
        assert v == pytest.approx(5.0 * 50.0 * 0.4)
    # Produced: no purchase plan -> no raw-material cost row at all.
    assert not _value_rows(matrix_engine, LineType.TOTAL_DEMAND, M_PRODUCED)


def test_matrix_purchase_receipt_value_tracks_planned_receipts(matrix_engine):
    plan_row = _rows(matrix_engine, LineType.PURCHASE_RECEIPT, M_PURCHASED)[0]
    value_row = _value_rows(matrix_engine, LineType.PURCHASE_RECEIPT, M_PURCHASED)[0]
    assert sum(plan_row.values.values()) > 0
    for period, qty in plan_row.values.items():
        assert value_row.values[period] == pytest.approx(qty * 3.0), period


def test_matrix_inventory_value_uses_default_inventory_value(matrix_engine):
    value_row = _value_rows(matrix_engine, LineType.INVENTORY, M_VOLUMES)[0]
    assert value_row.starting_stock == pytest.approx(500.0 * 2.5)
    for period, v in value_row.values.items():
        assert v == pytest.approx(500.0 * 2.5), period  # voorraad blijft vlak


def test_matrix_consolidated_turnover_rises_by_product_revenue(
        planning_engine_result, matrix_engine):
    def _turnover(engine):
        rows = [r for r in engine.value_results.get(LineType.CONSOLIDATION.value, [])
                if r.material_number == "ZZZZZZ_TURNOVER"]
        assert len(rows) == 1
        return rows[0].values

    base, overlay = _turnover(planning_engine_result), _turnover(matrix_engine)
    # Existing materials' L01 is untouched by the overlay, so the delta is
    # exactly the added products' revenue: 100×12 + 80×15 + 50×20 per period.
    expected_delta = 100.0 * 12.0 + 80.0 * 15.0 + 50.0 * 20.0
    for period, base_val in base.items():
        assert overlay[period] - base_val == pytest.approx(expected_delta), period


# -------------------------------------------------------------- export smoke

def test_full_excel_export_with_added_product(integrated_engine, tmp_path):
    """to_excel_with_values (all sheets, charts, formatting) must not choke on
    an overlay product, and its rows must land in the exported workbook."""
    import openpyxl

    out = tmp_path / "overlay_export.xlsx"
    with contextlib.redirect_stdout(io.StringIO()):
        integrated_engine.to_excel_with_values(str(out))
    assert out.exists() and out.stat().st_size > 0

    workbook = openpyxl.load_workbook(str(out), read_only=True)
    try:
        found = False
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(min_col=1, max_col=1, values_only=True):
                if str(row[0]) == MN:
                    found = True
                    break
            if found:
                break
        assert found, "added product missing from the exported workbook"
    finally:
        workbook.close()


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
