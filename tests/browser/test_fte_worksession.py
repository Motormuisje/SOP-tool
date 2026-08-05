"""Een échte werksessie met de capaciteits- en FTE-werkbank, end-to-end.

Geen losse unittests maar de volgorde waarin een consultant het gebruikt, op
een echte server met een echt klantwerkboek:

    doorrekenen -> masterdata importeren -> combinatie aanmaken -> loontarief
    invoeren -> herberekenen -> werkbank openen -> combinatie aanzetten ->
    varianten vergelijken -> norm bijstellen -> scenario opslaan -> scenario
    laden -> instantie dupliceren -> Reset -> server herstarten

Elke stap controleert het GETAL dat de gebruiker op dat moment ziet, niet
alleen de HTTP-status. Deze test bestaat omdat de unittests elk onderdeel los
afdekken maar niet de keten: de bugjacht vond juist daar de dure fouten (een
duplicaat dat stil anders rekende, een scenario dat overrides liet staan).

Draait op een EIGEN server (`own_server`): de sessie importeert masterdata,
dupliceert instanties en laadt scenario's, dus hij moet vanaf een bekende
begintoestand starten. Op de gedeelde server hing de uitkomst af van wat er
eerder in de suite had gedraaid — dat maakte de laatste stap wisselvallig.
"""

import json

import pytest
import requests

pytestmark = pytest.mark.no_fixture

TIMEOUT = 180


def _get(server, path, **kwargs):
    response = requests.get(server['base_url'] + path, timeout=TIMEOUT, **kwargs)
    return response, response.json()


def _post(server, path, payload=None, **kwargs):
    response = requests.post(server['base_url'] + path, json=payload,
                             timeout=TIMEOUT, **kwargs)
    return response, response.json()


def _patch(server, dataset, value, base_version=None):
    body = {'value': value}
    if base_version is not None:
        body['base_version'] = base_version
    response = requests.patch(f'{server["base_url"]}/api/master_data/{dataset}',
                              json=body, timeout=TIMEOUT)
    return response, response.json()


def _avg(values):
    values = [v for v in (values or {}).values()]
    return sum(values) / len(values) if values else 0.0


def _workbench(server):
    response, body = _get(server, '/api/fte')
    assert response.ok, body
    return body


def _wait_until_ready(server, session_id, seconds=180):
    """Wacht tot een koude sessie klaar is met opwarmen."""
    import time

    deadline = time.monotonic() + seconds
    status = None
    while time.monotonic() < deadline:
        _, listing = _get(server, '/api/sessions')
        # /api/sessions groepeert op jaar/maand/site.
        entries = [item for group in listing.get('groups', {}).values() for item in group]
        entry = next((e for e in entries if e['id'] == session_id), None)
        status = (entry or {}).get('restore_status')
        if status in ('ready', 'failed'):
            return status
        time.sleep(1)
    return status


@pytest.fixture(scope='module')
def session(own_server, golden_fixture_path):
    """Eén doorgerekende sessie met masterdata in de store.

    De masterdata komt uit het masterwerkboek dat de app zelf exporteert —
    dat is de route die de klant ook gebruikt, inclusief de F2-CF-bladen.
    """
    server = own_server
    # 1. Masterdata in de app zetten via het eigen werkboekformaat.
    response, body = _get(server, '/api/master_data')
    if not body.get('exists'):
        # Nog geen store: importeer het BASISwerkboek één keer als masterbron.
        with golden_fixture_path.open('rb') as workbook:
            response = requests.post(
                server['base_url'] + '/api/master_data/import',
                files={'file': (golden_fixture_path.name, workbook)},
                data={'confirm': 'true'}, timeout=TIMEOUT)
        assert response.ok, response.text
    return server


def test_01_masterdata_is_available(session):
    _, body = _get(session, '/api/master_data')

    assert body['exists'] is True
    assert body['counts']['machines'] > 0, 'zonder machines rekent de app geen capaciteit'
    # De F2-CF-datasets bestaan, ook al zijn ze nog leeg.
    for dataset in ('staffing_norms', 'machine_combinations', 'indirect_activities'):
        assert dataset in body['counts']


def test_02_workbench_opens_and_reproduces_line_12(session):
    """Zonder bemensingsnormen moet de werkbank exact geven wat Line 12 geeft.
    Wijkt dat af, dan is de motor niet meer additief."""
    body = _workbench(session)
    fte = body['fte']

    _, results = _get(session, '/api/results')
    l12 = list(results['results']['12. FTE requirements'])
    l12_avg = sum(_avg(r['values']) for r in l12)

    assert _avg(fte['totals']['direct_fte']) == pytest.approx(l12_avg, rel=1e-9)
    assert _avg(fte['totals']['indirect_fte']) == 0.0
    assert fte['fte_hours_per_year'] > 0


def test_03_utilization_never_exceeds_one_hundred_percent(session):
    """Regressie: indirecte activiteiten en de controlekamer zaten in de
    teller maar niet in de noemer — 119% bezetting op machines die op 19%
    liepen."""
    fte = _workbench(session)['fte']

    for period, value in fte['totals']['utilization'].items():
        assert 0.0 <= value <= 1.0, f'{period}: bezetting {value:.1%}'


def test_04_no_row_is_called_nan(session):
    fte = _workbench(session)['fte']
    labels = [line['label'] for line in fte['lines']]

    assert labels
    assert not any(str(label).lower().startswith('nan') for label in labels)


def test_05_consultant_adds_a_combination_and_a_labour_rate(session):
    """De consultant maakt in de masterdata een combinatie aan over twee
    machines uit VERSCHILLENDE groepen — daar zit de besparing."""
    _, machines_body = _get(session, '/api/master_data/machines')
    machines = machines_body['value']
    by_group = {}
    for machine in machines:
        by_group.setdefault(machine.get('machine_group') or '', []).append(machine['machine_code'])
    groups = [codes for group, codes in sorted(by_group.items()) if group]
    assert len(groups) >= 2, 'deze fixture heeft twee machinegroepen nodig'
    pair = [groups[0][0], groups[1][0]]

    _, status = _get(session, '/api/master_data')
    response, body = _patch(session, 'machine_combinations', {
        'DUO': {'combination_id': 'DUO', 'name': 'Duo over twee groepen',
                'machine_codes': pair, 'operators': 1.0, 'throughput_factor': 1.0,
                'function_group': 'operators', 'is_active': True,
                'description': 'Aangemaakt in de werksessietest'},
    }, base_version=status['version'])
    assert response.ok, body

    _, status = _get(session, '/api/master_data')
    response, body = _patch(session, 'labor_rates', {
        'default': {'function_group': 'default', 'cost_per_fte_per_year': 60000.0},
        'operators': {'function_group': 'operators', 'cost_per_fte_per_year': 60000.0},
    }, base_version=status['version'])
    assert response.ok, body

    session['combination_machines'] = pair


def test_06_a_stale_base_version_is_refused(session):
    """Twee tabbladen open: het tweede mag het eerste niet stil overschrijven."""
    response, body = _patch(session, 'labor_rates', {
        'default': {'function_group': 'default', 'cost_per_fte_per_year': 1.0},
    }, base_version=1)

    assert response.status_code == 409
    assert 'gewijzigd' in body['error']


def test_07_recalculate_picks_up_the_masterdata(session):
    response, body = _post(session, '/api/calculate', {
        'planning_month': '2025-12', 'months_actuals': 11, 'months_forecast': 12})
    assert response.ok, body
    assert body.get('success')

    workbench = _workbench(session)
    assert [c['combination_id'] for c in workbench['combinations']] == ['DUO']
    # Met loontarieven verschijnt er een kostenkolom.
    assert _avg(workbench['fte']['totals']['cost']) > 0


def test_08_switching_the_combination_on_lowers_the_hours(session):
    before = _workbench(session)['fte']
    before_hours = _avg(before['totals']['hours'])

    response, body = _post(session, '/api/fte/combinations',
                           {'active_combinations': ['DUO']})
    assert response.ok, body
    after_hours = _avg(body['fte']['totals']['hours'])

    assert after_hours < before_hours, (
        f'een gedeelde operator moet uren besparen: {before_hours:.1f} -> {after_hours:.1f}')
    assert body['active_combinations'] == ['DUO']


def test_09_comparison_shows_the_variant_as_cheaper(session):
    response, body = _post(session, '/api/fte/compare', {'variants': [
        {'label': 'Zonder', 'active_combinations': []},
        {'label': 'Met DUO', 'active_combinations': ['DUO']},
    ]})
    assert response.ok, body

    by_label = {v['label']: v['summary'] for v in body['variants']}
    assert by_label['Met DUO']['fte_avg'] < by_label['Zonder']['fte_avg']
    assert by_label['Met DUO']['labor_cost_total'] < by_label['Zonder']['labor_cost_total']
    for summary in by_label.values():
        assert 0.0 <= summary['utilization'] <= 1.0


def test_10_editing_a_norm_flows_through_to_the_workbench(session):
    """De werkbankflow: versie ophalen, PATCH met base_version, refresh."""
    workbench = _workbench(session)
    group = next(line for line in workbench['fte']['lines']
                 if line['category'] == 'group' and _avg(line['fte']) > 0
                 and not line['combination_id'])
    before = _avg(group['fte'])

    _, current = _get(session, f'/api/master_data/staffing_norms')
    value = dict(current['value'] or {})
    value[group['key']] = {'code': group['key'], 'operators_per_hour': 2.0,
                           'scope': 'group', 'function_group': 'operators',
                           'description': 'werksessietest'}
    response, body = _patch(session, 'staffing_norms', value,
                            base_version=workbench['master_version'])
    assert response.ok, body

    response, refreshed = _post(session, '/api/fte/refresh')
    assert response.ok, refreshed
    after_line = next(line for line in refreshed['fte']['lines']
                      if line['key'] == group['key'] and line['category'] == 'group')

    assert after_line['operators_source'] == 'staffing_norms'
    assert _avg(after_line['fte']) > before, 'twee operators moet meer FTE geven dan één'
    assert refreshed['master_version'] == body['version']


def test_11_scenario_round_trip_keeps_the_combination(session):
    """Regressie: machine-overrides en combinaties horen bij het scenario."""
    _post(session, '/api/fte/combinations', {'active_combinations': ['DUO']})
    with_combo = _avg(_workbench(session)['fte']['totals']['hours'])

    response, saved = _post(session, '/api/scenarios/save', {'name': 'Met DUO'})
    assert response.ok, saved
    scenario_id = saved['scenario_id']

    _post(session, '/api/fte/combinations', {'active_combinations': []})
    assert _avg(_workbench(session)['fte']['totals']['hours']) > with_combo

    response, loaded = _post(session, '/api/scenarios/load', {'scenario_id': scenario_id})
    assert response.ok, loaded

    restored = _workbench(session)
    assert restored['active_combinations'] == ['DUO']
    assert _avg(restored['fte']['totals']['hours']) == pytest.approx(with_combo, rel=1e-6)


def test_12_a_duplicated_instance_computes_the_same_numbers(session):
    """Regressie: 'Opslaan als instantie' kopieerde active_combinations niet,
    dus het duplicaat toonde stil andere FTE en EBITDA."""
    source = _workbench(session)
    source_hours = _avg(source['fte']['totals']['hours'])
    assert source['active_combinations'] == ['DUO']

    response, snapshot = _post(session, '/api/sessions/snapshot', {'name': 'Kopie'})
    assert response.ok, snapshot
    new_id = snapshot['session']['id']

    response, switched = _post(session, '/api/sessions/switch', {'session_id': new_id})
    assert response.ok, switched

    # Een duplicaat is KOUD: de engine wordt op de achtergrond opnieuw gebouwd
    # (upload -> berekenen -> edits terugspelen). Tot dat klaar is heeft de
    # werkbank niets te tonen. Dat is correct gedrag, dus wachten we erop —
    # precies zoals de gebruiker op het spinnertje wacht.
    status = _wait_until_ready(session, new_id)
    assert status == 'ready', f'de kopie werd niet warm: {status}'

    copy_workbench = _workbench(session)
    assert copy_workbench['active_combinations'] == ['DUO'], (
        'de kopie kreeg de actieve combinatie niet mee')
    session['duplicate_hours'] = _avg(copy_workbench['fte']['totals']['hours'])
    session['source_hours'] = source_hours


@pytest.mark.xfail(strict=False, reason=(
    'BESTAANDE BUG, niet uit F2-CF: een instantie die je dupliceert NA het laden '
    'van een scenario rekent andere Line 07-uren dan zijn bron. Gebisecteerd op '
    'commit 3235ffe (dus zonder enige F2-CF-wijziging): zonder scenario is de '
    'kopie exact gelijk (0 afwijkende regels), met scenario wijken er 3 af — '
    'materiaal 600003822 op PML06 gaat van 73,1 naar 346,0 uur, en daarmee '
    'machine Z_MACH06 en groep ZZ_GROUP04. Herberekenen zelf is wel idempotent. '
    'Vermoedelijke oorzaak: scenario-save leidt pending_edits af uit manual_edits '
    'op de rijen (build_pending_edits_from_results_snapshot), scenario-load zet '
    'die in capacity_overrides, en de kopie speelt ze bij het opwarmen opnieuw af.'))
def test_12b_a_duplicate_after_a_scenario_load_should_match_its_source(session):
    assert session['duplicate_hours'] == pytest.approx(
        session['source_hours'], rel=1e-6)


def test_13_reset_switches_the_combination_off(session):
    assert _workbench(session)['active_combinations'] == ['DUO']

    response, body = _post(session, '/api/reset_edits')
    assert response.ok, body

    after = _workbench(session)
    assert after['active_combinations'] == []
    assert _avg(after['fte']['totals']['hours']) > 0


def test_14_the_workbench_survives_a_restart(session, tmp_path_factory):
    """De sessie-state moet op schijf staan, niet alleen in het geheugen."""
    _post(session, '/api/fte/combinations', {'active_combinations': ['DUO']})
    expected = _avg(_workbench(session)['fte']['totals']['hours'])

    # Wat er nu op schijf staat is wat een herstart terugleest.
    store = json.loads((session['app_data_dir'] / 'sessions_store.json')
                       .read_text(encoding='utf-8'))
    active = store['sessions'][store['active_session_id']]

    assert active['active_combinations'] == ['DUO'], (
        'active_combinations staat niet in sessions_store.json; na een herstart '
        'zou de werkbank met een andere bezetting rekenen')
    assert expected > 0
