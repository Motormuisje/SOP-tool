"""Materiaalgroepen — pure scoping-helpers (synthetische rijen, no fixture)."""

from types import SimpleNamespace

import pytest

from modules.models import LineType, PlanningRow
from ui.scoping import (
    group_material_set,
    material_l07_hours_by_machine,
    resolve_active_group,
    scale_utilization,
    scope_inventory_quality,
    scope_trend,
    scoped_financials,
    scoped_marker,
)

pytestmark = pytest.mark.no_fixture

P = ['2026-01', '2026-02']


def _row(mat, values, line_type=LineType.TOTAL_DEMAND.value, aux=None,
         product_type='Bulk Product', name='', starting_stock=0.0):
    return PlanningRow(
        material_number=mat, material_name=name or f'N{mat}',
        product_type=product_type, product_family='', spc_product='',
        product_cluster='', product_name='', line_type=line_type,
        aux_column=aux, values=dict(values), starting_stock=starting_stock,
    )


# ------------------------------------------------------- groep-resolutie

def test_resolve_active_group_handles_stale_and_missing():
    group = {'id': 'g1', 'materials': ['M1']}
    sess = {'active_material_group': 'g1', 'material_groups': {'g1': group}}
    assert resolve_active_group(sess) is group
    assert resolve_active_group({'active_material_group': 'weg',
                                 'material_groups': {'g1': group}}) is None
    assert resolve_active_group({'active_material_group': None}) is None
    assert resolve_active_group(None) is None


def test_group_material_set_counts_unknown():
    data = SimpleNamespace(materials={'M1': 1, 'M2': 1})
    mats, missing = group_material_set({'materials': ['M1', 'GHOST']}, data)
    assert mats == {'M1', 'GHOST'} and missing == 1
    marker = scoped_marker({'id': 'g', 'name': 'X', 'materials': ['M1', 'GHOST']}, data)
    assert marker['materials'] == 2 and marker['missing'] == 1
    assert 'EBIT' in marker['omitted'] and marker['fte_scopable'] is False


# ----------------------------------------------------------------- trends

def test_scope_trend_sums_only_group_rows():
    rows = [_row('M1', {'2026-01': 10.0, '2026-02': 20.0}),
            _row('M2', {'2026-01': 1.0, '2026-02': 2.0}),
            _row('M3', {'2026-01': 100.0, '2026-02': 200.0})]
    assert scope_trend(rows, {'M1', 'M2'}, P) == {'2026-01': 11.0, '2026-02': 22.0}
    assert scope_trend(rows, set(), P) == {}


# ------------------------------------------------------- machine-uren/util

def _l07_rows():
    return [
        _row('M1', {'2026-01': 4.0, '2026-02': 6.0}, LineType.CAPACITY_UTILIZATION.value, aux='PBA01'),
        _row('M2', {'2026-01': 8.0, '2026-02': 2.0}, LineType.CAPACITY_UTILIZATION.value, aux='PBA01'),
        _row('M1', {'2026-01': 5.0, '2026-02': 5.0}, LineType.CAPACITY_UTILIZATION.value, aux='PBA02'),
        # Machine-aggregatierij moet worden genegeerd:
        _row('Z_MACH01', {'2026-01': 99.0, '2026-02': 99.0},
             LineType.CAPACITY_UTILIZATION.value, aux='GRP', product_type='Machine',
             name='PBA01'),
    ]


def test_material_l07_hours_by_machine_full_and_scoped():
    full = material_l07_hours_by_machine(_l07_rows(), None, P)
    assert full['PBA01'] == {'2026-01': 12.0, '2026-02': 8.0}
    assert full['PBA02'] == {'2026-01': 5.0, '2026-02': 5.0}
    scoped = material_l07_hours_by_machine(_l07_rows(), {'M1'}, P)
    assert scoped['PBA01'] == {'2026-01': 4.0, '2026-02': 6.0}


def test_scale_utilization_is_share_and_never_exceeds_full():
    full_util = {'2026-01': 80.0, '2026-02': 50.0}
    group = {'2026-01': 4.0, '2026-02': 8.0}
    full = {'2026-01': 12.0, '2026-02': 8.0}
    scaled = scale_utilization(full_util, group, full)
    assert scaled['2026-01'] == pytest.approx(80.0 * 4 / 12, abs=0.05)
    assert scaled['2026-02'] == 50.0  # volledige groep = volledige benutting
    for period in P:
        assert scaled[period] <= full_util[period]
    # Nul uren → nul aandeel, geen deling door nul.
    assert scale_utilization({'x': 60.0}, {'x': 0.0}, {'x': 0.0}) == {'x': 0.0}


# --------------------------------------------------------------------- IQ

def test_scope_inventory_quality_filters_and_recomputes_top10():
    per_material = [
        {'material_number': 'M1', 'total_overstock': 10.0, 'starting_overstock': 5.0},
        {'material_number': 'M2', 'total_overstock': 30.0, 'starting_overstock': 1.0},
        {'material_number': 'M3', 'total_overstock': 20.0, 'starting_overstock': 9.0},
    ]
    scoped, top10, total = scope_inventory_quality(per_material, {'M1', 'M3'})
    assert [m['material_number'] for m in scoped] == ['M1', 'M3']
    assert [m['material_number'] for m in top10] == ['M3', 'M1']  # starting_overstock desc
    assert total == 30.0


# ------------------------------------------------------ scoped financials

def _fake_engine():
    vr = {
        LineType.DEMAND_FORECAST.value: [
            _row('M1', {'2026-01': 1200.0, '2026-02': 1000.0}),
            _row('M2', {'2026-01': 500.0, '2026-02': 500.0}),
        ],
        LineType.TOTAL_DEMAND.value: [
            _row('M1', {'2026-01': 300.0, '2026-02': 250.0}),
        ],
        LineType.PURCHASE_RECEIPT.value: [
            _row('M1', {'2026-01': 90.0, '2026-02': 60.0}),
        ],
        LineType.INVENTORY.value: [
            _row('M1', {'2026-01': 400.0, '2026-02': 380.0}, starting_stock=100.0),
            _row('M2', {'2026-01': 999.0, '2026-02': 999.0}, starting_stock=999.0),
        ],
        # Value-L07: machinekostrij per machine, aux = tarief/uur.
        LineType.CAPACITY_UTILIZATION.value: [
            _row('Z_MACH01', {'2026-01': 0.0, '2026-02': 0.0},
                 LineType.CAPACITY_UTILIZATION.value, aux=50.0,
                 product_type='Machine', name='PBA01'),
        ],
    }
    results = {LineType.CAPACITY_UTILIZATION.value: _l07_rows()}
    data = SimpleNamespace(
        machines={'PBA01': SimpleNamespace(oee=0.8), 'PBA02': SimpleNamespace(oee=1.0)},
        valuation_params=SimpleNamespace(days_sales_outstanding=30.0,
                                         days_payable_outstanding=60.0),
    )
    return SimpleNamespace(value_results=vr, results=results, data=data)


def test_scoped_financials_bijdragemarge_math():
    fin = scoped_financials(_fake_engine(), {'M1'}, P)
    assert fin['TURNOVER'] == {'2026-01': 1200.0, '2026-02': 1000.0}
    assert fin['RAW MATERIAL COST'] == {'2026-01': 300.0, '2026-02': 250.0}
    # Machinekost: M1-uren op PBA01 (4;6) / OEE 0.8 × tarief 50 = 250;375.
    # PBA02 heeft geen value-kostrij → telt niet mee (zoals ongescoopt).
    assert fin['MACHINE COST'] == {'2026-01': 250.0, '2026-02': 375.0}
    assert fin['BIJDRAGEMARGE'] == {'2026-01': 1200.0 - 300.0 - 250.0,
                                    '2026-02': 1000.0 - 250.0 - 375.0}
    assert fin['INVENTORY VALUE']['2026-01'] == 400.0
    assert fin['INVENTORY VALUE']['Starting stock'] == 100.0
    # DSO 30 → receivables == turnover; DPO 60 → payables = 2× purchase cost.
    assert fin['RECEIVABLES'] == {'2026-01': 1200.0, '2026-02': 1000.0}
    assert fin['PAYABLES'] == {'2026-01': 180.0, '2026-02': 120.0}
    assert fin['WORKING CAPITAL REQUIREMENTS']['2026-01'] == 1200.0 + 400.0 - 180.0
    # Afgeleide/vaste metrics komen er bewust NIET in voor.
    for omitted in ('EBIT', 'GROSS MARGIN', 'COST OF GOODS', 'ROCE'):
        assert omitted not in fin
