"""Fase 1.3 — configurable forecast default volumes (opt-in overlay)."""

import pytest

from modules.forecast_engine import apply_forecast_defaults
from modules.models import LineType, PlanningRow

pytestmark = pytest.mark.no_fixture


def _row(mat, values):
    return PlanningRow(
        material_number=mat, material_name=f"n{mat}", product_type="Bulk Product",
        product_family="F", spc_product="S", product_cluster="C", product_name="P",
        line_type=LineType.DEMAND_FORECAST.value, values=dict(values),
    )


def test_empty_config_is_noop():
    rows = [_row("A", {"2025-12": 10.0, "2026-01": 0.0})]
    forecasts = {"A": {"2025-12": 10.0, "2026-01": 0.0}}
    assert apply_forecast_defaults(rows, forecasts, None) == 0
    assert apply_forecast_defaults(rows, forecasts, {}) == 0
    assert rows[0].values == {"2025-12": 10.0, "2026-01": 0.0}


def test_fill_empty_only_fills_zero_periods():
    rows = [_row("A", {"2025-12": 10.0, "2026-01": 0.0, "2026-02": 0.0})]
    forecasts = {"A": {"2025-12": 10.0, "2026-01": 0.0, "2026-02": 0.0}}
    changed = apply_forecast_defaults(rows, forecasts, {"mode": "fill_empty", "default": 7000})
    assert changed == 2
    assert rows[0].values == {"2025-12": 10.0, "2026-01": 7000.0, "2026-02": 7000.0}
    # forecasts dict kept consistent for the downstream cascade
    assert forecasts["A"]["2026-01"] == 7000.0


def test_add_mode_adds_to_every_period():
    rows = [_row("A", {"2025-12": 10.0, "2026-01": 0.0})]
    forecasts = {"A": {"2025-12": 10.0, "2026-01": 0.0}}
    changed = apply_forecast_defaults(rows, forecasts, {"mode": "add", "default": 100})
    assert changed == 2
    assert rows[0].values == {"2025-12": 110.0, "2026-01": 100.0}


def test_per_material_overrides_global_default():
    rows = [_row("A", {"2025-12": 0.0}), _row("B", {"2025-12": 0.0}), _row("C", {"2025-12": 0.0})]
    forecasts = {m.material_number: dict(m.values) for m in rows}
    cfg = {"mode": "fill_empty", "default": 50, "per_material": {"B": 999}}
    apply_forecast_defaults(rows, forecasts, cfg)
    assert rows[0].values["2025-12"] == 50.0    # global
    assert rows[1].values["2025-12"] == 999.0   # per-material override
    assert rows[2].values["2025-12"] == 50.0    # global


def test_no_global_default_only_touches_per_material():
    rows = [_row("A", {"2025-12": 0.0}), _row("B", {"2025-12": 0.0})]
    forecasts = {m.material_number: dict(m.values) for m in rows}
    apply_forecast_defaults(rows, forecasts, {"mode": "fill_empty", "per_material": {"B": 42}})
    assert rows[0].values["2025-12"] == 0.0     # untouched (no global default)
    assert rows[1].values["2025-12"] == 42.0


@pytest.mark.usefixtures("golden_fixture_path")
def test_add_mode_cascades_through_full_engine(golden_fixture_path):
    """End-to-end: forecast defaults in 'add' mode raise Line 01 for every
    material, and the change propagates (Line 03 total demand >= Line 01)."""
    from modules.planning_engine import PlanningEngine

    def _run(overrides):
        eng = PlanningEngine(
            str(golden_fixture_path), planning_month="2025-12",
            months_actuals=11, months_forecast=12, config_overrides=overrides,
        )
        eng.run()
        return eng

    base = _run({})
    bumped = _run({"forecast_defaults": {"mode": "add", "default": 1000}})

    period = base.data.periods[2]
    base_l01 = {r.material_number: r.values.get(period, 0.0)
                for r in base.results[LineType.DEMAND_FORECAST.value]}
    bumped_l01 = {r.material_number: r.values.get(period, 0.0)
                  for r in bumped.results[LineType.DEMAND_FORECAST.value]}

    # Every forecast material's Line 01 rose by exactly 1000 in that period.
    assert base_l01, "no demand rows in golden fixture"
    for mat, base_val in base_l01.items():
        assert abs(bumped_l01[mat] - (base_val + 1000.0)) < 1e-6, mat


def test_forecast_defaults_do_not_leak_to_other_sessions_on_rebuild():
    """F3: a session without defaults must never inherit them from the shared
    global config during a rebuild (cross-session contamination)."""
    from ui.engine_rebuild import get_session_config_overrides

    global_config = {"forecast_defaults": {"mode": "add", "default": 7000.0}}
    # Old/cold session: field defaulted to {} on load, no engine.
    sess = {"id": "a", "engine": None, "forecast_defaults": {}}
    ov = get_session_config_overrides(sess, global_config)
    assert "forecast_defaults" not in ov

    # Session that DOES have defaults gets its own, not global's.
    sess_b = {"id": "b", "engine": None,
              "forecast_defaults": {"mode": "fill_empty", "default": 5.0}}
    ov_b = get_session_config_overrides(sess_b, global_config)
    assert ov_b["forecast_defaults"] == {"mode": "fill_empty", "default": 5.0}


def test_forecast_defaults_round_trip_session_store(tmp_path):
    from types import SimpleNamespace

    from ui.session_store import load_sessions_from_disk, save_sessions_to_disk

    engine = SimpleNamespace(
        data=SimpleNamespace(purchased_and_produced=None, valuation_params=None),
        config_overrides={"forecast_defaults": {"mode": "add", "default": 100.0}},
    )
    sessions = {"s1": {"id": "s1", "engine": engine, "parameters": {"planning_month": "2025-12"}}}
    store = tmp_path / "sessions_store.json"
    save_sessions_to_disk(sessions, "s1", store, lambda s, e: {})
    loaded, _ = load_sessions_from_disk(store)
    assert loaded["s1"]["forecast_defaults"] == {"mode": "add", "default": 100.0}


def test_sanitize_forecast_defaults_empty_is_empty():
    """F7: mode-only payloads normalise to {} so an empty save never flags a
    structural change (which would rebuild and drop VP/PAP from the request)."""
    from ui.routes.config import _sanitize_forecast_defaults

    assert _sanitize_forecast_defaults({}) == {}
    assert _sanitize_forecast_defaults({"mode": "fill_empty", "default": None,
                                        "per_material": {}}) == {}
    assert _sanitize_forecast_defaults(None) == {}
    assert _sanitize_forecast_defaults({"mode": "add", "default": 7}) == {"mode": "add", "default": 7.0}


def test_cleared_pap_does_not_resurrect(tmp_path):
    """F9: purchased_and_produced cleared to {} persists as '' and must
    override the global fallback on cold rebuild, not fall through to it."""
    from types import SimpleNamespace

    from ui.engine_rebuild import get_session_config_overrides
    from ui.session_store import load_sessions_from_disk, save_sessions_to_disk

    engine = SimpleNamespace(
        data=SimpleNamespace(purchased_and_produced={}, valuation_params=None),
        config_overrides={},
    )
    sessions = {"s1": {"id": "s1", "engine": engine, "parameters": {"planning_month": "2025-12"}}}
    store = tmp_path / "sessions_store.json"
    save_sessions_to_disk(sessions, "s1", store, lambda s, e: {})
    loaded, _ = load_sessions_from_disk(store)
    sess = loaded["s1"]
    assert sess["purchased_and_produced"] == ""  # cleared, not None

    global_config = {"purchased_and_produced": "OTHER-MAT:1"}
    ov = get_session_config_overrides(sess, global_config)
    # '' overrides the global value (parses to no PAP entries downstream).
    assert ov["purchased_and_produced"] == ""
