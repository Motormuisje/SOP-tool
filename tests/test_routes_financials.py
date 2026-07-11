"""Fase 2.4 — financial-metrics deviation + drilldown routes."""

from flask import Flask

from modules.models import LineType
from modules.planning_engine import PlanningEngine
from ui.routes.financials import create_financials_blueprint
from ui.state_snapshot import snapshot_engine_state


def _app_with_engine(golden_fixture_path, with_baseline=True):
    engine = PlanningEngine(
        str(golden_fixture_path), planning_month="2025-12",
        months_actuals=11, months_forecast=12,
    )
    engine.run()
    sess = {"id": "fin", "engine": engine}
    if with_baseline:
        sess["reset_baseline"] = snapshot_engine_state(
            engine, lambda m, d: float(getattr(m, "shift_hours_override", None) or 0.0))

    def get_active():
        return sess, engine

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_financials_blueprint(get_active))
    return app, engine, sess


def test_financial_metrics_returns_consolidation_with_baseline(golden_fixture_path):
    app, engine, _ = _app_with_engine(golden_fixture_path)
    resp = app.test_client().get("/api/financial_metrics")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["baseline_available"] is True
    names = {m["name"] for m in body["metrics"]}
    assert "TURNOVER" in names
    turnover = next(m for m in body["metrics"] if m["name"] == "TURNOVER")
    # Fresh baseline == current, so all deltas are zero.
    assert all(abs(v) < 1e-6 for v in turnover["delta"].values())
    assert turnover["source_line_type"] == "01. Demand forecast"
    assert turnover["trend"] in ("up", "down", "flat")


def test_financial_metrics_deviation_after_edit(golden_fixture_path):
    from ui.volume_change import apply_volume_change
    app, engine, sess = _app_with_engine(golden_fixture_path)
    sess.setdefault("pending_edits", {})
    sess.setdefault("value_aux_overrides", {})

    # Raise demand for one material -> turnover should deviate from baseline.
    mat = engine.results[LineType.DEMAND_FORECAST.value][0].material_number
    period = engine.data.periods[1]
    with app.test_request_context():
        apply_volume_change(sess, engine, LineType.DEMAND_FORECAST.value, mat, period,
                            99999.0, aux_column="", push_undo=False)

    body = app.test_client().get("/api/financial_metrics").get_json()
    turnover = next(m for m in body["metrics"] if m["name"] == "TURNOVER")
    assert abs(turnover["delta"][period]) > 0.0


def test_drill_exact_for_sourced_metric(golden_fixture_path):
    app, _, _ = _app_with_engine(golden_fixture_path)
    resp = app.test_client().get("/api/financial_metrics/drill?metric=TURNOVER")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["derived"] is False
    assert body["source_line_type"] == "01. Demand forecast"
    assert len(body["contributors"]) > 0
    assert body["contributors"] == sorted(body["contributors"], key=lambda c: abs(c["total"]), reverse=True)


def test_drill_derived_metric_flagged(golden_fixture_path):
    app, _, _ = _app_with_engine(golden_fixture_path)
    body = app.test_client().get("/api/financial_metrics/drill?metric=GROSS MARGIN").get_json()
    assert body["derived"] is True


def test_financial_metrics_no_engine_returns_400(golden_fixture_path):
    app = Flask(__name__)
    app.register_blueprint(create_financials_blueprint(lambda: (None, None)))
    assert app.test_client().get("/api/financial_metrics").status_code == 400
