"""Machine 'toon producten' endpoint — volumes only, per machine."""

from flask import Flask

from modules.models import LineType
from modules.planning_engine import PlanningEngine
from ui.routes.machines import create_machines_blueprint


def _app(golden_fixture_path):
    engine = PlanningEngine(
        str(golden_fixture_path), planning_month="2025-12",
        months_actuals=11, months_forecast=12,
    )
    engine.run()
    sess = {"id": "m", "engine": engine}

    def get_active():
        return sess, engine

    def crash(*a, **k):
        raise RuntimeError("unexpected callback")

    app = Flask(__name__)
    app.register_blueprint(create_machines_blueprint(
        get_active, lambda s, e: {}, lambda m, d: 0.0, crash, crash,
        lambda e: {"value_results": {}, "consolidation": []}, lambda: None))
    return app, engine


def test_machine_products_returns_volumes_only(golden_fixture_path):
    app, engine = _app(golden_fixture_path)
    # Find a machine that has at least one product with planned volume.
    machines = app.test_client().get("/api/machines").get_json()["machines"]
    target = next((m["code"] for m in machines if m["throughput_effective"] > 0), None)
    assert target, "no machine with output in fixture"

    resp = app.test_client().get(f"/api/machines/{target}/products")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["machine"] == target
    assert body["periods"] == engine.data.periods
    assert body["products"], "expected at least one product on a producing machine"
    # Sorted by total desc, and each product carries per-period volumes only.
    totals = [p["total"] for p in body["products"]]
    assert totals == sorted(totals, reverse=True)
    first = body["products"][0]
    assert set(first.keys()) == {"material_number", "material_name", "values", "total"}
    assert set(first["values"].keys()) == set(engine.data.periods)
    # Cross-check: a listed product actually routes over this machine.
    routings = engine.data.get_all_routings(first["material_number"])
    assert any(getattr(r, "work_center", None) == target for r in routings)


def test_machine_products_unknown_machine_404(golden_fixture_path):
    app, _ = _app(golden_fixture_path)
    assert app.test_client().get("/api/machines/NOPE/products").status_code == 404
