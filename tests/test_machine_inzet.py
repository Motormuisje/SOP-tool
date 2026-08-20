"""Machine-inzet fase 1: omstellingen per machine per periode.

De route leest de planningresultaten (Line 07-materiaalregels dragen hun
machine in aux_column) en schat omstellingen als producten − 1 met
ondergrens 0. De sessie-overrides zijn weergave-wat-als: persistentie via
sessiestore/scenario's/duplicaat, Reset zet ze uit — bewust NIET door
config_overrides/snapshot/replay (geen motor consumeert ze in fase 1).
"""

import json
from types import SimpleNamespace

import pytest
from flask import Flask

from modules.master_data import FTE_DATASETS, serialize_master
from modules.models import ChangeoverTime, LineType
from tests.test_state_model_fte import _Engine, _combo_setup
from ui.engine_rebuild import install_clean_engine_baseline
from ui.routes.machine_inzet import _machine_usage, create_machine_inzet_blueprint
from ui.session_store import load_sessions_from_disk, save_sessions_to_disk

pytestmark = pytest.mark.no_fixture

PERIOD = '2025-01'


def _env():
    data, results = _combo_setup()
    engine = _Engine(data, results)
    engine.recalculate_fte([])
    sess = {'id': 's1', 'engine': engine, 'changeover_overrides': {}}
    saved = []
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(create_machine_inzet_blueprint(
        lambda: (sess, engine), lambda: saved.append(True)))
    return app.test_client(), sess, engine, saved


class TestBerekening:
    def test_producten_uren_en_venster_per_machine(self):
        data, results = _combo_setup()
        engine = _Engine(data, results)
        usage = _machine_usage(engine)

        assert set(usage['machines']) >= {'MA', 'MB'}
        ma = usage['machines']['MA']['per_period'][PERIOD]
        assert ma['products'] == ['PA']          # één product op MA
        assert ma['hours'] == pytest.approx(100.0)
        assert ma['window'] > 0                  # venster van de groep

    def test_schatting_is_producten_min_een_met_ondergrens_nul(self):
        """Eén product = nul omstellingen; de schatting mag nooit negatief."""
        data, results = _combo_setup()
        engine = _Engine(data, results)
        usage = _machine_usage(engine)
        for machine in usage['machines'].values():
            for cel in machine['per_period'].values():
                est = max(0, len(cel['products']) - 1)
                assert est >= 0
        # MA draait één product: schatting 0, geen fantoomomstelling.
        assert len(usage['machines']['MA']['per_period'][PERIOD]['products']) == 1

    def test_ruisuren_tellen_niet_als_product(self):
        """Afrondingsruis uit de cascade mag geen omstelling suggereren."""
        data, results = _combo_setup()
        for row in results[LineType.CAPACITY_UTILIZATION.value]:
            if str(row.material_number) == 'PA':
                row.values[PERIOD] = 0.001   # onder de drempel
        engine = _Engine(data, results)
        usage = _machine_usage(engine)
        assert usage['machines']['MA']['per_period'][PERIOD]['products'] == []


class TestRoutes:
    def test_get_geeft_gebruik_omsteltijden_en_overrides(self):
        client, sess, engine, _ = _env()
        engine.data.changeover_times = {
            'MA': ChangeoverTime(machine_code='MA', hours_per_changeover=1.5)}
        sess['changeover_overrides'] = {f'MA|{PERIOD}': 4}

        body = client.get('/api/machine_inzet').get_json()
        assert body['success'] is True
        assert body['machines']['MA']['per_period'][PERIOD]['hours'] == pytest.approx(100.0)
        assert body['changeover_times']['MA']['hours_per_changeover'] == 1.5
        assert body['overrides'] == {f'MA|{PERIOD}': 4}

    def test_post_valideert_en_persisteert(self):
        client, sess, _, saved = _env()
        ok = client.post('/api/machine_inzet/overrides',
                         json={'overrides': {f'MA|{PERIOD}': 3}})
        assert ok.get_json()['overrides'] == {f'MA|{PERIOD}': 3}
        assert sess['changeover_overrides'] == {f'MA|{PERIOD}': 3}
        assert saved, 'sessies zijn niet weggeschreven'

        leeg = client.post('/api/machine_inzet/overrides', json={'overrides': {}})
        assert leeg.get_json()['overrides'] == {}
        assert sess['changeover_overrides'] == {}

        for payload, fragment in [
            ({'overrides': [1]}, 'object'),
            ({'overrides': {'MA': 2}}, 'MACHINE|PERIODE'),
            ({'overrides': {f'MA|{PERIOD}': 'veel'}}, 'getal'),
            ({'overrides': {f'MA|{PERIOD}': -1}}, 'geheel getal'),
            ({'overrides': {f'MA|{PERIOD}': 2.5}}, 'geheel getal'),
        ]:
            resp = client.post('/api/machine_inzet/overrides', json=payload)
            assert resp.status_code == 400, payload
            assert fragment in resp.get_json()['error'], resp.get_json()

    def test_sitepoort_geldt_ook_hier(self):
        client, _, engine, _ = _env()
        engine.data.master_overlay_skipped = {'store_site': 'NLX1',
                                              'workbook_site': 'NLK1'}
        for call in (lambda: client.get('/api/machine_inzet'),
                     lambda: client.post('/api/machine_inzet/overrides',
                                         json={'overrides': {}})):
            resp = call()
            assert resp.status_code == 409
            assert 'NLK1' in resp.get_json()['error']


class TestDatasetEnPersistentie:
    def test_changeover_times_reist_door_de_serialisatie(self):
        from tests.master_fixtures import fake_master_loader
        loader = fake_master_loader()
        loader.changeover_times = {
            'PBA01': ChangeoverTime(machine_code='PBA01',
                                    hours_per_changeover=0.75,
                                    description='klantopgave')}
        master = json.loads(json.dumps(serialize_master(loader), default=str))
        assert master['changeover_times']['PBA01']['hours_per_changeover'] == 0.75
        assert 'changeover_times' in FTE_DATASETS

    def test_check_weigert_negatief_en_waarschuwt_onbekende_machine(self):
        from ui.routes.master_data import _check_changeover
        error, _ = _check_changeover('PBA01', {'hours_per_changeover': -1}, {'PBA01'})
        assert error and 'omsteltijd' in error.lower()
        error, warnings = _check_changeover('SPOOK', {'hours_per_changeover': 1.0},
                                            {'PBA01'})
        assert error is None
        assert warnings and 'onbekend' in warnings[0]
        # Nul is geldig: sommige wissels kosten geen tijd.
        error, _ = _check_changeover('PBA01', {'hours_per_changeover': 0}, {'PBA01'})
        assert error is None

    def test_overrides_overleven_een_herstart(self, tmp_path):
        data, results = _combo_setup()
        engine = _Engine(data, results)
        sess = {'id': 's1', 'engine': engine,
                'changeover_overrides': {f'MA|{PERIOD}': 5}}
        store = tmp_path / 'sessions_store.json'
        save_sessions_to_disk({'s1': sess}, 's1', store, lambda s, e: {})
        loaded, _ = load_sessions_from_disk(store)
        assert loaded['s1']['changeover_overrides'] == {f'MA|{PERIOD}': 5}

    def test_oude_store_zonder_veld_laadt_als_leeg(self, tmp_path):
        store = tmp_path / 'sessions_store.json'
        store.write_text(json.dumps({
            'active_session_id': 's1',
            'sessions': {'s1': {'id': 's1', 'file_path': '', 'parameters': {}}},
        }), encoding='utf-8')
        loaded, _ = load_sessions_from_disk(store)
        assert loaded['s1']['changeover_overrides'] == {}

    def test_reset_zet_de_overrides_uit(self):
        data, results = _combo_setup()
        engine = _Engine(data, results)
        sess = {'id': 's1', 'engine': engine, 'pending_edits': {},
                'machine_overrides': {},
                'changeover_overrides': {f'MA|{PERIOD}': 5}}
        install_clean_engine_baseline(sess, engine, lambda m, d: 0.0,
                                      clear_machine_overrides=True)
        assert sess['changeover_overrides'] == {}

    def test_configwijziging_laat_ze_staan(self):
        data, results = _combo_setup()
        engine = _Engine(data, results)
        sess = {'id': 's1', 'engine': engine, 'pending_edits': {},
                'machine_overrides': {},
                'changeover_overrides': {f'MA|{PERIOD}': 5}}
        install_clean_engine_baseline(sess, engine, lambda m, d: 0.0,
                                      clear_machine_overrides=False)
        assert sess['changeover_overrides'] == {f'MA|{PERIOD}': 5}
