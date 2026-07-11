"""Fase 3 — /api/products/added routes (fake engine + callbacks, no fixture)."""

from types import SimpleNamespace

import pytest
from flask import Flask

from modules.models import Machine, Material, ProductType
from ui.routes.products import create_products_blueprint, prune_material_state

pytestmark = pytest.mark.no_fixture

MN = '900000001'
PRODUCT = {'material_number': MN, 'name': 'Test', 'product_type': 'bulk',
           'flat_volume': 100.0}


def _data():
    return SimpleNamespace(
        materials={'M1': Material(material_number='M1', name='Bestaand',
                                  product_type=ProductType.BULK_PRODUCT,
                                  product_family='F')},
        bom=[],
        machines={'PBA01': Machine(machine_id='PBA01', machine_code='PBA01',
                                   name='Press', oee=0.8)},
        periods=['2026-01', '2026-02'],
    )


@pytest.fixture
def products_app():
    engine = SimpleNamespace(data=_data(), results={}, config_overrides={})
    sess = {
        'id': 's1', 'engine': engine, 'added_products': [],
        'pending_edits': {}, 'value_aux_overrides': {},
        'inventory_overrides': {}, 'capacity_overrides': {},
        'undo_stack': [], 'redo_stack': [],
    }
    holder = {'sess': sess, 'engine': engine}
    global_config = {}
    calls = {'build': 0, 'install': 0, 'replay': 0,
             'save_global': 0, 'save_sessions': 0}
    behaviour = {'build_raises': None}

    def fake_build(s, params=None):
        calls['build'] += 1
        if behaviour['build_raises'] is not None:
            raise behaviour['build_raises']
        return SimpleNamespace(
            data=_data(), results={},
            config_overrides={'added_products': list(s.get('added_products') or [])},
        )

    def fake_install(s, engine, clear_machine_overrides=True):
        calls['install'] += 1

    def fake_replay(s, engine):
        calls['replay'] += 1

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(create_products_blueprint(
        lambda: (holder['sess'], holder['engine']),
        global_config,
        lambda: calls.__setitem__('save_global', calls['save_global'] + 1),
        lambda: calls.__setitem__('save_sessions', calls['save_sessions'] + 1),
        fake_build,
        fake_install,
        fake_replay,
        lambda engine: {},
        lambda engine: {'value_results': {}, 'consolidation': []},
    ))
    return SimpleNamespace(app=app, sess=sess, holder=holder,
                           global_config=global_config, calls=calls,
                           behaviour=behaviour)


# ------------------------------------------------------------------ GET

def test_get_requires_engine(products_app):
    products_app.holder['engine'] = None
    resp = products_app.app.test_client().get('/api/products/added')
    assert resp.status_code == 400
    assert 'berekening' in resp.get_json()['error']


def test_get_returns_lists_for_datalists(products_app):
    products_app.sess['added_products'] = [dict(PRODUCT)]
    body = products_app.app.test_client().get('/api/products/added').get_json()
    assert body['added_products'] == [PRODUCT]
    assert body['machines'] == ['PBA01']
    assert body['materials'] == [{'number': 'M1', 'name': 'Bestaand'}]
    assert body['periods'] == ['2026-01', '2026-02']


# ----------------------------------------------------------------- POST

def test_post_happy_path_rebuilds_and_saves(products_app):
    resp = products_app.app.test_client().post('/api/products/added', json=PRODUCT)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['added_products'][0]['material_number'] == MN
    assert 'results' in body and 'periods' in body and 'value_results' in body
    assert products_app.sess['added_products'][0]['material_number'] == MN
    assert products_app.global_config['added_products'][0]['material_number'] == MN
    assert products_app.calls['build'] == 1
    assert products_app.calls['install'] == 1
    assert products_app.calls['replay'] == 1
    assert products_app.calls['save_global'] == 1
    assert products_app.calls['save_sessions'] == 1
    # The rebuilt engine was installed on the session.
    assert products_app.sess['engine'].config_overrides['added_products']


def test_post_upsert_replaces_by_number(products_app):
    client = products_app.app.test_client()
    client.post('/api/products/added', json=PRODUCT)
    client.post('/api/products/added', json=dict(PRODUCT, name='Nieuwe naam'))
    assert len(products_app.sess['added_products']) == 1
    assert products_app.sess['added_products'][0]['name'] == 'Nieuwe naam'


def test_post_validation_error_is_400_without_rebuild(products_app):
    client = products_app.app.test_client()
    for payload, msg in [
        (dict(PRODUCT, material_number='M1'), 'bestaat al'),
        (dict(PRODUCT, name=''), 'Productnaam'),
        (dict(PRODUCT, routing=[{'work_center': 'NOPE', 'base_quantity': 1,
                                 'standard_time': 1}]), 'bestaat niet'),
    ]:
        resp = client.post('/api/products/added', json=payload)
        assert resp.status_code == 400, payload
        assert msg in resp.get_json()['error']
    assert products_app.calls['build'] == 0
    assert products_app.sess['added_products'] == []


def test_post_rolls_back_when_rebuild_rejects_overlay(products_app):
    products_app.behaviour['build_raises'] = ValueError('BOM-cyclus: A → B → A')
    resp = products_app.app.test_client().post('/api/products/added', json=PRODUCT)
    assert resp.status_code == 400
    assert 'BOM-cyclus' in resp.get_json()['error']
    assert products_app.sess['added_products'] == []
    assert products_app.global_config['added_products'] == []
    assert products_app.calls['save_sessions'] == 0


# --------------------------------------------------------------- DELETE

def test_delete_unknown_is_404(products_app):
    resp = products_app.app.test_client().delete('/api/products/added/999')
    assert resp.status_code == 404


def test_delete_removes_and_prunes_material_state(products_app):
    client = products_app.app.test_client()
    client.post('/api/products/added', json=PRODUCT)
    sess = products_app.sess
    sess['pending_edits'] = {
        f'01. Demand forecast||{MN}||123||2026-01': {'new_value': 5},
        f'02. Dependent demand||M1||{MN}||2026-01': {'new_value': 6},
        '01. Demand forecast||M1||1||2026-01': {'new_value': 7},
    }
    sess['value_aux_overrides'] = {
        f'01. Demand forecast||{MN}': {'new_value': 1},
        '01. Demand forecast||M1': {'new_value': 2},
    }
    sess['inventory_overrides'] = {MN: 10.0, 'M1': 20.0}
    sess['capacity_overrides'] = {'07. Purchase plan': {MN: {'2026-01': 1.0},
                                                        'M1': {'2026-01': 2.0}}}
    sess['undo_stack'] = [{'material_number': MN}]
    sess['redo_stack'] = [{'material_number': MN}]

    resp = client.delete(f'/api/products/added/{MN}')
    assert resp.status_code == 200
    assert products_app.sess['added_products'] == []
    assert products_app.global_config['added_products'] == []
    # Only the unrelated M1 state survives.
    assert list(sess['pending_edits']) == ['01. Demand forecast||M1||1||2026-01']
    assert list(sess['value_aux_overrides']) == ['01. Demand forecast||M1']
    assert MN not in sess['inventory_overrides']
    assert MN not in sess['capacity_overrides']['07. Purchase plan']
    assert sess['undo_stack'] == [] and sess['redo_stack'] == []


def test_prune_material_state_helper_tolerates_missing_keys():
    sess = {}
    prune_material_state(sess, MN)
    assert sess['pending_edits'] == {}
    assert sess['undo_stack'] == [] and sess['redo_stack'] == []
