"""Materiaalgroepen — /api/material_groups routes (fake callbacks, no fixture)."""

from types import SimpleNamespace

import pytest
from flask import Flask

from ui.routes.material_groups import (
    create_material_groups_blueprint,
    prune_material_from_groups,
)

pytestmark = pytest.mark.no_fixture


@pytest.fixture
def groups_app():
    engine = SimpleNamespace(data=SimpleNamespace(materials={'M1': object(), 'M2': object()}))
    sess = {'id': 's1'}
    holder = {'sess': sess, 'engine': engine}
    calls = {'save': 0}
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(create_material_groups_blueprint(
        lambda: (holder['sess'], holder['engine']),
        lambda: calls.__setitem__('save', calls['save'] + 1),
    ))
    return SimpleNamespace(app=app, client=app.test_client(), sess=sess,
                           holder=holder, calls=calls)


def _create(groups_app, name='Top movers 2026-04 → 2026-06',
            materials=('M1', 'M2', 'GHOST')):
    resp = groups_app.client.post('/api/material_groups',
                                  json={'name': name, 'materials': list(materials),
                                        'source': 'analyse'})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()['group']


def test_create_lists_and_counts_unknown_materials(groups_app):
    group = _create(groups_app)
    body = groups_app.client.get('/api/material_groups').get_json()
    assert [g['id'] for g in body['groups']] == [group['id']]
    assert body['groups'][0]['materials'] == ['M1', 'M2', 'GHOST']
    assert body['unknown_counts'][group['id']] == 1  # GHOST niet in materials
    assert body['active_group_id'] is None
    assert groups_app.calls['save'] == 1


def test_create_dedupes_and_validates(groups_app):
    group = _create(groups_app, materials=('M1', 'M1', ' M2 '))
    assert group['materials'] == ['M1', 'M2']
    assert groups_app.client.post(
        '/api/material_groups', json={'name': '', 'materials': ['M1']}
    ).status_code == 400
    assert groups_app.client.post(
        '/api/material_groups', json={'name': 'X', 'materials': []}
    ).status_code == 400
    assert 'minstens één materiaal' in groups_app.client.post(
        '/api/material_groups', json={'name': 'X', 'materials': ['  ']}
    ).get_json()['error']


def test_rename_and_404(groups_app):
    group = _create(groups_app)
    resp = groups_app.client.patch(f"/api/material_groups/{group['id']}",
                                   json={'name': 'Nieuwe naam'})
    assert resp.status_code == 200
    assert groups_app.sess['material_groups'][group['id']]['name'] == 'Nieuwe naam'
    assert groups_app.client.patch('/api/material_groups/nope',
                                   json={'name': 'X'}).status_code == 404


def test_activate_deactivate_and_delete_active_deactivates(groups_app):
    group = _create(groups_app)
    resp = groups_app.client.post(f"/api/material_groups/{group['id']}/activate")
    assert resp.status_code == 200
    assert resp.get_json()['active_group_id'] == group['id']
    assert groups_app.sess['active_material_group'] == group['id']

    resp = groups_app.client.delete(f"/api/material_groups/{group['id']}")
    assert resp.status_code == 200
    assert resp.get_json()['active_group_id'] is None
    assert groups_app.sess['active_material_group'] is None
    assert groups_app.sess['material_groups'] == {}

    assert groups_app.client.post('/api/material_groups/nope/activate').status_code == 404
    assert groups_app.client.delete('/api/material_groups/nope').status_code == 404

    resp = groups_app.client.post('/api/material_groups/deactivate')
    assert resp.status_code == 200 and resp.get_json()['active_group_id'] is None


def test_no_session_is_400(groups_app):
    groups_app.holder['sess'] = None
    assert groups_app.client.get('/api/material_groups').status_code == 400


def test_prune_material_from_groups():
    sess = {'material_groups': {
        'g1': {'id': 'g1', 'name': 'A', 'materials': ['M1', 'M2']},
        'g2': {'id': 'g2', 'name': 'B', 'materials': ['M2']},
    }}
    prune_material_from_groups(sess, 'M2')
    assert sess['material_groups']['g1']['materials'] == ['M1']
    assert sess['material_groups']['g2']['materials'] == []  # groep blijft bestaan
    prune_material_from_groups({}, 'M1')  # geen groepen: geen crash


def test_groups_round_trip_session_store(tmp_path):
    from ui.session_store import load_sessions_from_disk, save_sessions_to_disk

    groups = {'g1': {'id': 'g1', 'name': 'Top movers', 'materials': ['M1'],
                     'created_at': 'x', 'source': 'analyse'}}
    sessions = {'s1': {'id': 's1', 'engine': None,
                       'material_groups': groups, 'active_material_group': 'g1',
                       'parameters': {'planning_month': '2025-12'}}}
    store = tmp_path / 'sessions_store.json'
    save_sessions_to_disk(sessions, 's1', store, lambda s, e: {})
    loaded, _ = load_sessions_from_disk(store)
    assert loaded['s1']['material_groups'] == groups
    assert loaded['s1']['active_material_group'] == 'g1'

    # Oude store-files zonder de velden: veilige defaults.
    import json
    payload = json.loads(store.read_text(encoding='utf-8'))
    payload['sessions']['s1'].pop('material_groups')
    payload['sessions']['s1'].pop('active_material_group')
    store.write_text(json.dumps(payload), encoding='utf-8')
    loaded, _ = load_sessions_from_disk(store)
    assert loaded['s1']['material_groups'] == {}
    assert loaded['s1']['active_material_group'] is None
