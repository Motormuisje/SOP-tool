"""Routes van de capaciteits- en FTE-werkbank (F2-CF).

Synthetische engine-stub met dezelfde recalculate_fte-semantiek als
PlanningEngine, zodat de routes zonder klantwerkboek testbaar zijn.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from modules.fte_engine import FteEngine
from modules.models import LineType, MachineCombination, StaffingNorm
from tests.test_fte_engine import PERIODS, _demand_rows, _mill_setup
from ui.routes.fte import create_fte_blueprint

pytestmark = pytest.mark.no_fixture


class _Engine:
    """Precies het contract dat de routes gebruiken (zie
    PlanningEngine.recalculate_fte)."""

    def __init__(self, data, results, value_results=None):
        self.data = data
        self.results = results
        self.value_results = value_results or {}
        self.active_combinations = []
        self.fte_results = None

    def recalculate_fte(self, active_combinations=None):
        if active_combinations is not None:
            self.active_combinations = list(active_combinations)
        self.fte_results = FteEngine(
            self.data, self.results, active_combinations=self.active_combinations,
            value_results=self.value_results).calculate()


def _env(*, with_combination=True, demand=None):
    from modules.capacity_engine import CapacityEngine

    norms = {'ZZ_MILL': StaffingNorm(code='ZZ_MILL', operators_per_hour=1.0,
                                     scope='group')}
    combos = {}
    if with_combination:
        combos['C1'] = MachineCombination(
            combination_id='C1', name='Duo', machine_codes=['MC1'],
            operators=1.0, throughput_factor=0.5)
    data, plan = _mill_setup(hours_per_period=100.0, staffing_norms=norms,
                             machine_combinations=combos)
    results = CapacityEngine(data, plan, {}).calculate()
    results[LineType.DEMAND_FORECAST.value] = _demand_rows(data, demand or {})

    engine = _Engine(data, results)
    engine.recalculate_fte([])
    sess = {'id': 's1', 'engine': engine, 'active_combinations': []}
    saved = []

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(create_fte_blueprint(
        lambda: (sess, engine), lambda: saved.append(True)))
    return app.test_client(), sess, engine, saved


def test_get_returns_lines_totals_and_catalog():
    client, _, _, _ = _env()
    body = client.get('/api/fte').get_json()

    assert body['success'] is True
    assert body['fte']['periods'] == PERIODS
    assert body['fte']['totals']['fte']['2025-01'] > 0
    assert [c['combination_id'] for c in body['combinations']] == ['C1']
    assert body['active_combinations'] == []


def test_get_without_engine_is_a_clean_400():
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(create_fte_blueprint(lambda: (None, None), lambda: None))
    resp = app.test_client().post('/api/fte/combinations', json={'active_combinations': []})

    assert resp.status_code == 400
    assert 'berekening' in resp.get_json()['error']


def test_activating_a_combination_changes_hours_and_persists():
    client, sess, engine, saved = _env()
    before = client.get('/api/fte').get_json()['fte']['totals']['hours']['2025-01']

    body = client.post('/api/fte/combinations',
                       json={'active_combinations': ['C1']}).get_json()

    assert body['active_combinations'] == ['C1']
    # Doorzetfactor 0,5 → dubbele uren.
    assert body['fte']['totals']['hours']['2025-01'] == pytest.approx(before * 2)
    assert sess['active_combinations'] == ['C1']
    assert engine.active_combinations == ['C1']
    assert saved, 'sessies zijn niet weggeschreven'


def test_unknown_combination_is_refused():
    client, sess, _, _ = _env()
    resp = client.post('/api/fte/combinations', json={'active_combinations': ['NOPE']})

    assert resp.status_code == 400
    assert 'NOPE' in resp.get_json()['error']
    assert sess['active_combinations'] == []  # niets gemuteerd


def test_combinations_requires_a_list():
    client, _, _, _ = _env()
    assert client.post('/api/fte/combinations', json={}).status_code == 400


def test_compare_prepends_the_current_setting_as_baseline():
    client, _, _, _ = _env(demand={'P1': dict.fromkeys(PERIODS, 10000.0)})
    body = client.post('/api/fte/compare', json={
        'variants': [{'label': 'Met C1', 'active_combinations': ['C1']}]}).get_json()

    labels = [v['label'] for v in body['variants']]
    assert labels == ['Huidige instelling', 'Met C1']
    baseline, variant = body['variants']
    assert 'delta' not in baseline
    assert variant['delta']['hours_total'] == pytest.approx(
        variant['summary']['hours_total'] - baseline['summary']['hours_total'])
    assert variant['summary']['tons_per_fte'] > 0


def test_compare_reports_utilization_cost_and_productivity():
    client, _, _, _ = _env(demand={'P1': dict.fromkeys(PERIODS, 10000.0)})
    body = client.post('/api/fte/compare', json={
        'variants': [{'active_combinations': []}]}).get_json()

    summary = body['variants'][0]['summary']
    for key in ('fte_avg', 'utilization', 'labor_cost_total', 'tons_per_fte',
                'staffed_fte_avg'):
        assert key in summary
    # Zonder loontarieven is er geen kostenoordeel — en dus ook geen marge.
    assert summary['labor_cost_total'] == 0.0
    assert summary['value_impact_available'] is False


def test_compare_rejects_an_empty_variant_list():
    client, _, _, _ = _env()
    assert client.post('/api/fte/compare', json={'variants': []}).status_code == 400


class TestErrorPaths:
    """De foutpaden van het HTTP-oppervlak. Een 500 met traceback op een lege
    body is geen acceptabel antwoord in klantsoftware."""

    def test_get_computes_the_workbench_if_it_was_never_built(self):
        client, _, engine, _ = _env()
        engine.fte_results = None

        body = client.get('/api/fte').get_json()

        assert body['success'] is True
        assert engine.fte_results is not None

    def test_get_reports_when_the_workbench_cannot_be_built(self):
        """Een engine zonder recalculate_fte (oud of gestubd) mag geen 500 geven."""
        app = Flask(__name__)
        app.config['TESTING'] = True
        engine = SimpleNamespace(data=None, results={}, value_results={},
                                 fte_results=None)
        app.register_blueprint(create_fte_blueprint(lambda: ({}, engine), lambda: None))

        res = app.test_client().get('/api/fte')

        assert res.status_code == 400
        assert 'niet beschikbaar' in res.get_json()['error']

    @pytest.mark.parametrize('payload', [
        {},
        {'active_combinations': 'C1'},
        {'active_combinations': {'C1': True}},
    ])
    def test_combinations_needs_a_real_list(self, payload):
        client, _, _, _ = _env()
        assert client.post('/api/fte/combinations', json=payload).status_code == 400

    def test_the_response_reports_what_the_engine_applied(self):
        """Twee combinaties die dezelfde machine claimen: de motor zet er één
        uit. Antwoorden met de GEVRAAGDE lijst liet het vinkje aanstaan voor
        iets wat niet meerekent — en zette dat ook zo in de sessie."""
        from modules.models import MachineCombination

        client, sess, engine, _ = _env()
        engine.data.machine_combinations['C2'] = MachineCombination(
            combination_id='C2', machine_codes=['MC1'], operators=1.0)

        body = client.post('/api/fte/combinations',
                           json={'active_combinations': ['C1', 'C2']}).get_json()

        assert body['active_combinations'] == ['C1']
        assert sess['active_combinations'] == ['C1']
        assert engine.fte_results.active_combinations == ['C1']
        assert any('C2' in w for w in body['warnings'])

    def test_combinations_accepts_duplicates_without_double_counting(self):
        client, _, engine, _ = _env()
        once = client.post('/api/fte/combinations',
                           json={'active_combinations': ['C1']}).get_json()
        twice = client.post('/api/fte/combinations',
                            json={'active_combinations': ['C1', 'C1']}).get_json()

        assert twice['fte']['totals']['hours'] == once['fte']['totals']['hours']

    def test_refresh_without_a_store_is_a_clean_400(self):
        from ui import master_store

        previous = master_store.get_store_path()
        master_store.set_store_path(Path('bestaat-niet') / 'master_store.json')
        try:
            client, _, _, _ = _env()
            res = client.post('/api/fte/refresh')
            assert res.status_code == 400
            assert 'masterdata' in res.get_json()['error']
        finally:
            master_store.set_store_path(previous) if previous else None

    def test_refresh_without_an_engine_is_a_clean_400(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(create_fte_blueprint(lambda: (None, None), lambda: None))

        assert app.test_client().post('/api/fte/refresh').status_code == 400

    @pytest.mark.parametrize('variants,fragment', [
        ('geen lijst', 'niet-lege lijst'),
        ([], 'niet-lege lijst'),
        (['geen object'], 'geen object'),
        ([{'active_combinations': 'C1'}], 'moet een lijst zijn'),
        ([{'active_combinations': ['NOPE']}], 'onbekende combinatie'),
    ])
    def test_compare_rejects_malformed_variants(self, variants, fragment):
        client, _, _, _ = _env()
        res = client.post('/api/fte/compare', json={'variants': variants})

        assert res.status_code == 400
        assert fragment in res.get_json()['error']

    def test_compare_without_an_engine_is_a_clean_400(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(create_fte_blueprint(lambda: (None, None), lambda: None))

        res = app.test_client().post('/api/fte/compare',
                                     json={'variants': [{'active_combinations': []}]})
        assert res.status_code == 400

    def test_compare_handles_missing_margin_without_crashing(self):
        """gross_margin_total is None zonder valuatieparameters; de
        delta-berekening moet die overslaan in plaats van te struikelen."""
        client, _, _, _ = _env()
        body = client.post('/api/fte/compare', json={'variants': [
            {'label': 'Met C1', 'active_combinations': ['C1']}]}).get_json()

        variant = body['variants'][1]
        assert variant['summary']['gross_margin_total'] is None
        assert 'gross_margin_total' not in variant['delta']
        assert 'hours_total' in variant['delta']


class TestMasterVersion:
    """De werkbank bewerkt bemensingsnormen via de masterdata-PATCH, die een
    schrijfactie op een oudere versie met 409 weigert. Daarvoor moet de
    werkbank de versie meesturen waaruit de GETOONDE normen komen.

    De huidige storeversie melden zou juist het gevaarlijke geval doorlaten:
    masterdata-edits gelden pas bij de volgende berekening, dus een draaiende
    engine toont een oudere norm. Stuurt de werkbank dan de nieuwe versie mee,
    dan is er geen conflict en verdwijnt de wijziging van de collega.
    """

    def test_version_follows_the_engine_not_the_store(self, tmp_path):
        from ui import master_store

        previous = master_store.get_store_path()
        path = tmp_path / 'master_store.json'
        master_store.set_store_path(path)
        first = master_store.save_master_store(path, {'staffing_norms': {}},
                                               source_filename='x')
        master_store.save_master_store(path, {'staffing_norms': {}},
                                       previous=first, edited=True)
        master_store.set_store_path(path)
        try:
            client, _, engine, _ = _env()
            # De engine is gebouwd uit versie 1; de store staat inmiddels op 2.
            engine.data.fte_master_version = 1
            assert master_store.get_current_master_record()['version'] == 2

            assert client.get('/api/fte').get_json()['master_version'] == 1
        finally:
            master_store.set_store_path(previous) if previous else None

    def test_version_is_none_when_the_engine_has_none(self):
        """Werkboeksessie zonder store: geen versie om te melden, dus laat de
        frontend base_version weg in plaats van er een te verzinnen."""
        client, _, _, _ = _env()
        for payload in (client.get('/api/fte').get_json(),
                        client.post('/api/fte/combinations',
                                    json={'active_combinations': []}).get_json()):
            assert payload['master_version'] is None

    def test_refresh_stamps_the_version_it_read(self, tmp_path):
        from ui import master_store

        previous = master_store.get_store_path()
        path = tmp_path / 'master_store.json'
        master_store.set_store_path(path)
        master_store.save_master_store(path, {'staffing_norms': {}}, source_filename='x')
        master_store.set_store_path(path)
        try:
            client, _, engine, _ = _env()
            body = client.post('/api/fte/refresh').get_json()

            assert body['master_version'] == 1
            assert engine.data.fte_master_version == 1
        finally:
            master_store.set_store_path(previous) if previous else None

    def test_combinations_response_carries_the_version(self):
        client, _, _, _ = _env()
        body = client.post('/api/fte/combinations',
                           json={'active_combinations': ['C1']}).get_json()
        assert 'master_version' in body


class TestSitePoort:
    """De werkbank is uitgeschakeld zodra sessie en masterdata van
    verschillende sites zijn.

    Gezien in het echt: een NLK1-werkboeksessie in de gedeelde datamap naast
    de NLX1-store. Zonder poort toonde en berekende de werkbank machines van
    twee sites door elkaar, met de bemensingsnormen van de verkeerde site.
    """

    def _store_with_site(self, tmp_path, site):
        from ui import master_store

        previous = master_store.get_store_path()
        path = tmp_path / 'master_store.json'
        master_store.set_store_path(path)
        master_store.save_master_store(path, {'config': {'site': site},
                                              'staffing_norms': {}},
                                       source_filename='x')
        master_store.set_store_path(path)
        return previous

    def test_all_four_endpoints_refuse_a_cross_site_session(self, tmp_path):
        from ui import master_store

        previous = self._store_with_site(tmp_path, 'NLX1')
        try:
            client, _, engine, saved = _env()
            engine.data.config = SimpleNamespace(site='NLK1')

            calls = [
                ('GET', '/api/fte', None),
                ('POST', '/api/fte/combinations', {'active_combinations': ['C1']}),
                ('POST', '/api/fte/refresh', {}),
                ('POST', '/api/fte/compare',
                 {'variants': [{'label': 'x', 'active_combinations': []}]}),
            ]
            for method, url, payload in calls:
                resp = (client.get(url) if method == 'GET'
                        else client.post(url, json=payload))
                assert resp.status_code == 409, (url, resp.status_code)
                body = resp.get_json()
                assert 'NLK1' in body['error'] and 'NLX1' in body['error'], (url, body)
                assert body['workbook_site'] == 'NLK1'
                assert body['store_site'] == 'NLX1'
            # De weigering mag niets hebben aangeraakt of weggeschreven.
            assert saved == []
            assert engine.active_combinations == []
        finally:
            if previous:
                master_store.set_store_path(previous)

    def test_the_overlay_skip_flag_alone_is_enough(self):
        """Sessies die met de sitepoort zijn herbouwd dragen de vlag; die moet
        ook zonder (bereikbare) store volstaan — anders valt de bescherming weg
        zodra iemand de store verwijdert terwijl de sessie nog draait."""
        client, _, engine, _ = _env()
        engine.data.master_overlay_skipped = {'store_site': 'NLX1',
                                              'workbook_site': 'NLK1'}
        resp = client.get('/api/fte')
        assert resp.status_code == 409
        assert 'NLK1' in resp.get_json()['error']

    def test_matching_sites_pass(self, tmp_path):
        from ui import master_store

        previous = self._store_with_site(tmp_path, 'NLX1')
        try:
            client, _, engine, _ = _env()
            engine.data.config = SimpleNamespace(site='NLX1')
            assert client.get('/api/fte').status_code == 200
        finally:
            if previous:
                master_store.set_store_path(previous)
