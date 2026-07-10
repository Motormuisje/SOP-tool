from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from modules.data_loader import DataLoader
from modules.models import BOMItem, PlanningConfig, ValuationParameters


pytestmark = pytest.mark.no_fixture


def _loader():
    loader = DataLoader.__new__(DataLoader)
    loader.config_overrides = {}
    loader.extract_files = None
    loader.file_path = None
    loader.excel_file = SimpleNamespace(sheet_names=[])
    loader.config = PlanningConfig(initial_date=datetime(2025, 1, 1), site="NLX1")
    loader.materials = {}
    loader.bom = []
    loader.routing = {}
    loader.machines = {}
    loader.machine_groups = {}
    loader.forecasts = {}
    loader.periods = loader.config.get_periods()
    loader.purchased_and_produced = {}
    loader.bom_levels = {}
    loader.purchase_lead_times = {}
    loader.valuation_params = None
    loader.sales_prices = {}
    loader.material_costs = {}
    loader.machine_costs = {}
    return loader


def test_safe_float_handles_nan_bad_values_and_default():
    loader = _loader()

    assert loader._safe_float(float("nan"), default=7.0) == 7.0
    assert loader._safe_float("not-a-number", default=3.0) == 3.0
    assert loader._safe_float("12.5") == 12.5


def test_config_overrides_update_config_periods_and_pap():
    loader = _loader()
    loader.config_overrides = {
        "site": "NLX2",
        "forecast_months": 3,
        "unlimited_machines": "PBA01, PBA02",
        "purchased_and_produced": "MAT-1:0.25, bad-entry, MAT-2:not-number",
    }

    loader._apply_config_overrides()

    assert loader.config.site == "NLX2"
    assert loader.config.forecast_months == 3
    assert loader.periods == ["2025-01", "2025-02", "2025-03"]
    assert loader.config.unlimited_capacity_machine == ["PBA01", "PBA02"]
    assert loader.purchased_and_produced == {"MAT-1": 0.25}


def test_machine_availability_carries_forward_last_excel_period(monkeypatch):
    loader = _loader()
    loader.config.forecast_months = 4
    loader.periods = ["2025-01", "2025-02", "2025-03", "2025-04"]

    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda *args, **kwargs: pd.DataFrame(
            {
                "Machine code": ["PML12"],
                "MachineID": ["PML12"],
                "Machine name": ["PML12"],
                "Machine group": ["PML"],
                "OEE (%)": [85],
                datetime(2025, 1, 1): [140],
                datetime(2025, 2, 1): [140],
                datetime(2025, 3, 1): [float("nan")],
                datetime(2025, 4, 1): [float("nan")],
            }
        ),
    )

    loader._load_machines()

    assert loader.machines["PML12"].availability_by_period == {
        "2025-01": 1.4,
        "2025-02": 1.4,
        "2025-03": 1.4,
        "2025-04": 1.4,
    }


def test_valuation_overrides_create_params_and_skip_empty_values():
    loader = _loader()
    loader.config_overrides = {
        "valuation_params": {
            "1": "10.5",
            "2": "",
            "3": None,
            "4": "4",
            "5": "5",
            "6": "6",
            "7": "7",
            "8": "8",
        }
    }

    loader._apply_valuation_overrides()

    assert isinstance(loader.valuation_params, ValuationParameters)
    assert loader.valuation_params.direct_fte_cost_per_month == pytest.approx(10.5)
    assert loader.valuation_params.indirect_fte_cost_per_month == 0.0
    assert loader.valuation_params.days_payable_outstanding == 8


def test_calculate_bom_levels_is_deterministic_and_handles_cycle():
    loader = _loader()
    loader.forecasts = {"A": {"2025-01": 1.0}}
    loader.bom = [
        BOMItem("P", "A", "Parent A", "B", "Child B", 1.0),
        BOMItem("P", "B", "Parent B", "C", "Child C", 1.0),
        BOMItem("P", "C", "Parent C", "B", "Child B", 1.0),
    ]

    loader._calculate_bom_levels()

    assert loader.bom_levels["A"] == 0
    assert loader.bom_levels["B"] >= 1
    assert loader.get_materials_at_level(loader.bom_levels["B"]) == sorted(
        loader.get_materials_at_level(loader.bom_levels["B"])
    )
    assert loader.get_max_bom_level() >= 1


def test_purchase_and_routing_helpers_return_defaults():
    loader = _loader()
    item = BOMItem("P", "PARENT", "Parent", "CHILD", "Child", 2.0, bom_header_quantity=5.0)
    coproduct = BOMItem("P", "PARENT", "Parent", "CO", "Co", 1.0, is_coproduct=True)
    loader.bom = [item, coproduct]
    loader.routing = {"MAT-1": ["routing-a", "routing-b"]}
    loader.purchase_lead_times = {"MAT-1": 4}
    loader.purchased_and_produced = {"MAT-1": 0.25}

    assert loader.is_purchased_and_produced("MAT-1") is True
    assert loader.get_purchase_fraction("MAT-1") == 0.25
    assert loader.get_purchase_fraction("missing") == 0.0
    assert loader.get_production_ceiling("PARENT") == 5.0
    assert loader.get_production_ceiling("missing") == 1.0
    assert loader.get_lead_time("MAT-1") == 4
    assert loader.get_lead_time("missing") == 1
    assert loader.get_bom_for_parent("PARENT") == [item]
    assert loader.get_primary_routing("MAT-1") == "routing-a"
    assert loader.get_primary_routing("missing") is None
    assert loader.get_all_routings("MAT-1") == ["routing-a", "routing-b"]


def test_financial_loaders_skip_missing_optional_sheets():
    loader = _loader()
    loader.excel_file = SimpleNamespace(sheet_names=[])

    loader._load_avg_sales_price()
    loader._load_cost_raw_material()
    loader._load_cost_machine_hour()
    loader._load_valuation_params()

    assert loader.sales_prices == {}
    assert loader.material_costs == {}
    assert loader.machine_costs == {}
    assert loader.valuation_params is None


def test_valuation_params_requires_all_eight_cost_numbers(monkeypatch):
    loader = _loader()
    loader.excel_file = SimpleNamespace(sheet_names=["Valuation parameters"])

    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda *args, **kwargs: pd.DataFrame(
            {"Cost number": [1, 2, 3], "Value": [10.0, 20.0, 30.0]}
        ),
    )

    loader._load_valuation_params()

    assert loader.valuation_params is None


def test_financial_loaders_filter_by_site_and_aggregate(monkeypatch):
    loader = _loader()
    loader.excel_file = SimpleNamespace(
        sheet_names=["Average sales price", "Cost raw material", "Cost machine hour"]
    )

    def fake_read_excel(excel_file, sheet_name):
        if sheet_name == "Average sales price":
            return pd.DataFrame(
                {
                    "ProductId": ["MAT-1", "MAT-1", "MAT-2"],
                    "PlantCode": ["NLX1", "NLX1", "OTHER"],
                    "Volume 2025": [10.0, 30.0, 100.0],
                    "ExWorks Revenue": [100.0, 600.0, 999.0],
                }
            )
        if sheet_name == "Cost raw material":
            return pd.DataFrame(
                {
                    "Product Code": ["RAW-1", "RAW-2"],
                    "Plant Code": ["NLX1", "OTHER"],
                    "Product Name": ["Raw One", "Raw Two"],
                    "Cost Per Unit": [12.0, 99.0],
                }
            )
        return pd.DataFrame(
            {
                "Act. type short text": ["Machine Variable", "Labor"],
                "Plant Code": ["NLX1", "NLX1"],
                "Cost Center": ["PBA11-NLX1", "LAB01"],
                "Fxd Prices in OCrcy": [55.0, 99.0],
            }
        )

    monkeypatch.setattr(pd, "read_excel", fake_read_excel)

    loader._load_avg_sales_price()
    loader._load_cost_raw_material()
    loader._load_cost_machine_hour()

    assert set(loader.sales_prices) == {"MAT-1"}
    assert loader.sales_prices["MAT-1"].price_per_unit == pytest.approx(17.5)
    assert set(loader.material_costs) == {"RAW-1"}
    assert loader.material_costs["RAW-1"].cost_per_unit == 12.0
    assert set(loader.machine_costs) == {"PBA11"}
    assert loader.machine_costs["PBA11"].variable_cost_per_hour == 55.0
