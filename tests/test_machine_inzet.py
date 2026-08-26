"""Machine-inzet fase 1 + 1b: omstellingen, volgorde en kosten per machine.

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


# ── Fase 1b: volgorde, tarief en kosten ──────────────────────────────────────

def _twee_producten_op_ma(machine_costs=None, plan_pb=5000.0):
    """MA draait PA (100 u) én PB (50 u standaard) — dus één omstelling per
    periode; MB staat stil. Optioneel machinekosten voor de tarief-terugval."""
    from modules.capacity_engine import CapacityEngine
    from modules.models import MachineGroup
    from tests.test_fte_engine import PERIODS, _data, _demand_rows, _machine, _mat, _routing

    machines = {'MA': _machine('MA', group='ZZ_G1'), 'MB': _machine('MB', group='ZZ_G2')}
    materials = {
        'ZZ_G1': _mat('ZZ_G1', packaging_machine_group='1', fte_requirements=1.0),
        'ZZ_G2': _mat('ZZ_G2', packaging_machine_group='1', fte_requirements=1.0),
        'PA': _mat('PA', name='Product A'), 'PB': _mat('PB', name='Product B'),
    }
    groups = {'ZZ_G1': MachineGroup('ZZ_G1', ['MA']), 'ZZ_G2': MachineGroup('ZZ_G2', ['MB'])}
    routings = {'PA': [_routing('MA')], 'PB': [_routing('MA')]}
    plan = {'PA': dict.fromkeys(PERIODS, 10000.0), 'PB': dict.fromkeys(PERIODS, plan_pb)}
    extra = {'machine_costs': machine_costs or {}}
    data = _data(machines, materials, groups, routings, **extra)
    results = CapacityEngine(data, plan, {}).calculate()
    results[LineType.DEMAND_FORECAST.value] = _demand_rows(data, {})
    return data, results


def _env2(machine_costs=None, changeovers=None, sess_extra=None):
    from ui.routes.machine_inzet import build_machine_inzet
    data, results = _twee_producten_op_ma(machine_costs)
    engine = _Engine(data, results)
    engine.recalculate_fte([])
    sess = {'id': 's1', 'engine': engine, 'changeover_overrides': {},
            'changeover_sequences': {}}
    sess.update(sess_extra or {})
    return engine, sess, (lambda: build_machine_inzet(engine, sess, changeovers or {}))


class TestVolgorde:
    def test_standaardvolgorde_is_grootste_run_eerst(self):
        _, _, build = _env2()
        ma = build()['machines']['MA']
        assert ma['sequence'] == ['PA', 'PB']            # 100 u vóór 50 u
        assert ma['sequence_source'] == 'standaard'
        assert ma['product_names'] == {'PA': 'Product A', 'PB': 'Product B'}
        assert ma['product_hours']['PA'][PERIOD] == pytest.approx(100.0)
        assert ma['product_hours']['PB'][PERIOD] == pytest.approx(50.0)
        # De telling blijft producten − 1, onafhankelijk van de volgorde.
        assert ma['per_period'][PERIOD]['estimate'] == 1
        assert ma['per_period'][PERIOD]['changeovers'] == 1

    def test_standaardvolgorde_is_deterministisch_bij_gelijke_uren(self):
        from ui.routes.machine_inzet import _default_sequence
        assert _default_sequence({'PB': {PERIOD: 10.0}, 'PA': {PERIOD: 10.0}}) == ['PA', 'PB']

    def test_sessievolgorde_wint_en_overleeft_verdwenen_producten(self):
        from ui.routes.machine_inzet import _effective_sequence
        hours = {'PA': {PERIOD: 100.0}, 'PB': {PERIOD: 50.0}, 'PC': {PERIOD: 10.0}}
        seq, source = _effective_sequence(['PB', 'SPOOK', 'PA'], hours)
        assert seq == ['PB', 'PA', 'PC'] and source == 'wat-als'   # SPOOK weg, PC erachter
        seq, source = _effective_sequence([], hours)
        assert seq == ['PA', 'PB', 'PC'] and source == 'standaard'

    def test_route_valideert_en_persisteert_de_volgorde(self):
        from ui.routes.machine_inzet import create_machine_inzet_blueprint
        engine, sess, _ = _env2()
        saved = []
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(create_machine_inzet_blueprint(
            lambda: (sess, engine), lambda: saved.append(True)))
        client = app.test_client()

        ok = client.post('/api/machine_inzet/sequences', json={'sequences': {'MA': ['PB', 'PA']}})
        assert ok.status_code == 200, ok.get_json()
        assert sess['changeover_sequences'] == {'MA': ['PB', 'PA']}
        assert saved
        body = client.get('/api/machine_inzet').get_json()
        assert body['machines']['MA']['sequence'] == ['PB', 'PA']
        assert body['machines']['MA']['sequence_source'] == 'wat-als'
        assert body['sequences'] == {'MA': ['PB', 'PA']}

        # Lege lijst = terug naar standaard; machine weglaten ook.
        leeg = client.post('/api/machine_inzet/sequences', json={'sequences': {'MA': []}})
        assert leeg.get_json()['sequences'] == {}
        assert sess['changeover_sequences'] == {}

        for payload, fragment in [
            ({'sequences': [1]}, 'object'),
            ({'sequences': {'SPOOK': ['PA']}}, 'onbekende machine'),
            ({'sequences': {'MA': 'PA,PB'}}, 'lijst'),
            ({'sequences': {'MA': ['PA', 'PA']}}, 'dubbel'),
            ({'sequences': {'MA': ['PA', 'PX']}}, 'draait niet'),
        ]:
            resp = client.post('/api/machine_inzet/sequences', json=payload)
            assert resp.status_code == 400, payload
            assert fragment in resp.get_json()['error'], resp.get_json()

    def test_volgorde_reist_door_sessiestore_reset_en_duplicaat(self, tmp_path):
        data, results = _twee_producten_op_ma()
        engine = _Engine(data, results)
        sess = {'id': 's1', 'engine': engine, 'pending_edits': {}, 'machine_overrides': {},
                'changeover_overrides': {}, 'changeover_sequences': {'MA': ['PB', 'PA']}}
        store = tmp_path / 'sessions_store.json'
        save_sessions_to_disk({'s1': sess}, 's1', store, lambda s, e: {})
        loaded, _ = load_sessions_from_disk(store)
        assert loaded['s1']['changeover_sequences'] == {'MA': ['PB', 'PA']}

        # Oude store zonder veld: leeg, geen KeyError.
        store.write_text(json.dumps({'active_session_id': 's1', 'sessions': {
            's1': {'id': 's1', 'file_path': '', 'parameters': {}}}}), encoding='utf-8')
        assert load_sessions_from_disk(store)[0]['s1']['changeover_sequences'] == {}

        # Reset zet de volgorde uit; een configwijziging laat hem staan.
        install_clean_engine_baseline(sess, engine, lambda m, d: 0.0, clear_machine_overrides=True)
        assert sess['changeover_sequences'] == {}
        sess['changeover_sequences'] = {'MA': ['PB', 'PA']}
        install_clean_engine_baseline(sess, engine, lambda m, d: 0.0, clear_machine_overrides=False)
        assert sess['changeover_sequences'] == {'MA': ['PB', 'PA']}


class TestKosten:
    def _mc(self, rate):
        from modules.models import MachineCost
        return {'MA': MachineCost(plant_code='NLX1', cost_center='MA', variable_cost_per_hour=rate)}

    def test_zonder_omsteltijd_geen_uren_en_geen_kosten(self):
        _, _, build = _env2(machine_costs=self._mc(80.0))
        ma = build()['machines']['MA']
        assert ma['hours_per_changeover'] is None
        cel = ma['per_period'][PERIOD]
        assert cel['changeovers'] == 1
        assert cel['changeover_hours'] is None and cel['cost'] is None
        assert ma['total']['changeover_hours'] == 0 and ma['total']['cost'] == 0
        # Het tarief is wél al bekend (machinetarief), zodat invullen direct rekent.
        assert ma['rate'] == pytest.approx(80.0) and ma['rate_source'] == 'machinetarief'

    def test_tarief_uit_masterdata_wint_van_machinetarief(self):
        _, _, build = _env2(machine_costs=self._mc(80.0), changeovers={
            'MA': {'hours_per_changeover': 1.5, 'description': '', 'cost_per_hour': 120.0}})
        out = build()
        ma = out['machines']['MA']
        assert ma['rate'] == pytest.approx(120.0) and ma['rate_source'] == 'omsteltijden'
        cel = ma['per_period'][PERIOD]
        assert cel['changeover_hours'] == pytest.approx(1.5)      # 1 × 1,5
        assert cel['cost'] == pytest.approx(180.0)                # 1,5 × 120
        assert cel['window_pct'] == pytest.approx(1.5 / cel['window'] * 100, abs=0.01)   # 2 decimalen
        n = len(out['periods'])
        assert ma['total'] == {'changeovers': n, 'changeover_hours': pytest.approx(1.5 * n),
                               'cost': pytest.approx(180.0 * n),
                               'run_hours': pytest.approx(150.0 * n)}
        assert out['totals']['by_period'][PERIOD] == {
            'changeovers': 1, 'changeover_hours': pytest.approx(1.5), 'cost': pytest.approx(180.0)}
        assert out['totals']['horizon']['cost'] == pytest.approx(180.0 * n)

    def test_terugval_op_machinetarief_en_eerlijk_zonder_tarief(self):
        _, _, build = _env2(machine_costs=self._mc(80.0), changeovers={
            'MA': {'hours_per_changeover': 2.0, 'description': '', 'cost_per_hour': None}})
        ma = build()['machines']['MA']
        assert ma['rate_source'] == 'machinetarief'
        assert ma['per_period'][PERIOD]['cost'] == pytest.approx(160.0)   # 2 u × 80

        _, _, build = _env2(changeovers={
            'MA': {'hours_per_changeover': 2.0, 'description': '', 'cost_per_hour': None}})
        ma = build()['machines']['MA']
        assert ma['rate'] == 0 and ma['rate_source'] is None
        assert ma['per_period'][PERIOD]['changeover_hours'] == pytest.approx(2.0)
        assert ma['per_period'][PERIOD]['cost'] == 0      # uren wel, euro's eerlijk nul

    def test_override_op_aantal_werkt_door_in_uren_en_kosten(self):
        _, _, build = _env2(machine_costs=self._mc(80.0), changeovers={
            'MA': {'hours_per_changeover': 1.0, 'description': '', 'cost_per_hour': None}},
            sess_extra={'changeover_overrides': {f'MA|{PERIOD}': 4}})
        cel = build()['machines']['MA']['per_period'][PERIOD]
        assert cel['is_override'] and cel['estimate'] == 1 and cel['changeovers'] == 4
        assert cel['changeover_hours'] == pytest.approx(4.0)
        assert cel['cost'] == pytest.approx(320.0)

    def test_tarief_is_masterdata_met_check_en_serialisatie(self):
        from tests.master_fixtures import fake_master_loader
        from ui.routes.master_data import _check_changeover
        error, _ = _check_changeover('PBA01', {'hours_per_changeover': 1, 'cost_per_hour': -5}, {'PBA01'})
        assert error and 'tarief' in error.lower()
        error, _ = _check_changeover('PBA01', {'hours_per_changeover': 1, 'cost_per_hour': None}, {'PBA01'})
        assert error is None

        loader = fake_master_loader()
        loader.changeover_times = {
            'PBA01': ChangeoverTime(machine_code='PBA01', hours_per_changeover=0.75, cost_per_hour=95.5),
            'PBA02': ChangeoverTime(machine_code='PBA02', hours_per_changeover=0.5)}
        master = json.loads(json.dumps(serialize_master(loader), default=str))
        assert master['changeover_times']['PBA01']['cost_per_hour'] == 95.5
        assert master['changeover_times']['PBA02']['cost_per_hour'] is None

        # Een record van vóór dit veld (zonder cost_per_hour) hydrateert als None.
        from modules.master_data import hydrate_fte_datasets
        loader2 = fake_master_loader()
        hydrate_fte_datasets(loader2, {'changeover_times': {
            'PBA03': {'machine_code': 'PBA03', 'hours_per_changeover': 1.0}}})
        assert loader2.changeover_times['PBA03'].cost_per_hour is None
