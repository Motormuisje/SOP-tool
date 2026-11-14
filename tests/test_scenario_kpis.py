"""Scenariovergelijking: kerncijfers naast elkaar (ui/scenario_kpis.py).

De vergelijking rekent niets opnieuw. Deze tests pinnen dat elk kerncijfer
precies uit de motor komt: het financiële horizongetal is wat de motor zelf
in aux_2 zet, en dat volgt de VBA-regel (som voor stromen, gemiddelde voor
saldi, voorraadwaarde inclusief beginvoorraad).
"""

import copy
import json

import pytest

from modules.models import LineType
from tests.test_routes_scenarios import scenarios_route_app  # noqa: F401
from ui.routes.scenarios import snapshot_engine_results
from ui.scenario_kpis import compare, compute_kpis, input_changes


def _row(lt, values, material='MAT-1', aux=None, aux2=None, name='', family=''):
    return {'material_number': material, 'material_name': name, 'line_type': lt,
            'aux_column': aux, 'aux_2_column': aux2, 'product_family': family,
            'values': dict(values), 'starting_stock': 0.0}


P = ['2026-01', '2026-02', '2026-03']


def _synthetic(ebit=(10.0, 20.0, 30.0), inv=(5.0, -1.0, 2.0), target=(3.0, 3.0, 3.0),
               util=(0.5, 1.2, 0.9)):
    results = {
        LineType.TOTAL_DEMAND.value: [_row(LineType.TOTAL_DEMAND.value, dict(zip(P, (1.0, 2.0, 3.0))))],
        LineType.INVENTORY.value: [_row(LineType.INVENTORY.value, dict(zip(P, inv)), name='Mat 1')],
        LineType.MIN_TARGET_STOCK.value: [_row(LineType.MIN_TARGET_STOCK.value, dict(zip(P, target)))],
        LineType.UTILIZATION_RATE.value: [
            _row(LineType.UTILIZATION_RATE.value, dict(zip(P, util)), material='Z_M1', name='PML01', family='G1'),
            _row(LineType.UTILIZATION_RATE.value, dict(zip(P, (1.0, 1.0, 1.0))), material='Z_M9', name='PBA99'),
        ],
        LineType.FTE_REQUIREMENTS.value: [
            _row(LineType.FTE_REQUIREMENTS.value, dict(zip(P, (1.0, 2.0, 3.0))), material='G1'),
            _row(LineType.FTE_REQUIREMENTS.value, dict(zip(P, (1.0, 1.0, 1.0))), material='G2'),
        ],
    }
    values = {LineType.CONSOLIDATION.value: [
        _row(LineType.CONSOLIDATION.value, dict(zip(P, ebit)), material='ZZZZZZ_EBIT', aux2=str(sum(ebit))),
        _row(LineType.CONSOLIDATION.value, dict(zip(P, (0.1, 0.2, 0.3))), material='ZZZZZZ_ROCE', aux2=None),
    ]}
    return results, values


class TestExtraction:
    def test_financial_figure_is_the_engines_horizon_figure(self):
        results, values = _synthetic()
        out = compute_kpis(results, values)
        assert out['kpis']['ebit'] == 60.0
        assert out['series']['ebit'] == dict(zip(P, (10.0, 20.0, 30.0)))
        # aux_2 leeg = horizongetal 0 (zo laat de motor een ROCE van 0 achter).
        assert out['kpis']['roce'] == 0.0
        # Een regel die ontbreekt is onbekend, geen nul.
        assert out['kpis']['turnover'] is None

    def test_exceptions_and_capacity(self):
        out = compute_kpis(*_synthetic(), unlimited_machines=['PBA99'])
        k = out['kpis']
        assert k['below_target'] == 2.0          # -1 en 2 liggen onder 3
        assert k['stock_negative'] == 1.0
        assert out['eligible_target_months'] == 3
        assert k['overloaded_machine_months'] == 1.0
        assert k['peak_utilization'] == pytest.approx(1.2)
        # PBA99 staat in de lijst onbeperkte machines: niet in de top.
        assert [m['machine'] for m in out['exceptions']['top_machines']] == ['PML01']
        assert out['exceptions']['below_target'][0]['shortfall'] == pytest.approx(4.0)
        assert k['fte_avg'] == pytest.approx((2 + 3 + 4) / 3)
        assert k['ending_inventory'] == 2.0
        assert k['total_demand'] == 6.0

    def test_a_finite_machine_at_exactly_full_load_stays_in_the_ranking(self):
        """100 % in elke maand bewijst geen onbeperkte capaciteit: alleen de
        lijst uit de configuratie bepaalt dat."""
        results, values = _synthetic(util=(0.5, 0.6, 0.7))
        out = compute_kpis(results, values, unlimited_machines=[])
        assert out['exceptions']['top_machines'][0]['machine'] == 'PBA99'
        assert out['kpis']['peak_utilization'] == pytest.approx(1.0)
        assert out['kpis']['overloaded_machine_months'] == 0.0

    def test_material_without_a_target_row_is_not_counted_below_target(self):
        results, values = _synthetic()
        results[LineType.MIN_TARGET_STOCK.value] = []
        out = compute_kpis(results, values)
        assert out['kpis']['below_target'] == 0.0
        assert out['eligible_target_months'] == 0
        assert out['kpis']['stock_negative'] == 1.0


    def test_planned_hours_on_a_machine_without_capacity_are_counted(self):
        """At 0 % availability the engine reports utilization 0 (no division by
        zero), so the month looks idle. This count makes it visible."""
        results, values = _synthetic()
        results[LineType.AVAILABLE_CAPACITY.value] = [
            _row(LineType.AVAILABLE_CAPACITY.value, dict(zip(P, (1.0, 0.0, 0.0))), material='Z_M1', name='PML01', family='G1'),
            _row(LineType.AVAILABLE_CAPACITY.value, dict(zip(P, (0.0, 0.0, 0.0))), material='Z_M9', name='PBA99'),
        ]
        machine_hours = _row(LineType.CAPACITY_UTILIZATION.value, dict(zip(P, (10.0, 12.0, 0.0))),
                             material='Z_M1', name='PML01')
        machine_hours['product_type'] = 'Machine'
        material_hours = _row(LineType.CAPACITY_UTILIZATION.value, dict(zip(P, (99.0, 99.0, 99.0))), material='MAT-1')
        unlimited = _row(LineType.CAPACITY_UTILIZATION.value, dict(zip(P, (5.0, 5.0, 5.0))), material='Z_M9', name='PBA99')
        unlimited['product_type'] = 'Machine'
        results[LineType.CAPACITY_UTILIZATION.value] = [machine_hours, material_hours, unlimited]

        out = compute_kpis(results, values, unlimited_machines=['PBA99'])

        assert out['kpis']['no_capacity_months'] == 1.0          # PML01 in 2026-02 only
        item = out['exceptions']['no_capacity'][0]
        assert (item['machine'], item['period'], item['hours']) == ('PML01', '2026-02', 12.0)


class TestCompare:
    def test_deltas_against_the_first_column(self):
        a_res, a_val = _synthetic()
        b_res, b_val = _synthetic(ebit=(10.0, 25.0, 30.0))
        out = compare([{'name': 'A', 'results': a_res, 'value_results': a_val},
                       {'name': 'B', 'results': b_res, 'value_results': b_val}])
        assert out['columns'][0]['deltas'] == {}
        assert out['columns'][1]['deltas']['ebit'] == pytest.approx(5.0)
        assert out['columns'][1]['compatibility'] == 'gelijk'

    def test_no_deltas_when_the_horizon_differs(self):
        a_res, a_val = _synthetic()
        b_res, b_val = _synthetic()
        for rows in b_res.values():
            for row in rows:
                row['values']['2026-04'] = 0.0
        out = compare([{'name': 'A', 'results': a_res, 'value_results': a_val},
                       {'name': 'B', 'results': b_res, 'value_results': b_val}])
        assert out['columns'][1]['compatibility'] == 'andere horizon'
        assert out['columns'][1]['deltas'] == {}

    def test_input_changes_name_what_differs(self):
        base = {'pending_edits': {}, 'machine_overrides': {}, 'valuation_params': {'1': 1.0},
                'purchased_and_produced': 'MAT-1:0.25'}
        other = dict(base, pending_edits={'k': {}}, valuation_params={'1': 2.0})
        changes = input_changes(other, base)
        assert any('planbewerkingen' in c for c in changes)
        assert 'waarderingsparameters' in changes
        assert not any('machine' in c for c in changes)


def test_extraction_on_the_real_engine_follows_the_vba_rules(planning_engine_result):
    """On the golden workbook: flows equal the sum of their monthly values,
    the inventory value equals the average including the starting stock, and
    ROCE equals total EBIT over average capital investment."""
    results, values, _ = snapshot_engine_results(planning_engine_result)
    out = compute_kpis(results, values)
    periods = out['periods']
    consol = {r['material_number']: r for r in values[LineType.CONSOLIDATION.value]}

    assert len(periods) == len(planning_engine_result.data.periods)
    for key, row in (('ebit', 'ZZZZZZ_EBIT'), ('turnover', 'ZZZZZZ_TURNOVER'),
                     ('operational_cashflow', 'ZZZZZZ_OPERATIONAL CASHFLOW')):
        assert out['kpis'][key] == pytest.approx(sum(consol[row]['values'][p] for p in periods), rel=1e-9)
    starting = sum(r['starting_stock'] for r in values[LineType.INVENTORY.value])
    inv = [starting] + [consol['ZZZZZZ_INVENTORY VALUE']['values'][p] for p in periods]
    assert out['kpis']['inventory_value'] == pytest.approx(sum(inv) / len(inv), rel=1e-9)
    ci = consol['ZZZZZZ_CAPITAL INVESTMENT']['values']
    expected_roce = sum(consol['ZZZZZZ_EBIT']['values'][p] for p in periods) / (sum(ci[p] for p in periods) / len(periods))
    assert out['kpis']['roce'] == pytest.approx(expected_roce, rel=1e-9)
    assert out['kpis']['fte_avg'] > 0
    assert out['kpis']['peak_utilization'] is not None


def test_comparing_a_scenario_with_itself_gives_zero_deltas(planning_engine_result):
    results, values, _ = snapshot_engine_results(planning_engine_result)
    column = {'name': 'X', 'results': results, 'value_results': values}
    out = compare([column, copy.deepcopy(column)])
    deltas = out['columns'][1]['deltas']
    assert deltas and all(v is None or abs(v) < 1e-9 for v in deltas.values())


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@pytest.mark.no_fixture
def test_route_compares_saved_scenarios_and_the_current_plan(scenarios_route_app):  # noqa: F811
    app = scenarios_route_app
    first = app.client.post('/api/scenarios/save', json={'name': 'Basis'}).get_json()
    saved = app.scenarios[first['scenario_id']]
    assert saved['periods'] == [] or isinstance(saved['periods'], list)
    assert 'master_version' in saved

    response = app.client.post('/api/scenarios/kpis', json={
        'scenario_ids': [first['scenario_id']], 'include_current': True})

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    names = [c['name'] for c in body['columns']]
    assert names == ['Basis', 'Huidige stand']
    assert body['columns'][1]['is_current'] is True
    assert body['headline'][0] == 'ebit'


@pytest.mark.no_fixture
@pytest.mark.parametrize('payload, status', [
    (['niet', 'een', 'object'], 400),
    ({'scenario_ids': ['a'], 'include_current': 'false'}, 400),               # geen boolean
    ({'scenario_ids': ['a', 'b'], 'base': 'a'}, 400),                         # base alleen 'current'
    ({'scenario_ids': ['a', 'b'], 'base': 'current'}, 400),                   # zonder huidige stand
    ({'scenario_ids': [], 'include_current': True}, 400),                    # één kolom
    ({'scenario_ids': ['a', 'b', 'c', 'd'], 'include_current': True}, 400),  # vijf kolommen
    ({'scenario_ids': ['a', 'a']}, 400),                                     # dubbel
    ({'scenario_ids': 'a'}, 400),                                            # geen lijst
    ({'scenario_ids': ['missing', 'other']}, 404),
])
def test_route_validates_the_selection(scenarios_route_app, payload, status):  # noqa: F811
    response = scenarios_route_app.client.post('/api/scenarios/kpis', json=payload)
    assert response.status_code == status


@pytest.mark.no_fixture
def test_route_refuses_scenarios_of_another_session(scenarios_route_app):  # noqa: F811
    app = scenarios_route_app
    sid = app.client.post('/api/scenarios/save', json={'name': 'A'}).get_json()['scenario_id']
    app.scenarios[sid]['session_id'] = 'session-b'

    response = app.client.post('/api/scenarios/kpis', json={'scenario_ids': [sid], 'include_current': True})

    assert response.status_code == 403


@pytest.mark.no_fixture
def test_live_column_is_read_inside_the_rebuild_lock(scenarios_route_app):  # noqa: F811
    """The engine is looked up while holding the rebuild lock, so a rebuild
    cannot swap it between lookup and read."""
    from ui.locks import engine_rebuild_lock

    app = scenarios_route_app
    sid = app.client.post('/api/scenarios/save', json={'name': 'A'}).get_json()['scenario_id']
    seen = []
    original_results = app.engine.results

    class _Probe(dict):
        def items(self):
            seen.append(engine_rebuild_lock._is_owned())
            return original_results.items()

    app.engine.results = _Probe(original_results)
    try:
        response = app.client.post('/api/scenarios/kpis', json={'scenario_ids': [sid], 'include_current': True})
    finally:
        app.engine.results = original_results
    assert response.status_code == 200, response.get_json()
    assert seen and all(seen)


@pytest.mark.no_fixture
def test_master_version_is_the_engines_and_a_difference_is_flagged(scenarios_route_app):  # noqa: F811
    from types import SimpleNamespace

    app = scenarios_route_app
    app.engine._resolved_master_source = SimpleNamespace(version=7)
    sid = app.client.post('/api/scenarios/save', json={'name': 'Op v7'}).get_json()['scenario_id']
    assert app.scenarios[sid]['master_version'] == 7
    app.engine._resolved_master_source = SimpleNamespace(version=9)

    body = app.client.post('/api/scenarios/kpis', json={'scenario_ids': [sid], 'include_current': True}).get_json()

    base, live = body['columns']
    assert base['master_version'] == 7 and live['master_version'] == 9
    assert live['master_version_differs'] is True and base['master_version_known'] is True


@pytest.mark.no_fixture
def test_older_scenarios_take_the_current_unlimited_list_and_say_so(scenarios_route_app):  # noqa: F811
    from types import SimpleNamespace

    app = scenarios_route_app
    app.engine.data.config = SimpleNamespace(unlimited_capacity_machine=['PBA99'])
    sid = app.client.post('/api/scenarios/save', json={'name': 'Nieuw'}).get_json()['scenario_id']
    assert app.scenarios[sid]['unlimited_machines'] == ['PBA99']
    old = dict(app.scenarios[sid], name='Oud')
    old.pop('unlimited_machines')
    app.scenarios['old'] = old

    body = app.client.post('/api/scenarios/kpis', json={'scenario_ids': ['old', sid]}).get_json()

    assert body['columns'][0]['unlimited_assumed'] is True
    assert body['columns'][1]['unlimited_assumed'] is False



# ---------------------------------------------------------------------------
# Audit 2026-11: defects found in this module by review, each pinned here
# ---------------------------------------------------------------------------

class TestAuditFindings:
    def test_recorded_horizon_wins_over_a_sparse_first_row(self):
        results, values = _synthetic()
        results[LineType.DEMAND_FORECAST.value] = [
            _row(LineType.DEMAND_FORECAST.value, {'2026-01': 1.0}, material='SPARSE')]
        assert compute_kpis(results, values, periods=P)['periods'] == P
        # Without a recorded horizon the union of the rows is used, not the first row.
        results[LineType.DEMAND_FORECAST.value].append(
            _row(LineType.DEMAND_FORECAST.value, dict(zip(P, (1.0, 1.0, 1.0))), material='FULL'))
        assert compute_kpis(results, values)['periods'] == P

    @pytest.mark.parametrize('bad', [[], 'abc', [1, 2], None, ['2026-01', '']])
    def test_an_invalid_recorded_horizon_falls_back_to_the_rows(self, bad):
        results, values = _synthetic()
        assert compute_kpis(results, values, periods=bad)['periods'] == P

    def test_unreadable_figures_are_unknown_not_zero(self):
        results, values = _synthetic()
        values[LineType.CONSOLIDATION.value][0]['aux_2_column'] = 'n/a'
        results[LineType.TOTAL_DEMAND.value][0]['values']['2026-02'] = 'abc'
        results[LineType.FTE_REQUIREMENTS.value][0]['values']['2026-03'] = float('nan')
        out = compute_kpis(results, values)
        assert out['kpis']['ebit'] is None
        assert out['kpis']['total_demand'] is None
        assert out['kpis']['fte_avg'] is None
        # A blank aux_2 is the engine's way of writing 0 and stays 0.
        assert out['kpis']['roce'] == 0.0

    def test_unknown_figures_give_no_delta(self):
        a_res, a_val = _synthetic()
        b_res, b_val = _synthetic()
        b_val[LineType.CONSOLIDATION.value][0]['aux_2_column'] = 'n/a'
        out = compare([{'name': 'A', 'results': a_res, 'value_results': a_val},
                       {'name': 'B', 'results': b_res, 'value_results': b_val}])
        assert out['columns'][1]['deltas']['ebit'] is None

    def test_only_the_charted_series_is_sent(self):
        out = compute_kpis(*_synthetic())
        assert set(out['series']) == {'ebit'}



@pytest.mark.no_fixture
def test_older_scenarios_are_ranked_without_the_current_unlimited_machines(scenarios_route_app):  # noqa: F811
    """Mutation test gap: the earlier test checked the flag, not that the
    fallback list is actually used. PBA99 runs at exactly 100 % (unlimited);
    with the fallback it must not top the ranking of an older scenario."""
    from types import SimpleNamespace

    app = scenarios_route_app
    app.engine.data.config = SimpleNamespace(unlimited_capacity_machine=['PBA99'])
    sid = app.client.post('/api/scenarios/save', json={'name': 'Nieuw'}).get_json()['scenario_id']
    util = LineType.UTILIZATION_RATE.value
    rows = [_row(util, dict(zip(P, (1.0, 1.0, 1.0))), material='Z_M9', name='PBA99'),
            _row(util, dict(zip(P, (0.4, 0.5, 0.6))), material='Z_M1', name='PML01')]
    for scenario_id in (sid,):
        app.scenarios[scenario_id]['results'][util] = rows
    old = dict(app.scenarios[sid], name='Oud')
    old.pop('unlimited_machines')
    app.scenarios['old'] = old

    body = app.client.post('/api/scenarios/kpis', json={'scenario_ids': ['old', sid]}).get_json()

    for column in body['columns']:
        assert [m['machine'] for m in column['exceptions']['top_machines']] == ['PML01'], column['name']
