"""Materiaalgroepen — gescoopte read-endpoints op de golden fixture.

Parity eerst: zonder actieve groep zijn de payloads byte-identiek aan de
ongescoopte route (geen 'scoped'-sleutel). Met actieve groep: trends zijn
exact de som van de groepsrijen, de financiële blok bevat uitsluitend de
eerlijke metrics + BIJDRAGEMARGE, en bezetting is het groepsaandeel (nooit
boven de volledige benutting). Machine-eigenschappen blijven de hele machine.
"""

from types import SimpleNamespace

import pytest
from flask import Flask

from modules.models import LineType
from ui.routes.machines import create_machines_blueprint
from ui.routes.read import create_read_blueprint

GROUP_ID = 'g-test'


@pytest.fixture()
def scoped_app(planning_engine_result):
    sess = {'id': 's', 'engine': planning_engine_result,
            'machine_undo': [], 'machine_redo': []}
    holder = {'sess': sess}

    def get_active():
        return holder['sess'], planning_engine_result

    def crash(*args, **kwargs):
        raise RuntimeError('unexpected callback')

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(create_read_blueprint(
        get_active, lambda row: row.to_dict(), lambda engine: {}))
    app.register_blueprint(create_machines_blueprint(
        get_active, lambda s, e: {}, lambda machine, data: 500.0,
        crash, crash, lambda e: {}, lambda: None))
    return SimpleNamespace(app=app, client=app.test_client(), sess=sess,
                           engine=planning_engine_result)


def _pick_group_materials(engine, count=3):
    mats = []
    for row in engine.results.get(LineType.TOTAL_DEMAND.value, []):
        if sum(row.values.values()) > 0:
            mats.append(str(row.material_number))
        if len(mats) == count:
            break
    assert len(mats) == count, 'fixture heeft te weinig vraagmaterialen'
    return mats


def _activate(sess, materials):
    sess['material_groups'] = {GROUP_ID: {
        'id': GROUP_ID, 'name': 'Testgroep', 'materials': list(materials),
        'created_at': 'x', 'source': 'test'}}
    sess['active_material_group'] = GROUP_ID


def test_dashboard_parity_without_active_group(scoped_app):
    base = scoped_app.client.get('/api/dashboard').get_json()
    assert 'scoped' not in base

    mats = _pick_group_materials(scoped_app.engine)
    _activate(scoped_app.sess, mats)
    scoped = scoped_app.client.get('/api/dashboard').get_json()
    assert 'scoped' in scoped

    scoped_app.sess['active_material_group'] = None
    after = scoped_app.client.get('/api/dashboard').get_json()
    assert after == base, 'deactiveren moet de payload exact herstellen'


def test_dashboard_scoped_trends_and_financials(scoped_app):
    engine = scoped_app.engine
    mats = _pick_group_materials(engine)
    _activate(scoped_app.sess, mats)
    payload = scoped_app.client.get('/api/dashboard').get_json()

    # Trends: exact dezelfde accumulate-and-round als de route, over de groep.
    expected = {}
    for row in engine.results.get(LineType.TOTAL_DEMAND.value, []):
        if str(row.material_number) not in set(mats):
            continue
        for period in engine.data.periods:
            expected[period] = round(
                expected.get(period, 0.0) + row.values.get(period, 0.0), 1)
    assert payload['demand_trend'] == expected
    assert sum(expected.values()) > 0

    fin = payload['financials']
    assert 'BIJDRAGEMARGE' in fin
    for omitted in ('EBIT', 'ROCE', 'GROSS MARGIN', 'EBITDA', 'COST OF GOODS',
                    'OPERATIONAL CASHFLOW', 'CAPITAL INVESTMENT'):
        assert omitted not in fin, omitted
    marker = payload['scoped']
    assert marker['name'] == 'Testgroep' and marker['materials'] == 3
    assert marker['fte_scopable'] is False and 'EBIT' in marker['omitted']

    # IQ: alleen groepsmaterialen.
    iq_mats = {m['material_number'] for m in payload['inventory_quality']}
    assert iq_mats <= set(mats)
    assert {m['material_number'] for m in payload['top_10_overstocks']} <= set(mats)
    assert payload['kpis']['materials'] == 3


def test_dashboard_scoped_utilization_is_share(scoped_app):
    base = scoped_app.client.get('/api/dashboard').get_json()
    mats = _pick_group_materials(scoped_app.engine)
    _activate(scoped_app.sess, mats)
    scoped = scoped_app.client.get('/api/dashboard').get_json()

    full_by_machine = {entry['machine']: entry['values']
                       for entry in base['utilization_by_machine']}
    for entry in scoped['utilization_by_machine']:
        full = full_by_machine[entry['machine']]
        for period, value in entry['values'].items():
            assert value <= full[period] + 1e-6, (entry['machine'], period)


def test_machines_scoped_hours_capacity_untouched(scoped_app):
    base = scoped_app.client.get('/api/machines').get_json()
    mats = _pick_group_materials(scoped_app.engine)
    _activate(scoped_app.sess, mats)
    scoped = scoped_app.client.get('/api/machines').get_json()

    assert 'scoped' in scoped and 'scoped' not in base
    base_by_code = {m['code']: m for m in base['machines']}
    group_hours_total = 0.0
    for machine in scoped['machines']:
        full = base_by_code[machine['code']]
        # Machine-eigenschappen blijven de hele machine.
        assert machine['oee'] == full['oee']
        assert machine['shift_hours'] == full['shift_hours']
        assert machine['availability_by_period'] == full['availability_by_period']
        assert machine['capacity_hours_by_period'] == full['capacity_hours_by_period']
        # Groepsuren/utilization zijn een deel van het geheel.
        for period, hours in machine['req_hours_by_period'].items():
            assert hours <= full['req_hours_by_period'][period] + 0.05
            group_hours_total += hours
        for period, util in machine['util_by_period'].items():
            assert util <= full['util_by_period'][period] + 0.11
    assert group_hours_total >= 0.0


def test_machine_products_scoped_to_group(scoped_app):
    mats = _pick_group_materials(scoped_app.engine)
    base = None
    # Vind een machine met producten in de volledige weergave.
    machines = scoped_app.client.get('/api/machines').get_json()['machines']
    for machine in machines:
        body = scoped_app.client.get(
            f"/api/machines/{machine['code']}/products").get_json()
        if body['products']:
            base = (machine['code'], body)
            break
    assert base, 'geen machine met producten in de fixture'

    _activate(scoped_app.sess, mats)
    scoped = scoped_app.client.get(f'/api/machines/{base[0]}/products').get_json()
    assert 'scoped' in scoped
    assert {p['material_number'] for p in scoped['products']} <= set(mats)


def test_value_results_scoped_consolidation_block(scoped_app):
    base = scoped_app.client.get('/api/value_results').get_json()
    assert 'scoped_consolidation' not in base and 'scoped' not in base

    mats = _pick_group_materials(scoped_app.engine)
    _activate(scoped_app.sess, mats)
    scoped = scoped_app.client.get('/api/value_results').get_json()
    block = scoped['scoped_consolidation']
    assert 'BIJDRAGEMARGE' in block and 'TURNOVER' in block
    assert 'EBIT' not in block
    # Volledige consolidatie blijft onaangeroerd meekomen.
    assert scoped['consolidation'] == base['consolidation']
