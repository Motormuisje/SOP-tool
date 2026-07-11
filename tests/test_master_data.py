"""Master-config vervanging — serialisatie, hydratie en de werkboek-vrije run.

Kerngarantie: de store bevat POST-PARSE data. serialize→JSON→hydrate levert
exact dezelfde DataLoader-structuren op als de xlsm-loaders (golden test);
de maandelijkse extract-loaders zijn gedeelde code voor beide paden, dus
structurele pariteit ⇒ enginepariteit bij gelijke extracts. Daarnaast een
volledige engine-run ZONDER enig werkboek (master dict + synthetische
extracts) als end-to-end-bewijs.
"""

import contextlib
import io
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from modules.data_loader import DataLoader
from modules.master_data import (
    MASTER_SCHEMA_VERSION,
    finalize_shift_systems,
    hydrate_loader,
    serialize_master,
)
from modules.models import (
    LineType, Machine, Material, PlanningConfig, ProductType,
    SafetyStockConfig, SalesPriceItem, ShiftSystem, ValuationParameters,
)


# ---------------------------------------------------------------- golden parity

def test_serialize_hydrate_round_trip_matches_xlsm_loader(golden_fixture_path):
    with contextlib.redirect_stdout(io.StringIO()):
        source = DataLoader(str(golden_fixture_path))
        source.load_all()

    master = json.loads(json.dumps(serialize_master(source), default=str))
    assert master['schema_version'] == MASTER_SCHEMA_VERSION

    target = DataLoader(master_data=master)
    with contextlib.redirect_stdout(io.StringIO()):
        hydrate_loader(target, master)
        finalize_shift_systems(target)

    assert target.config.initial_date == source.config.initial_date
    assert target.config.forecast_months == source.config.forecast_months
    assert target.config.site == source.config.site
    assert target.config.unlimited_capacity_machine == source.config.unlimited_capacity_machine
    assert target.forecast_actuals_months == source.forecast_actuals_months
    assert target.periods == source.periods
    assert target.purchased_and_produced == source.purchased_and_produced

    assert target.fte_hours_per_year == source.fte_hours_per_year
    assert target.shift_hours == source.shift_hours
    assert target.default_shift_name == source.default_shift_name

    assert target.materials == source.materials
    assert target.machines == source.machines
    assert target.machine_groups == source.machine_groups
    assert target.safety_stock == source.safety_stock
    assert target.purchase_lead_times == source.purchase_lead_times
    assert target.purchase_moq == source.purchase_moq
    assert target.purchase_sheet_materials == source.purchase_sheet_materials
    assert target.purchase_actuals == source.purchase_actuals
    assert target.sales_prices == source.sales_prices
    assert target.material_costs == source.material_costs
    assert target.machine_costs == source.machine_costs
    assert target.valuation_params == source.valuation_params


# --------------------------------------------------- werkboek-vrije engine-run

def _fake_source_loader():
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


def _write_extracts(tmp_path):
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

    bom = _wb('bom.xlsx', 'EXP_BOM',
              ['Material', 'Component', 'Bill of Material', 'Plant',
               'BILLOFMATERIALITEMQUANTITY', 'BOM Header Quantity in Base UoM',
               'Material Name', 'Component Description', 'Co-product', 'PV'],
              [['M1', 'M2', '1', 'NLX1', 2.0, 1.0, 'Parent', 'Child', '', '']])
    routing = _wb('routing.xlsx', 'EXP_ROUTING',
                  ['Material', 'Work Center', 'Plant', 'Base Quantity',
                   'Standard Value 01', 'Material Description', 'PV'],
                  [['M1', 'PBA01', 'NLX1', 100.0, 2.0, 'Parent', '']])
    stock = _wb('stock.xlsx', 'SAPUI5 Export',
                ['Material', 'Plant', 'Unrestricted Stock', 'Total Value',
                 'Total Stock', 'Value of Unrestricted Stock'],
                [['M1', 'NLX1', 50.0, 500.0, 50.0, 500.0],
                 ['M2', 'NLX1', 20.0, 60.0, 20.0, 60.0]])
    # Header direct op rij 0; anker = eerste kolomkop 'Product Number Name'.
    # actuals=1 → anchor = eerste periodekolom + 2 maanden = 2026-01.
    forecast = _wb('forecast.xlsx', 'Blad1',
                   ['Product Number Name', '2025/M11', '2025/M12',
                    '2026/M01', '2026/M02', '2026/M03'],
                   [['M1 - Parent', 90.0, 95.0, 100.0, 110.0, 120.0]])
    return {'bom': bom, 'routing': routing, 'stock': stock, 'forecast': forecast}


def test_full_engine_run_without_any_workbook(tmp_path):
    """Master store + maandelijkse extracts: geen basis-.xlsm meer nodig."""
    from modules.planning_engine import PlanningEngine

    master = json.loads(json.dumps(serialize_master(_fake_source_loader()), default=str))
    extracts = _write_extracts(tmp_path)

    with contextlib.redirect_stdout(io.StringIO()):
        engine = PlanningEngine(
            None, planning_month=None, months_actuals=1, months_forecast=3,
            extract_files=extracts, master_data=master,
        )
        engine.run()

    assert engine.data.periods == ['2026-01', '2026-02', '2026-03']
    l01 = [r for r in engine.results[LineType.DEMAND_FORECAST.value]
           if r.material_number == 'M1']
    assert l01 and l01[0].values == {'2026-01': 100.0, '2026-02': 110.0, '2026-03': 120.0}

    # M1 is BOM-parent met routing → productie; M2 krijgt afhankelijke vraag.
    prod = [r for r in engine.results[LineType.PRODUCTION_PLAN.value]
            if r.material_number == 'M1']
    assert prod and sum(prod[0].values.values()) > 0
    dep = [r for r in engine.results[LineType.DEPENDENT_DEMAND.value]
           if r.material_number == 'M2' and r.aux_column == 'M1']
    assert dep, 'kind kreeg geen afhankelijke vraag zonder werkboek'

    # Machines + waardeplanning draaien mee vanuit de store.
    machine_rows = [r for r in engine.results[LineType.CAPACITY_UTILIZATION.value]
                    if r.product_type == 'Machine']
    assert machine_rows, 'machinerijen ontbreken in de werkboek-vrije run'
    assert engine.data.machines['PBA01'].shift_system == ShiftSystem.THREE_SHIFT
    value_l01 = [r for r in engine.value_results.get(LineType.DEMAND_FORECAST.value, [])
                 if r.material_number == 'M1']
    assert value_l01 and sum(value_l01[0].values.values()) == pytest.approx(12.0 * 330.0)


def test_master_store_persistence_round_trip(tmp_path):
    from ui.master_store import load_master_store, master_counts, save_master_store

    master = json.loads(json.dumps(serialize_master(_fake_source_loader()), default=str))
    store_path = tmp_path / 'master_store.json'
    record = save_master_store(store_path, master, source_filename='MS_RECONC.xlsm')
    assert record['version'] == 1 and record['source_filename'] == 'MS_RECONC.xlsm'

    loaded = load_master_store(store_path)
    assert loaded['master'] == master
    counts = master_counts(loaded['master'])
    assert counts['materials'] == 2 and counts['machines'] == 1
    assert counts['valuation_params'] == 1

    # Bewerking: versie omhoog, import-metadata blijft, edited_at gezet.
    record2 = save_master_store(store_path, master, previous=loaded, edited=True)
    assert record2['version'] == 2
    assert record2['source_filename'] == 'MS_RECONC.xlsm'
    assert record2['edited_at']

    # Corrupt bestand → None + quarantaine, geen crash.
    store_path.write_text('{{{', encoding='utf-8')
    assert load_master_store(store_path) is None
    assert not store_path.exists()
