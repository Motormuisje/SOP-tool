"""Routes van de capaciteits- en FTE-werkbank (F2-CF).

Synthetische engine-stub met dezelfde recalculate_fte-semantiek als
PlanningEngine, zodat de routes zonder klantwerkboek testbaar zijn.
"""

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
