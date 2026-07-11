"""Gedeelde synthetische masterdata-/extract-fixtures (master-config tests)."""

from datetime import datetime
from types import SimpleNamespace

from modules.models import (
    Machine, Material, PlanningConfig, ProductType, SafetyStockConfig,
    SalesPriceItem, ValuationParameters,
)


def fake_master_loader():
    """Hand-built 'loader' met echte dataclasses om een master-dict te maken."""
    return SimpleNamespace(
        config=PlanningConfig(initial_date=datetime(2026, 1, 1), forecast_months=3,
                              site='NLX1', unlimited_capacity_machine=[]),
        forecast_actuals_months=1,
        purchased_and_produced={},
        fte_hours_per_year=1492.0,
        shift_hours={'3-shift system': 520.0},
        default_shift_name='3-shift system',
        materials={
            'M1': Material(material_number='M1', name='Parent', product_type=ProductType.BULK_PRODUCT,
                           product_family='FAM'),
            'M2': Material(material_number='M2', name='Child', product_type=ProductType.RAW_MATERIAL,
                           product_family='FAM'),
        },
        machines={'PBA01': Machine(machine_id='PBA01', machine_code='PBA01', name='Press',
                                   oee=0.8, machine_group='G1',
                                   availability_by_period={'2026-01': 1.0})},
        safety_stock={'M1': SafetyStockConfig(material_number='M1', safety_stock=10.0,
                                              lot_size=0.0)},
        purchase_lead_times={'M2': 1},
        purchase_moq={'M2': 5.0},
        purchase_sheet_materials={'M2'},
        purchase_actuals={},
        sales_prices={'M1': SalesPriceItem(plant_code='NLX1', product_id='M1',
                                           volume_2025=1.0, ex_works_revenue=12.0)},
        material_costs={},
        machine_costs={},
        valuation_params=ValuationParameters(
            direct_fte_cost_per_month=1000.0, indirect_fte_cost_per_month=500.0,
            overhead_cost_per_month=200.0, sga_cost_per_month=100.0,
            depreciation_per_year=1200.0, net_book_value=50000.0,
            days_sales_outstanding=30, days_payable_outstanding=30),
    )


def write_extract_files(tmp_path):
    """Vier minimale maandextracts in de formaten van de extract-loaders."""
    import openpyxl

    def _wb(name, sheet, headers, rows):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet
        ws.append(headers)
        for row in rows:
            ws.append(row)
        path = tmp_path / name
        wb.save(str(path))
        return str(path)

    bom = _wb('bom_extract.xlsx', 'EXP_BOM',
              ['Material', 'Component', 'Bill of Material', 'Plant',
               'BILLOFMATERIALITEMQUANTITY', 'BOM Header Quantity in Base UoM',
               'Material Name', 'Component Description', 'Co-product', 'PV'],
              [['M1', 'M2', '1', 'NLX1', 2.0, 1.0, 'Parent', 'Child', '', '']])
    routing = _wb('routing_extract.xlsx', 'EXP_ROUTING',
                  ['Material', 'Work Center', 'Plant', 'Base Quantity',
                   'Standard Value 01', 'Material Description', 'PV'],
                  [['M1', 'PBA01', 'NLX1', 100.0, 2.0, 'Parent', '']])
    stock = _wb('stock_extract.xlsx', 'SAPUI5 Export',
                ['Material', 'Plant', 'Unrestricted Stock', 'Total Value',
                 'Total Stock', 'Value of Unrestricted Stock'],
                [['M1', 'NLX1', 50.0, 500.0, 50.0, 500.0],
                 ['M2', 'NLX1', 20.0, 60.0, 20.0, 60.0]])
    # Header direct op rij 0; actuals=1 → anchor = eerste periodekolom + 2.
    forecast = _wb('forecast_extract.xlsx', 'Blad1',
                   ['Product Number Name', '2025/M11', '2025/M12',
                    '2026/M01', '2026/M02', '2026/M03'],
                   [['M1 - Parent', 90.0, 95.0, 100.0, 110.0, 120.0]])
    return {'bom': bom, 'routing': routing, 'stock': stock, 'forecast': forecast}
