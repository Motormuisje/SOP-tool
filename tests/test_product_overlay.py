"""Fase 3 — product overlay: normalization, validation, cycle detection and
the DataLoader mutations of apply_product_overlay (synthetic data, no fixture)."""

import types
from datetime import datetime

import pytest

from modules.data_loader import DataLoader
from modules.models import (
    BOMItem, Machine, Material, PlanningConfig, ProductType, SafetyStockConfig,
)
from modules.product_overlay import (
    apply_product_overlay,
    check_overlay_cycles,
    find_bom_cycle,
    normalize_material_number,
    validate_added_product,
)

pytestmark = pytest.mark.no_fixture


def _mat(mn, name='Mat', ptype=ProductType.BULK_PRODUCT):
    return Material(material_number=mn, name=name, product_type=ptype,
                    product_family='FAM')


def _bom(parent, component, qty=1.0):
    return BOMItem(plant='NLX1', parent_material=parent, parent_name='',
                   component_material=component, component_name='',
                   quantity_per=qty)


def _fake_data(periods=('2026-01', '2026-02', '2026-03'),
               forecast_first_period='2025-01', actuals=11):
    """Minimal DataLoader stand-in with the real _calculate_bom_levels bound."""
    data = types.SimpleNamespace(
        config=PlanningConfig(initial_date=datetime(2026, 1, 1), site='NLX1'),
        materials={'M1': _mat('M1'), 'M2': _mat('M2'), 'M3': _mat('M3')},
        bom=[_bom('M1', 'M2'), _bom('M2', 'M3')],
        routing={},
        machines={'PBA01': Machine(machine_id='PBA01', machine_code='PBA01',
                                   name='Press', oee=0.8)},
        forecasts={'M1': {'2025-01': 10.0}},
        stock_levels={},
        safety_stock={},
        periods=list(periods),
        purchase_lead_times={},
        purchase_moq={},
        purchase_sheet_materials=set(),
        purchased_and_produced={},
        bom_levels={},
        sales_prices={},
        material_costs={},
        forecast_first_period=forecast_first_period,
        forecast_actuals_months=actuals,
        bom_cycle_warnings=[],
    )
    data._calculate_bom_levels = types.MethodType(
        DataLoader._calculate_bom_levels, data)
    data._calculate_bom_levels()
    return data


def _product(**over):
    base = {
        'material_number': '900000001',
        'name': 'Nieuw product',
        'product_type': 'bulk',
        'flat_volume': 100.0,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------- normalize

def test_normalize_strips_float_artifact_and_whitespace():
    assert normalize_material_number(' 600003822.0 ') == '600003822'
    assert normalize_material_number(600003822.0) == '600003822'
    assert normalize_material_number('600003822.000') == '600003822'
    assert normalize_material_number(900000001) == '900000001'


def test_normalize_leaves_real_decimals_and_text_alone():
    assert normalize_material_number('1.50') == '1.50'
    assert normalize_material_number('ZZMILL01') == 'ZZMILL01'
    assert normalize_material_number(None) == ''


# ----------------------------------------------------------------- validate

def test_validate_happy_path_sanitizes_and_defaults():
    data = _fake_data()
    out = validate_added_product(_product(
        material_number=' 900000001.0 ',
        volumes={'2026-02': '250'},
        bom_as_parent=[{'component': 'M2', 'qty_per': '2,5'.replace(',', '.')}],
        routing=[{'work_center': 'PBA01', 'base_quantity': 1000, 'standard_time': 8}],
        lead_time='2', moq=50, pap_fraction=0.5,
        sales_price=12.5, raw_material_cost=3, default_inventory_value=4,
    ), data)
    assert out['material_number'] == '900000001'
    assert out['volumes'] == {'2026-02': 250.0}
    assert out['bom_as_parent'] == [{'component': 'M2', 'qty_per': 2.5}]
    assert out['routing'][0]['work_center'] == 'PBA01'
    assert out['lead_time'] == 2 and out['moq'] == 50.0
    assert out['pap_fraction'] == 0.5


@pytest.mark.parametrize('broken, msg_part', [
    (dict(material_number=''), 'Materiaalnummer is verplicht'),
    (dict(name=''), 'Productnaam is verplicht'),
    (dict(product_type='vloeibaar'), 'Ongeldig producttype'),
    (dict(material_number='M1'), 'bestaat al in het bronbestand'),
    (dict(flat_volume=-1), 'vast volume'),
    (dict(volumes={'jan': 5}), 'Ongeldige periode'),
    (dict(pap_fraction=1.5), 'maximaal 1'),
    (dict(bom_as_parent=[{'component': 'ONBEKEND', 'qty_per': 1}]), 'onbekend'),
    (dict(bom_as_parent=[{'component': 'M2', 'qty_per': 0}]), 'groter dan 0'),
    (dict(bom_as_parent=[{'component': '900000001', 'qty_per': 1}]), 'zichzelf'),
    (dict(routing=[{'work_center': 'NOPE', 'base_quantity': 1, 'standard_time': 1}]),
     'bestaat niet'),
    (dict(routing=[{'work_center': 'PBA01', 'base_quantity': 0, 'standard_time': 1}]),
     'basisaantal'),
])
def test_validate_rejects_with_dutch_message(broken, msg_part):
    data = _fake_data()
    with pytest.raises(ValueError) as exc:
        validate_added_product(_product(**broken), data)
    assert msg_part in str(exc.value)


def test_validate_allows_reference_to_other_added_product():
    data = _fake_data()
    other = _product(material_number='900000002', name='Ander')
    out = validate_added_product(_product(
        bom_as_parent=[{'component': '900000002', 'qty_per': 1.0}],
    ), data, other_added=[other])
    assert out['bom_as_parent'][0]['component'] == '900000002'


def test_validate_rejects_duplicate_added_number():
    data = _fake_data()
    other = _product()  # same 900000001
    with pytest.raises(ValueError) as exc:
        validate_added_product(_product(), data, other_added=[other])
    assert 'al als dynamisch product' in str(exc.value)


# ------------------------------------------------------------------ sourcing

_PRODUCED_FIELDS = dict(
    bom_as_parent=[{'component': 'M2', 'qty_per': 1.0}],
    routing=[{'work_center': 'PBA01', 'base_quantity': 100, 'standard_time': 1}],
)


@pytest.mark.parametrize('broken, msg_part', [
    (dict(sourcing='teleportatie'), 'Ongeldige verwervingswijze'),
    (dict(sourcing='purchased',
          routing=[{'work_center': 'PBA01', 'base_quantity': 1, 'standard_time': 1}]),
     'geen routing'),
    (dict(sourcing='purchased', bom_as_parent=[{'component': 'M2', 'qty_per': 1}]),
     'verbruikt geen componenten'),
    (dict(sourcing='purchased', pap_fraction=0.5), 'productiefractie'),
    (dict(sourcing='produced',
          routing=[{'work_center': 'PBA01', 'base_quantity': 1, 'standard_time': 1}]),
     'stuklijstcomponent'),
    (dict(sourcing='produced', bom_as_parent=[{'component': 'M2', 'qty_per': 1}]),
     'routing-regel'),
    (dict(sourcing='produced', moq=25, **_PRODUCED_FIELDS), 'MOQ en lead time'),
    (dict(sourcing='produced', lead_time=2, **_PRODUCED_FIELDS), 'MOQ en lead time'),
    (dict(sourcing='produced', pap_fraction=1.0, **_PRODUCED_FIELDS), 'productiefractie'),
    (dict(sourcing='mix'), 'productiefractie verplicht'),
])
def test_sourcing_rejects_dead_field_combinations(broken, msg_part):
    data = _fake_data()
    with pytest.raises(ValueError) as exc:
        validate_added_product(_product(**broken), data)
    assert msg_part in str(exc.value)


def test_sourcing_happy_paths():
    data = _fake_data()
    purchased = validate_added_product(
        _product(sourcing='purchased', moq=30, lead_time=2), data)
    assert purchased['sourcing'] == 'purchased' and purchased['moq'] == 30.0

    produced = validate_added_product(
        _product(sourcing='produced', **_PRODUCED_FIELDS), data)
    assert produced['sourcing'] == 'produced'

    mix = validate_added_product(
        _product(sourcing='mix', pap_fraction=0.6, moq=10, **_PRODUCED_FIELDS), data)
    assert mix['sourcing'] == 'mix' and mix['pap_fraction'] == 0.6


def test_without_sourcing_legacy_combinations_stay_valid():
    """Pre-selector payloads (no 'sourcing' key) keep the engine inference:
    a produced-looking product with an MOQ must not start failing rebuilds."""
    data = _fake_data()
    out = validate_added_product(_product(moq=25, lead_time=2, **_PRODUCED_FIELDS), data)
    assert out['sourcing'] is None
    assert out['moq'] == 25.0 and out['lead_time'] == 2


# -------------------------------------------------------------------- cycles

def test_find_bom_cycle_none_on_dag():
    assert find_bom_cycle({'A': {'B', 'C'}, 'B': {'C'}}) is None


def test_find_bom_cycle_returns_path():
    cycle = find_bom_cycle({'A': {'B'}, 'B': {'C'}, 'C': {'A'}})
    assert cycle is not None
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {'A', 'B', 'C'}


def test_check_overlay_cycles_raises_for_overlay_cycle():
    data = _fake_data()  # workbook: M1 -> M2 -> M3
    # New product is parent of M1 and child of M3: M3 -> P -> M1 -> M2 -> M3.
    product = validate_added_product(_product(
        bom_as_parent=[{'component': 'M1', 'qty_per': 1.0}],
        bom_as_child=[{'parent': 'M3', 'qty_per': 1.0}],
    ), data)
    with pytest.raises(ValueError) as exc:
        check_overlay_cycles(data, [product])
    assert 'BOM-cyclus' in str(exc.value)
    assert '900000001' in str(exc.value)


def test_apply_is_atomic_on_cycle_error():
    data = _fake_data()
    before_bom = len(data.bom)
    before_mats = set(data.materials)
    with pytest.raises(ValueError):
        apply_product_overlay(data, [_product(
            bom_as_parent=[{'component': 'M1', 'qty_per': 1.0}],
            bom_as_child=[{'parent': 'M3', 'qty_per': 1.0}],
        )])
    assert len(data.bom) == before_bom
    assert set(data.materials) == before_mats
    assert '900000001' not in data.forecasts
    assert '900000001' not in data.safety_stock


def test_workbook_cycle_only_warns_not_raises():
    data = _fake_data()
    data.bom.append(_bom('M3', 'M1'))  # pre-existing workbook cycle
    data._calculate_bom_levels()
    # Overlay on an unrelated branch must still apply.
    apply_product_overlay(data, [_product()])
    assert '900000001' in data.materials
    # And the loader-level warning helper flags the workbook cycle.
    data.bom_cycle_warnings = []
    DataLoader._warn_on_bom_cycles(data)
    assert data.bom_cycle_warnings, 'workbook cycle must be recorded'


# --------------------------------------------------------------------- apply

def test_apply_full_product_mutates_all_stores():
    data = _fake_data()
    apply_product_overlay(data, [_product(
        product_family='FAM-NEW',
        volumes={'2026-02': 250.0},
        starting_stock=40.0, safety_stock=10.0,
        bom_as_parent=[{'component': 'M2', 'qty_per': 2.0}],
        bom_as_child=[{'parent': 'M1', 'qty_per': 0.5}],
        routing=[{'work_center': 'PBA01', 'base_quantity': 1000.0, 'standard_time': 8.0}],
        lead_time=2, moq=50.0, pap_fraction=0.25,
        sales_price=12.0, raw_material_cost=3.0, default_inventory_value=4.0,
    )])
    mn = '900000001'
    mat = data.materials[mn]
    assert mat.product_type == ProductType.BULK_PRODUCT
    assert mat.product_family == 'FAM-NEW'
    assert mat.default_inventory_value == 4.0
    assert mat.production_line is None and mat.grouped_production_line is None

    edges = {(b.parent_material, b.component_material) for b in data.bom}
    assert (mn, 'M2') in edges and ('M1', mn) in edges

    assert data.routing[mn][0].work_center == 'PBA01'
    assert data.stock_levels[mn] == 40.0
    assert isinstance(data.safety_stock[mn], SafetyStockConfig)
    assert data.safety_stock[mn].safety_stock == 10.0
    assert data.purchase_lead_times[mn] == 2
    assert data.purchase_moq[mn] == 50.0
    assert mn in data.purchase_sheet_materials
    assert data.purchased_and_produced[mn] == 0.25
    assert data.sales_prices[mn].price_per_unit == 12.0
    assert data.material_costs[mn].cost_per_unit == 3.0

    # BOM levels recomputed: the new product is a child of M1 (level 0),
    # so it sits below M1 and above M2.
    assert data.bom_levels[mn] >= 1
    assert data.bom_levels['M2'] > data.bom_levels[mn] - 1  # M2 also child of new product


def test_apply_forecast_uses_anchor_math():
    data = _fake_data(forecast_first_period='2025-01', actuals=11)
    apply_product_overlay(data, [_product(
        flat_volume=100.0, volumes={'2026-02': 250.0})])
    # anchor = 2025-01 + 12 months = 2026-01; planning periods 2026-01..03
    fdict = data.forecasts['900000001']
    assert fdict['2026-01'] == 100.0
    assert fdict['2026-02'] == 250.0
    assert fdict['2026-03'] == 100.0


def test_apply_forecast_fallback_without_first_period():
    data = _fake_data(forecast_first_period=None, actuals=11)
    # Deze test toetst de POSITIONELE fallback (VBA-validatiemodus); de
    # default is inmiddels kalender-uitlijning.
    data.config.forecast_align_to_month = False
    apply_product_overlay(data, [_product(flat_volume=100.0)])
    fdict = data.forecasts['900000001']
    # A zero key 12 months before periods[0] forces the sorted-keys fallback
    # in ForecastEngine to derive periods[0] as the anchor.
    assert fdict['2025-01'] == 0.0
    assert fdict['2026-01'] == 100.0 and fdict['2026-03'] == 100.0


def test_apply_bomless_product_always_gets_safety_stock_entry():
    data = _fake_data()
    apply_product_overlay(data, [_product(safety_stock=0.0)])
    # Without BOM edges the standalone pass (STEP 4b) only picks up materials
    # present in data.safety_stock — the overlay must guarantee the entry.
    assert '900000001' in data.safety_stock
    assert '900000001' not in data.bom_levels  # no edges -> no level


def test_apply_two_products_referencing_each_other():
    data = _fake_data()
    p1 = _product(material_number='900000001', name='Een',
                  bom_as_parent=[{'component': '900000002', 'qty_per': 3.0}])
    p2 = _product(material_number='900000002', name='Twee', flat_volume=None)
    apply_product_overlay(data, [p1, p2])
    edges = {(b.parent_material, b.component_material) for b in data.bom}
    assert ('900000001', '900000002') in edges
    # Component name resolved from the overlay, not empty.
    row = next(b for b in data.bom
               if (b.parent_material, b.component_material) == ('900000001', '900000002'))
    assert row.component_name == 'Twee'
    assert data.bom_levels['900000002'] == data.bom_levels['900000001'] + 1


def test_apply_empty_overlay_is_noop():
    data = _fake_data()
    before = (dict(data.materials), list(data.bom), dict(data.bom_levels))
    apply_product_overlay(data, [])
    assert (dict(data.materials), list(data.bom), dict(data.bom_levels)) == before
