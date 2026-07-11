from types import SimpleNamespace

import pytest
from flask import Flask

from modules.models import LineType, PlanningRow
from ui.parsers import (
    format_purchased_and_produced,
    parse_purchased_and_produced,
    valuation_params_from_config,
)
from ui.routes.scenarios import create_scenarios_blueprint
from ui.state_snapshot import (
    build_pending_edits_from_results_snapshot,
    planning_row_from_snapshot,
    rebuild_volume_caches_from_results,
    row_key_from_obj,
)


pytestmark = pytest.mark.no_fixture


def _row(
    material_number="MAT-1",
    line_type=LineType.TOTAL_DEMAND.value,
    values=None,
    manual_edits=None,
):
    return PlanningRow(
        material_number=material_number,
        material_name=f"Name {material_number}",
        product_type="Bulk Product",
        product_family="Family",
        spc_product="SPC",
        product_cluster="Cluster",
        product_name="Product",
        line_type=line_type,
        values=values or {"2025-12": 10.0, "2026-01": 12.0},
        manual_edits=manual_edits or {},
    )


def _snapshot(row):
    return row.to_dict()


def _scenario(session_id, name, results=None, value_results=None, **overrides):
    scenario = {
        "id": name.lower(),
        "name": name,
        "session_id": session_id,
        "timestamp": f"2026-04-21T12:0{len(name)}:00",
        "edit_count": 0,
        "results": results or {},
        "value_results": value_results or {},
        "pending_edits": {},
        "value_aux_overrides": {},
        "valuation_params": {"1": 1.0},
        "purchased_and_produced": "MAT-1:0.25",
    }
    scenario.update(overrides)
    return scenario


@pytest.fixture
def scenarios_route_app(tmp_path):
    active = {"session_id": "session-a"}
    scenarios = {}
    sessions = {
        "session-a": {
            "id": "session-a",
            "pending_edits": {},
            "value_aux_overrides": {},
            "undo_stack": ["old"],
            "redo_stack": ["old"],
        },
        "session-b": {
            "id": "session-b",
            "pending_edits": {},
            "value_aux_overrides": {},
            "undo_stack": [],
            "redo_stack": [],
        },
    }
    engine = SimpleNamespace(
        results={
            LineType.TOTAL_DEMAND.value: [
                _row(
                    manual_edits={
                        "2025-12": {"original": 9.0, "new": 10.0},
                    }
                )
            ],
            LineType.INVENTORY.value: [_row(line_type=LineType.INVENTORY.value)],
        },
        value_results={
            LineType.CONSOLIDATION.value: [
                _row("ZZZZZZ_REVENUE", LineType.CONSOLIDATION.value, {"2025-12": 100.0})
            ]
        },
        data=SimpleNamespace(
            valuation_params=valuation_params_from_config({"1": 1.0}),
            purchased_and_produced={"MAT-1": 0.25},
        ),
    )

    def get_active():
        return sessions.get(active["session_id"]), engine

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(create_scenarios_blueprint(
        scenarios,
        sessions,
        lambda: active["session_id"],
        get_active,
        {"valuation_params": {"1": 1.0}, "purchased_and_produced": "MAT-1:0.25"},
        lambda: tmp_path / "exports",
        build_pending_edits_from_results_snapshot,
        planning_row_from_snapshot,
        rebuild_volume_caches_from_results,
        valuation_params_from_config,
        parse_purchased_and_produced,
        format_purchased_and_produced,
        row_key_from_obj,
    ))

    return SimpleNamespace(
        app=flask_app,
        client=flask_app.test_client(),
        active=active,
        scenarios=scenarios,
        sessions=sessions,
        engine=engine,
        export_dir=tmp_path / "exports",
    )


def test_list_scenarios_returns_only_active_session_sorted(scenarios_route_app):
    scenarios_route_app.scenarios["later"] = _scenario(
        "session-a",
        "Later",
        timestamp="2026-04-21T12:02:00",
    )
    scenarios_route_app.scenarios["earlier"] = _scenario(
        "session-a",
        "Earlier",
        timestamp="2026-04-21T12:01:00",
    )
    scenarios_route_app.scenarios["other"] = _scenario("session-b", "Other")

    response = scenarios_route_app.client.get("/api/scenarios")

    assert response.status_code == 200
    payload = response.get_json()
    assert [item["id"] for item in payload["scenarios"]] == ["earlier", "later"]
    assert [item["name"] for item in payload["scenarios"]] == ["Earlier", "Later"]


def test_save_scenario_snapshots_current_engine(scenarios_route_app):
    response = scenarios_route_app.client.post("/api/scenarios/save", json={"name": "Baseline"})

    assert response.status_code == 200, response.get_json(silent=True) or response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["name"] == "Baseline"
    assert payload["edit_count"] == 1

    saved = scenarios_route_app.scenarios[payload["scenario_id"]]
    assert saved["session_id"] == "session-a"
    assert LineType.TOTAL_DEMAND.value in saved["results"]
    assert LineType.CONSOLIDATION.value in saved["value_results"]
    assert saved["pending_edits"]
    assert saved["valuation_params"] == {"1": 1.0}
    assert saved["purchased_and_produced"] == "MAT-1:0.25"


def test_save_scenario_persists_to_scenario_store(scenarios_route_app):
    scenarios_route_app.sessions["session-a"]["pending_edits"] = {
        "03. Total demand||MAT-1||||2025-12": {"original": 9.0, "new_value": 10.0},
    }

    response = scenarios_route_app.client.post("/api/scenarios/save", json={"name": "Stored"})

    assert response.status_code == 200, response.get_json(silent=True)
    scenario_id = response.get_json()["scenario_id"]
    assert scenario_id in scenarios_route_app.scenarios
    stored = scenarios_route_app.scenarios[scenario_id]
    assert stored["name"] == "Stored"
    assert stored["pending_edits"] == {
        "03. Total demand||MAT-1||||2025-12": {"original": 9.0, "new_value": 10.0},
    }


def test_save_scenario_requires_name(scenarios_route_app):
    response = scenarios_route_app.client.post("/api/scenarios/save", json={"name": " "})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Scenario name is required"


def test_load_scenario_restores_snapshots_and_session_state(scenarios_route_app):
    restored_row = _row("MAT-9", LineType.TOTAL_DEMAND.value, {"2025-12": 42.0})
    restored_value = _row("ZZZZZZ_REVENUE", LineType.CONSOLIDATION.value, {"2025-12": 123.0})
    scenarios_route_app.scenarios["scenario-a"] = _scenario(
        "session-a",
        "Loaded",
        results={LineType.TOTAL_DEMAND.value: [_snapshot(restored_row)]},
        value_results={LineType.CONSOLIDATION.value: [_snapshot(restored_value)]},
        pending_edits={"03. Total demand||MAT-9||||2025-12": {"original": 1.0, "new_value": 42.0}},
        value_aux_overrides={"value-key": {"new_value": 12.0}},
        valuation_params={"1": 2.5},
        purchased_and_produced="MAT-9:0.5",
    )

    response = scenarios_route_app.client.post(
        "/api/scenarios/load",
        json={"scenario_id": "scenario-a"},
    )

    assert response.status_code == 200, response.get_json(silent=True) or response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["name"] == "Loaded"
    assert payload["pending_edits"] == {
        "03. Total demand||MAT-9||||2025-12": {"original": 1.0, "new_value": 42.0}
    }
    assert payload["value_aux_overrides"] == {"value-key": {"new_value": 12.0}}
    assert payload["restored_valuation_params"] == {"1": 2.5}

    sess = scenarios_route_app.sessions["session-a"]
    assert sess["undo_stack"] == []
    assert sess["redo_stack"] == []
    assert scenarios_route_app.engine.results[LineType.TOTAL_DEMAND.value][0].material_number == "MAT-9"
    assert scenarios_route_app.engine.all_production_plans == {}
    assert scenarios_route_app.engine.all_purchase_receipts == {}


def test_load_scenario_restores_session_state_with_derived_pending_edits(scenarios_route_app):
    restored_row = _row(
        "MAT-7",
        LineType.TOTAL_DEMAND.value,
        {"2025-12": 33.0},
        manual_edits={"2025-12": {"original": 30.0, "new": 33.0}},
    )
    scenarios_route_app.scenarios["scenario-derived"] = _scenario(
        "session-a",
        "Derived",
        results={LineType.TOTAL_DEMAND.value: [_snapshot(restored_row)]},
        pending_edits={},
        value_aux_overrides={"aux-key": {"original": 1.0, "new_value": 2.0}},
    )

    response = scenarios_route_app.client.post(
        "/api/scenarios/load",
        json={"scenario_id": "scenario-derived"},
    )

    assert response.status_code == 200, response.get_json(silent=True)
    assert scenarios_route_app.sessions["session-a"]["pending_edits"] == {
        "03. Total demand||MAT-7||||2025-12": {"original": 30.0, "new_value": 33.0},
    }
    assert scenarios_route_app.sessions["session-a"]["value_aux_overrides"] == {
        "aux-key": {"original": 1.0, "new_value": 2.0},
    }


def test_load_scenario_returns_404_for_missing_id(scenarios_route_app):
    response = scenarios_route_app.client.post(
        "/api/scenarios/load",
        json={"scenario_id": "missing"},
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "Scenario not found"


def test_delete_scenario_removes_active_session_scenario(scenarios_route_app):
    scenarios_route_app.scenarios["scenario-a"] = _scenario("session-a", "Delete Me")

    response = scenarios_route_app.client.delete("/api/scenarios/scenario-a")

    assert response.status_code == 200
    assert response.get_json() == {"success": True}
    assert "scenario-a" not in scenarios_route_app.scenarios


def test_delete_scenario_returns_404_for_missing_id(scenarios_route_app):
    response = scenarios_route_app.client.delete("/api/scenarios/missing")

    assert response.status_code == 404
    assert response.get_json()["error"] == "Scenario not found"


def test_compare_scenarios_returns_summary_and_diff_rows(scenarios_route_app):
    row_a = _row("MAT-1", LineType.TOTAL_DEMAND.value, {"2025-12": 10.0, "2026-01": 20.0})
    row_b = _row("MAT-1", LineType.TOTAL_DEMAND.value, {"2025-12": 8.0, "2026-01": 25.0})
    inv_a = _row("MAT-1", LineType.INVENTORY.value, {"2025-12": 4.0})
    inv_b = _row("MAT-1", LineType.INVENTORY.value, {"2025-12": 1.0})
    scenarios_route_app.scenarios["a"] = _scenario(
        "session-a",
        "Scenario A",
        results={
            LineType.TOTAL_DEMAND.value: [_snapshot(row_a)],
            LineType.INVENTORY.value: [_snapshot(inv_a)],
        },
    )
    scenarios_route_app.scenarios["b"] = _scenario(
        "session-a",
        "Scenario B",
        results={
            LineType.TOTAL_DEMAND.value: [_snapshot(row_b)],
            LineType.INVENTORY.value: [_snapshot(inv_b)],
        },
    )

    response = scenarios_route_app.client.post(
        "/api/scenarios/compare",
        json={"scenario_a_id": "a", "scenario_b_id": "b"},
    )

    assert response.status_code == 200, response.get_json(silent=True) or response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["summary"]["scenario_a_name"] == "Scenario A"
    assert payload["summary"]["scenario_b_name"] == "Scenario B"
    assert payload["summary"]["total_demand_diff"] == {"2025-12": 2.0, "2026-01": -5.0}
    assert payload["summary"]["inventory_diff"] == {"2025-12": 3.0}
    assert payload["summary"]["changed_rows"] == 2
    assert len(payload["rows"]) == 2


def test_compare_scenarios_export_returns_xlsx(scenarios_route_app):
    row_a = _row("MAT-1", LineType.TOTAL_DEMAND.value, {"2025-12": 10.0})
    row_b = _row("MAT-1", LineType.TOTAL_DEMAND.value, {"2025-12": 8.0})
    val_a = _row("REV", LineType.CONSOLIDATION.value, {"2025-12": 100.0})
    val_b = _row("REV", LineType.CONSOLIDATION.value, {"2025-12": 75.0})
    scenarios_route_app.scenarios["a"] = _scenario(
        "session-a",
        "Scenario A",
        results={LineType.TOTAL_DEMAND.value: [_snapshot(row_a)]},
        value_results={LineType.CONSOLIDATION.value: [_snapshot(val_a)]},
    )
    scenarios_route_app.scenarios["b"] = _scenario(
        "session-a",
        "Scenario B",
        results={LineType.TOTAL_DEMAND.value: [_snapshot(row_b)]},
        value_results={LineType.CONSOLIDATION.value: [_snapshot(val_b)]},
    )

    response = scenarios_route_app.client.get("/api/scenarios/compare/export?a=a&b=b")

    assert response.status_code == 200, response.get_json(silent=True)
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert 'filename="Comparison_Scenario A_vs_Scenario B.xlsx"' in response.headers["Content-Disposition"]


def test_compare_scenarios_returns_404_for_missing_id(scenarios_route_app):
    response = scenarios_route_app.client.post(
        "/api/scenarios/compare",
        json={"scenario_a_id": "missing", "scenario_b_id": "also-missing"},
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "Scenario not found"


def test_scenario_compare_export_writes_file_to_export_dir(scenarios_route_app):
    row_a = _row("MAT-1", LineType.TOTAL_DEMAND.value, {"2025-12": 10.0})
    row_b = _row("MAT-1", LineType.TOTAL_DEMAND.value, {"2025-12": 8.0})
    scenarios_route_app.scenarios["a"] = _scenario(
        "session-a",
        "Scenario A",
        results={LineType.TOTAL_DEMAND.value: [_snapshot(row_a)]},
    )
    scenarios_route_app.scenarios["b"] = _scenario(
        "session-a",
        "Scenario B",
        results={LineType.TOTAL_DEMAND.value: [_snapshot(row_b)]},
    )

    response = scenarios_route_app.client.get("/api/scenarios/compare/export?a=a&b=b")

    assert response.status_code == 200, response.get_json(silent=True)
    export_path = scenarios_route_app.export_dir / "Comparison_Scenario A_vs_Scenario B.xlsx"
    assert export_path.exists()


def test_load_scenario_rejects_other_session(scenarios_route_app):
    scenarios_route_app.scenarios["scenario-b"] = _scenario("session-b", "Other Session")

    response = scenarios_route_app.client.post(
        "/api/scenarios/load",
        json={"scenario_id": "scenario-b"},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "Scenario belongs to a different session"
    assert scenarios_route_app.sessions["session-a"]["pending_edits"] == {}


def test_delete_scenario_rejects_other_session(scenarios_route_app):
    scenarios_route_app.scenarios["scenario-b"] = _scenario("session-b", "Keep Me")

    response = scenarios_route_app.client.delete("/api/scenarios/scenario-b")

    assert response.status_code == 403
    assert response.get_json()["error"] == "Scenario belongs to a different session"
    assert "scenario-b" in scenarios_route_app.scenarios


def test_compare_scenarios_rejects_cross_session_selection(scenarios_route_app):
    scenarios_route_app.scenarios["a"] = _scenario(
        "session-a",
        "Scenario A",
        results={LineType.TOTAL_DEMAND.value: [_snapshot(_row("MAT-1"))]},
    )
    scenarios_route_app.scenarios["b"] = _scenario(
        "session-b",
        "Scenario B",
        results={LineType.TOTAL_DEMAND.value: [_snapshot(_row("MAT-1"))]},
    )

    response = scenarios_route_app.client.post(
        "/api/scenarios/compare",
        json={"scenario_a_id": "a", "scenario_b_id": "b"},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "Scenarios belong to a different session"


def test_scenario_compare_export_without_selection_returns_404(scenarios_route_app):
    response = scenarios_route_app.client.get("/api/scenarios/compare/export")

    assert response.status_code == 404
    assert response.get_json()["error"] == "Scenario not found"


def test_scenario_compare_export_rejects_cross_session_selection(scenarios_route_app):
    scenarios_route_app.scenarios["a"] = _scenario(
        "session-a",
        "Scenario A",
        results={LineType.TOTAL_DEMAND.value: [_snapshot(_row("MAT-1"))]},
    )
    scenarios_route_app.scenarios["b"] = _scenario(
        "session-b",
        "Scenario B",
        results={LineType.TOTAL_DEMAND.value: [_snapshot(_row("MAT-1"))]},
    )

    response = scenarios_route_app.client.get("/api/scenarios/compare/export?a=a&b=b")

    assert response.status_code == 403
    assert response.get_json()["error"] == "Scenarios belong to a different session"


def test_scenario_compare_export_with_empty_diff_writes_no_diff_sheet(scenarios_route_app):
    row = _row("MAT-1", LineType.TOTAL_DEMAND.value, {"2025-12": 10.0})
    scenarios_route_app.scenarios["a"] = _scenario(
        "session-a",
        "Scenario A",
        results={LineType.TOTAL_DEMAND.value: [_snapshot(row)]},
    )
    scenarios_route_app.scenarios["b"] = _scenario(
        "session-a",
        "Scenario B",
        results={LineType.TOTAL_DEMAND.value: [_snapshot(row)]},
    )

    response = scenarios_route_app.client.get("/api/scenarios/compare/export?a=a&b=b")

    assert response.status_code == 200, response.get_json(silent=True)
    export_path = scenarios_route_app.export_dir / "Comparison_Scenario A_vs_Scenario B.xlsx"
    assert export_path.exists()

    import openpyxl

    workbook = openpyxl.load_workbook(export_path)
    assert workbook["Volume Comparison"]["A1"].value == "No differences found."
    assert workbook["Value Comparison"]["A1"].value == "No differences found."


def test_load_scenario_rederives_override_stores_from_pending_edits(scenarios_route_app):
    """H7: stale capacity/inventory overrides must not survive a scenario load."""
    sess = scenarios_route_app.sessions["session-a"]
    sess["capacity_overrides"] = {
        "07. Capacity utilization": {"STALE-MAT": {"2025-12": 999.0}},
    }
    sess["inventory_overrides"] = {"STALE-MAT": 111.0}

    scenarios_route_app.scenarios["sc1"] = _scenario(
        "session-a",
        "Sc1",
        results={LineType.TOTAL_DEMAND.value: [_snapshot(_row())]},
        pending_edits={
            "07. Capacity utilization||GROUP-X||||2026-01": {"original": 10.0, "new_value": 42.0},
            "04. Inventory||MAT-1||||starting_stock": {"original": 5.0, "new_value": 77.0},
            "01. Demand forecast||MAT-1||||2026-01": {"original": 1.0, "new_value": 2.0},
        },
    )

    response = scenarios_route_app.client.post("/api/scenarios/load", json={"scenario_id": "sc1"})

    assert response.status_code == 200
    assert sess["capacity_overrides"] == {
        "07. Capacity utilization": {"GROUP-X": {"2026-01": 42.0}}
    }
    assert sess["inventory_overrides"] == {"MAT-1": 77.0}


def test_scenarios_persist_round_trip(tmp_path):
    """M13: scenarios must survive a server restart via scenarios_store.json."""
    import json

    from ui.session_store import load_scenarios_from_disk, save_scenarios_to_disk

    store = tmp_path / "scenarios_store.json"
    scenarios = {"sc1": _scenario("session-a", "Sc1")}
    save_scenarios_to_disk(scenarios, store)

    assert store.exists()
    assert not store.with_name("scenarios_store.json.tmp").exists()
    loaded = load_scenarios_from_disk(store)
    assert loaded == json.loads(json.dumps(scenarios))

    store.write_text("{ corrupt", encoding="utf-8")
    assert load_scenarios_from_disk(store) == {}
    assert not store.exists()  # quarantined


# ----------------------------------------------- dynamische producten (Fase 3)

DYN_PRODUCT = {"material_number": "900000001", "name": "Dyn",
               "product_type": "bulk", "flat_volume": 1.0}


def test_save_records_added_products_deep(scenarios_route_app):
    sess = scenarios_route_app.sessions["session-a"]
    sess["added_products"] = [dict(DYN_PRODUCT)]
    response = scenarios_route_app.client.post(
        "/api/scenarios/save", json={"name": "Met product"})
    assert response.status_code == 200
    scenario_id = response.get_json()["scenario_id"]
    saved = scenarios_route_app.scenarios[scenario_id]["added_products"]
    assert saved == [DYN_PRODUCT]
    assert saved is not sess["added_products"]
    assert saved[0] is not sess["added_products"][0]


def test_load_warns_when_scenario_products_missing_from_session(scenarios_route_app):
    """Scenario opgeslagen mét product, product daarna verwijderd: laden moet
    dat expliciet melden (bewerkingen op het product worden geskipt) in
    plaats van stil een kloppend-lijkende toestand te tonen."""
    scenarios_route_app.scenarios["sc1"] = _scenario(
        "session-a", "SC1", added_products=[dict(DYN_PRODUCT)])
    scenarios_route_app.sessions["session-a"]["added_products"] = []

    response = scenarios_route_app.client.post(
        "/api/scenarios/load", json={"scenario_id": "sc1"})
    assert response.status_code == 200
    warnings = response.get_json().get("warnings")
    assert warnings, "verwachtte een waarschuwing over dynamische producten"
    assert "dynamische producten" in warnings[0]
    assert "900000001" in warnings[0]


def test_load_warns_about_products_added_after_save(scenarios_route_app):
    scenarios_route_app.scenarios["sc1"] = _scenario(
        "session-a", "SC1", added_products=[])
    scenarios_route_app.sessions["session-a"]["added_products"] = [dict(DYN_PRODUCT)]

    response = scenarios_route_app.client.post(
        "/api/scenarios/load", json={"scenario_id": "sc1"})
    assert response.status_code == 200
    warnings = response.get_json().get("warnings")
    assert warnings and "niet in het scenario" in warnings[0]


def test_load_is_silent_when_products_match_or_scenario_predates_field(scenarios_route_app):
    scenarios_route_app.scenarios["match"] = _scenario(
        "session-a", "Match", added_products=[dict(DYN_PRODUCT)])
    scenarios_route_app.scenarios["legacy"] = _scenario("session-a", "Legacy")
    scenarios_route_app.sessions["session-a"]["added_products"] = [dict(DYN_PRODUCT)]

    for scenario_id in ("match", "legacy"):
        response = scenarios_route_app.client.post(
            "/api/scenarios/load", json={"scenario_id": scenario_id})
        assert response.status_code == 200
        assert "warnings" not in response.get_json(), scenario_id
