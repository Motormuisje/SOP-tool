"""Masterdata-routes + werkboek-vrije upload/calculate-flow."""

import json
from types import SimpleNamespace

import pytest
from flask import Flask

from modules.master_data import serialize_master
from tests.master_fixtures import fake_master_loader, write_extract_files
from ui import master_store
from ui.routes.master_data import create_master_data_blueprint

pytestmark = pytest.mark.no_fixture


@pytest.fixture
def store_env(tmp_path):
    """Eigen store-pad per test; module-global netjes herstellen."""
    previous = master_store.get_store_path()
    path = tmp_path / 'master_store.json'
    master_store.set_store_path(path)
    yield SimpleNamespace(path=path, tmp=tmp_path)
    master_store.set_store_path(previous) if previous else master_store.set_store_path(path)


def _seed_store(store_env):
    master = json.loads(json.dumps(serialize_master(fake_master_loader()), default=str))
    master_store.save_master_store(store_env.path, master, source_filename='seed.xlsm')
    master_store.set_store_path(store_env.path)  # cache verversen
    return master


@pytest.fixture
def md_app(store_env):
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(create_master_data_blueprint(
        {}, lambda: store_env.tmp / 'uploads'))
    return SimpleNamespace(app=app, client=app.test_client(), store=store_env)


def test_status_reports_absence_and_presence(md_app):
    assert md_app.client.get('/api/master_data').get_json() == {'exists': False}
    _seed_store(md_app.store)
    body = md_app.client.get('/api/master_data').get_json()
    assert body['exists'] and body['version'] == 1
    assert body['counts']['materials'] == 2 and body['counts']['machines'] == 1


def test_get_dataset_and_unknown(md_app):
    assert md_app.client.get('/api/master_data/materials').status_code == 400  # geen store
    _seed_store(md_app.store)
    body = md_app.client.get('/api/master_data/materials').get_json()
    assert [m['material_number'] for m in body['value']] == ['M1', 'M2']
    assert md_app.client.get('/api/master_data/nonsense').status_code == 404


def test_patch_validates_by_hydration_and_bumps_version(md_app):
    master = _seed_store(md_app.store)

    # Geldige bewerking: naam aanpassen.
    materials = [dict(m) for m in master['materials']]
    materials[0]['name'] = 'Parent (hernoemd)'
    resp = md_app.client.patch('/api/master_data/materials',
                               json={'value': materials})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['version'] == 2 and body['requires_recalculate'] is True
    stored = master_store.load_master_store(md_app.store.path)
    assert stored['master']['materials'][0]['name'] == 'Parent (hernoemd)'
    assert stored['edited_at'] and stored['source_filename'] == 'seed.xlsm'

    # Verkeerd type → 400; hydratie-fout (kapot record) → 400 met reden.
    assert md_app.client.patch('/api/master_data/materials',
                               json={'value': {'nope': 1}}).status_code == 400
    broken = [dict(materials[0])]
    broken[0].pop('product_type')
    resp = md_app.client.patch('/api/master_data/materials', json={'value': broken})
    assert resp.status_code == 400
    assert 'Wijziging geweigerd' in resp.get_json()['error']
    # Mislukte patch mag de versie niet ophogen.
    assert master_store.load_master_store(md_app.store.path)['version'] == 2


def test_import_requires_source_and_confirm_flow(md_app, tmp_path):
    # Geen upload en geen geconfigureerd master_file → 400.
    resp = md_app.client.post('/api/master_data/import', data={})
    assert resp.status_code == 400
    assert 'Geen bronbestand' in resp.get_json()['error']


def test_workbook_free_upload_and_calculate(flask_test_app, store_env, tmp_path):
    """Multi-upload zonder basisbestand: master-store + 4 extracts → sessie
    zonder file_path; /api/calculate rekent vanuit de store."""
    _seed_store(store_env)
    extracts = write_extract_files(tmp_path)

    files = {}
    for form_key, dict_key in [('bom_file', 'bom'), ('routing_file', 'routing'),
                               ('stock_file', 'stock'), ('forecast_file', 'forecast')]:
        files[form_key] = (open(extracts[dict_key], 'rb'),
                          f'{dict_key}_extract.xlsx')
    resp = flask_test_app.client.post(
        '/api/upload', data={**files, 'custom_name': 'Werkboek-vrij'},
        content_type='multipart/form-data')
    body = resp.get_json()
    assert resp.status_code == 200 and body.get('success'), body
    session_id = body['session_id']
    sess = flask_test_app.sessions[session_id]
    assert sess['file_path'] == ''  # geen basiswerkboek
    assert set(sess['extract_files']) == {'bom', 'routing', 'stock', 'forecast'}

    calc = flask_test_app.client.post('/api/calculate', json={
        'planning_month': None, 'months_actuals': 1, 'months_forecast': 3})
    calc_body = calc.get_json()
    assert calc.status_code == 200 and calc_body.get('success'), calc_body
    engine = sess['engine']
    assert engine is not None
    assert engine.data.periods == ['2026-01', '2026-02', '2026-03']
    assert 'M1' in engine.data.materials and 'PBA01' in engine.data.machines
