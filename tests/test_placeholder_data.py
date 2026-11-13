"""Aannames voor ontbrekende omsteltijden (modules/placeholder_data.py).

De klant levert omsteltijden later aan. De tool vult ze tot dan met een
aanname uit een vaste regel. Wat hier vastligt: alleen gaten worden gevuld,
een aanname blijft herkenbaar tot iemand haar wijzigt of bevestigt, en
verwijderen raakt nooit een aangepaste, bevestigde of klantwaarde.
"""

import copy
import json
from types import SimpleNamespace

import pytest
from flask import Flask

from modules.master_data import hydrate_loader, serialize_master
from modules.placeholder_data import (
    CHANGEOVER_RULESET,
    apply_placeholders,
    changeover_placeholders,
    changeover_rule_for,
    confirm_placeholders,
    origin_state,
    placeholder_status,
    remove_placeholders,
)
from tests.master_fixtures import fake_master_loader
from ui import master_store
from ui.routes.machine_inzet import create_machine_inzet_blueprint

pytestmark = pytest.mark.no_fixture


def _master(machines=('PML01', 'PBA07', 'PSS13', 'PWP01', 'PPM08', 'XYZ01', 'PBA99'),
            existing=None, site='NLX1'):
    return {
        'config': {'site': site, 'unlimited_capacity_machine': ['PBA99']},
        'machines': [{'machine_code': code} for code in machines],
        'changeover_times': copy.deepcopy(existing or {}),
    }


class TestGenerator:
    def test_rule_per_machine_type(self):
        assert changeover_rule_for('PML01') == (2.0, 'maalinstallatie')
        assert changeover_rule_for('pba07') == (0.5, 'afvulmachine')
        assert changeover_rule_for('XYZ01') == (1.0, 'overige installatie')

    def test_only_machines_without_a_record_and_not_virtual(self):
        master = _master(existing={'PML01': {'machine_code': 'PML01', 'hours_per_changeover': 3.0}})

        added = changeover_placeholders(master)

        assert set(added) == {'PBA07', 'PSS13', 'PWP01', 'PPM08', 'XYZ01'}
        assert 'PML01' not in added          # klantwaarde bestaat al
        assert 'PBA99' not in added          # virtuele installatie, onbeperkte capaciteit
        rec = added['PBA07']
        assert rec['hours_per_changeover'] == 0.5
        assert rec['origin'] == 'aanname' and rec['origin_value'] == 0.5
        assert rec['origin_rule'] == CHANGEOVER_RULESET
        assert rec['cost_per_hour'] is None  # terugval op het machinetarief
        assert rec['description'].startswith('Aanname')

    def test_deterministic_and_idempotent(self):
        master = _master()
        first, keys1 = apply_placeholders(master)
        second, keys2 = apply_placeholders(first)

        assert keys1 and keys2 == []
        assert changeover_placeholders(master) == changeover_placeholders(_master())
        assert master['changeover_times'] == {}   # invoer niet gemuteerd


class TestHerkomst:
    def _applied(self):
        master, _ = apply_placeholders(_master(
            existing={'PML01': {'machine_code': 'PML01', 'hours_per_changeover': 3.0}}))
        return master

    def test_states(self):
        master = self._applied()
        ct = master['changeover_times']
        ct['PSS13']['hours_per_changeover'] = 1.5           # aangepast
        ct['PWP01']['cost_per_hour'] = 80.0                 # tarief aangevuld

        assert origin_state(ct['PML01']) == ''
        assert origin_state(ct['PBA07']) == 'aanname'
        assert origin_state(ct['PSS13']) == 'aangepast'
        assert origin_state(ct['PWP01']) == 'aangepast'

    def test_remove_takes_only_unchanged_assumptions(self):
        master = self._applied()
        master['changeover_times']['PSS13']['hours_per_changeover'] = 1.5
        master, _ = confirm_placeholders(master, ['PPM08'])

        cleaned, removed = remove_placeholders(master)

        assert removed == ['PBA07', 'PWP01', 'XYZ01']
        assert set(cleaned['changeover_times']) == {'PML01', 'PSS13', 'PPM08'}
        assert cleaned['changeover_times']['PSS13']['hours_per_changeover'] == 1.5

    def test_confirm_is_sticky(self):
        master, confirmed = confirm_placeholders(self._applied())

        assert confirmed == ['PBA07', 'PPM08', 'PSS13', 'PWP01', 'XYZ01']
        assert all(origin_state(r) == 'bevestigd' for k, r in master['changeover_times'].items() if k != 'PML01')
        assert remove_placeholders(master)[1] == []

    def test_status_counts(self):
        master = self._applied()
        master['changeover_times']['PSS13']['hours_per_changeover'] = 1.5
        st = placeholder_status(master)

        assert st['would_add'] == []
        assert st['assumed'] == ['PBA07', 'PPM08', 'PWP01', 'XYZ01']
        assert st['adjusted'] == ['PSS13']
        assert st['client'] == ['PML01']

    def test_origin_fields_survive_hydration_and_serialisation(self):
        """The provenance travels with the record through the store
        round-trip; otherwise every assumption would turn into client data."""
        master = json.loads(json.dumps(serialize_master(fake_master_loader()), default=str))
        master, added = apply_placeholders(master)
        assert added

        again = json.loads(json.dumps(serialize_master(_hydrated(master)), default=str))

        for code in added:
            rec = again['changeover_times'][code]
            assert rec['origin'] == 'aanname'
            assert rec['origin_value'] == rec['hours_per_changeover']
            assert origin_state(rec) == 'aanname'


def _hydrated(master):
    from modules.data_loader import DataLoader
    loader = DataLoader(None, config_overrides={}, master_data=master)
    hydrate_loader(loader, master)
    return loader


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@pytest.fixture
def ph_app(tmp_path):
    previous = master_store.get_store_path()
    path = tmp_path / 'master_store.json'
    master_store.set_store_path(path)
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(create_machine_inzet_blueprint(lambda: (None, None), lambda: None))

    def seed(site='NLX1'):
        master = json.loads(json.dumps(serialize_master(fake_master_loader()), default=str))
        master['config']['site'] = site
        master_store.save_master_store(path, master, source_filename='seed.xlsm')
        master_store.set_store_path(path)
        return master

    yield SimpleNamespace(client=app.test_client(), seed=seed)
    if previous is not None:
        master_store.set_store_path(previous)


def test_route_preview_apply_confirm_remove(ph_app):
    ph_app.seed()
    status = ph_app.client.get('/api/machine_inzet/placeholders').get_json()
    assert status['would_add'], status
    version = status['version']

    applied = ph_app.client.post('/api/machine_inzet/placeholders',
                                 json={'action': 'apply', 'base_version': version}).get_json()
    assert applied['success'] and applied['changed'] == status['would_add']
    assert applied['version'] == version + 1
    assert applied['would_add'] == [] and applied['assumed'] == status['would_add']
    stored = master_store.get_current_master_record()['master']['changeover_times']
    assert all(stored[k]['origin'] == 'aanname' for k in applied['changed'])

    removed = ph_app.client.post('/api/machine_inzet/placeholders',
                                 json={'action': 'remove', 'base_version': applied['version']}).get_json()
    assert removed['changed'] == applied['changed']
    assert removed['would_add'] == status['would_add']


def test_route_refuses_a_stale_version_and_changes_nothing(ph_app):
    ph_app.seed()
    version = ph_app.client.get('/api/machine_inzet/placeholders').get_json()['version']

    response = ph_app.client.post('/api/machine_inzet/placeholders',
                                  json={'action': 'apply', 'base_version': version - 1})

    assert response.status_code == 409
    assert master_store.get_current_master_record()['version'] == version


def test_route_requires_a_base_version_and_a_known_action(ph_app):
    ph_app.seed()
    version = ph_app.client.get('/api/machine_inzet/placeholders').get_json()['version']

    assert ph_app.client.post('/api/machine_inzet/placeholders',
                              json={'action': 'apply'}).status_code == 400
    assert ph_app.client.post('/api/machine_inzet/placeholders',
                              json={'action': 'wipe', 'base_version': version}).status_code == 400


@pytest.mark.parametrize('site', ['NLK1', 'NLU1', ''])
def test_route_refuses_other_sites(ph_app, site):
    """Machine-inzet is alleen aan Maastricht verkocht: de route weigert zelf,
    ook als de UI er per ongeluk een knop voor toont."""
    ph_app.seed(site=site)

    assert ph_app.client.get('/api/machine_inzet/placeholders').status_code == 403
    response = ph_app.client.post('/api/machine_inzet/placeholders',
                                  json={'action': 'apply', 'base_version': 1})
    assert response.status_code == 403
    assert master_store.get_current_master_record()['version'] == 1


class TestRandgevallen:
    def test_non_finite_values_never_count_as_unchanged(self):
        master, _ = apply_placeholders(_master())
        for bad in (float('nan'), float('inf'), None, 'abc'):
            rec = dict(master['changeover_times']['PBA07'], hours_per_changeover=bad)
            assert origin_state(rec) == 'aangepast', bad
        rec = dict(master['changeover_times']['PBA07'], origin_value=float('nan'))
        assert origin_state(rec) == 'aangepast'

    def test_state_follows_the_current_value_not_the_edit_history(self):
        """Documented behaviour: change and restore = an unchanged assumption
        again, and therefore removable again."""
        master, _ = apply_placeholders(_master())
        rec = master['changeover_times']['PBA07']
        rec['hours_per_changeover'] = 2.0
        assert origin_state(rec) == 'aangepast'
        rec['hours_per_changeover'] = 0.5
        assert origin_state(rec) == 'aanname'
        assert 'PBA07' in remove_placeholders(master)[1]

    def test_confirmed_description_names_the_original_assumption(self):
        master, _ = confirm_placeholders(apply_placeholders(_master())[0], ['PML01'])
        desc = master['changeover_times']['PML01']['description']
        assert desc.startswith('Aanname') and 'oorspronkelijk 2 u' in desc and 'bevestigd' in desc


def test_provenance_survives_the_master_workbook(tmp_path):
    """Export to SOP_Masterdata_<site>.xlsx and parse it back: origin,
    origin_rule and origin_value come back unchanged, so an assumption edited
    in Excel is still recognisable as one."""
    from modules.master_workbook import export_master_workbook, parse_master_workbook

    master = json.loads(json.dumps(serialize_master(fake_master_loader()), default=str))
    master, added = apply_placeholders(master)
    master, _ = confirm_placeholders(master, added[:1])
    path = tmp_path / 'SOP_Masterdata_NLX1.xlsx'
    export_master_workbook(master, path, site='NLX1', store_version=3)

    parsed, _meta = parse_master_workbook(path)

    for code in added:
        before, after = master['changeover_times'][code], parsed['changeover_times'][code]
        for field in ('origin', 'origin_rule', 'origin_value', 'hours_per_changeover'):
            assert after[field] == before[field], (code, field)
        assert origin_state(after) == origin_state(before)


def test_two_simultaneous_saves_on_one_version_only_one_wins(ph_app):
    """Two tabs both press 'apply' on the version they loaded. The second
    must get a 409 and change nothing, not add the records a second time on
    top of a newer store."""
    ph_app.seed()
    version = ph_app.client.get('/api/machine_inzet/placeholders').get_json()['version']

    first = ph_app.client.post('/api/machine_inzet/placeholders',
                               json={'action': 'apply', 'base_version': version})
    second = ph_app.client.post('/api/machine_inzet/placeholders',
                                json={'action': 'confirm', 'base_version': version})

    assert first.status_code == 200 and second.status_code == 409
    record = master_store.get_current_master_record()
    assert record['version'] == version + 1
    assert all(origin_state(r) == 'aanname'
               for r in record['master']['changeover_times'].values() if r.get('origin'))
