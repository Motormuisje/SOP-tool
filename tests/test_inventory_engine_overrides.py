"""Unit tests for InventoryEngine.calculate_for_material override_initial_stock.

Self-contained: stubs DataLoader with SimpleNamespace so no Excel fixture
or DB load is needed. Mirrors the @pytest.mark.no_fixture pattern used
elsewhere in the suite.
"""

from types import SimpleNamespace

import pytest

from modules.inventory_engine import InventoryEngine
from modules.models import Material, ProductType, SafetyStockConfig


PERIODS = ["2026-01", "2026-02", "2026-03"]
MAT = "MAT-1"


def _make_data(stock_level: float = 100.0):
    """Build a minimal DataLoader-like stub for a single purchased material.

    Material is a Raw Material so the engine takes the purchase-only path
    (no production plan). MOQ=1, lead_time=0 makes the math trivial:
    purchase_receipt[period] = max(target - running_stock + demand, 0)
    rounded up to MOQ multiples.
    """
    material = Material(
        material_number=MAT,
        name="Test material",
        product_type=ProductType.RAW_MATERIAL,
        product_family="FAM",
    )
    safety = SafetyStockConfig(
        material_number=MAT,
        safety_stock=0.0,
        lot_size=1.0,
        strategic_stock=0.0,
        target_stock=0.0,
        use_moving_average=False,
    )
    data = SimpleNamespace(
        periods=list(PERIODS),
        materials={MAT: material},
        bom=[],
        stock_levels={MAT: stock_level},
        safety_stock={MAT: safety},
        purchase_sheet_materials={MAT},
        purchase_actuals={},
        # Method stubs — engine calls these via getattr-style methods.
        is_purchased_and_produced=lambda m: False,
        get_purchase_fraction=lambda m: 0.0,
        get_production_ceiling=lambda m: 1.0,
        get_purchase_moq=lambda m: 1.0,
        get_lead_time=lambda m: 0,
        get_all_routings=lambda m: [],
    )
    return data


@pytest.mark.no_fixture
def test_override_initial_stock_replaces_data_lookup():
    data = _make_data(stock_level=100.0)
    engine = InventoryEngine(data)

    forecast = {p: 10.0 for p in PERIODS}
    result = engine.calculate_for_material(
        mat_num=MAT,
        forecast=forecast,
        dependent_demand_agg={p: 0.0 for p in PERIODS},
        dependent_demand_by_parent={},
        override_initial_stock=500.0,
    )

    inventory = result["inventory"]
    purchase = result["purchase_receipt"]
    p0 = PERIODS[0]
    # initial=500, demand=10, target=0 → raw_need = 0 - 500 + 10 = -490 → no purchase.
    # Inventory[p0] = 500 - 10 + 0 = 490 (NOT 100 - 10 = 90 from data.stock_levels).
    assert purchase[p0] == 0.0
    assert inventory[p0] == 490.0


@pytest.mark.no_fixture
def test_override_initial_stock_none_falls_back_to_data():
    data = _make_data(stock_level=100.0)
    engine = InventoryEngine(data)

    forecast = {p: 10.0 for p in PERIODS}
    result = engine.calculate_for_material(
        mat_num=MAT,
        forecast=forecast,
        dependent_demand_agg={p: 0.0 for p in PERIODS},
        dependent_demand_by_parent={},
        # override_initial_stock left at default None
    )

    p0 = PERIODS[0]
    # initial=100, demand=10 → inventory[p0] = 100 - 10 = 90.
    assert result["inventory"][p0] == 90.0


@pytest.mark.no_fixture
def test_override_initial_stock_zero_is_respected():
    data = _make_data(stock_level=100.0)
    engine = InventoryEngine(data)

    forecast = {p: 10.0 for p in PERIODS}
    result = engine.calculate_for_material(
        mat_num=MAT,
        forecast=forecast,
        dependent_demand_agg={p: 0.0 for p in PERIODS},
        dependent_demand_by_parent={},
        override_initial_stock=0.0,
    )

    p0 = PERIODS[0]
    # initial=0, demand=10, target=0 → raw_need=10 → purchase=10 (MOQ=1).
    # Inventory[p0] = 0 - 10 + 10 = 0. Critically, NOT the 90 we'd see if
    # the override fell back to data.stock_levels=100.
    assert result["purchase_receipt"][p0] == 10.0
    assert result["inventory"][p0] == 0.0
