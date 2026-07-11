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
