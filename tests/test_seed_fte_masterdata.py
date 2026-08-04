"""Seed-script voor de F2-CF masterdata (tools/seed_fte_masterdata.py).

Draait op een synthetisch werkboek met dezelfde vorm als het klantmodel — het
echte bestand bevat klantdata en staat niet in de repo. Wat hier bewaakt wordt
is de LEESLOGICA: de bruto→netto FTE-afleiding, de draaitabel-doorvulling op
het PEER-blad, en de vertaaltabel klantnaam → SAP-code.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))

from seed_fte_masterdata import (  # noqa: E402
    MODEL_TO_SAP,
    read_fte,
    read_maintenance,
    read_model_machines,
    read_peer,
    read_truck_rows,
    verify_mapping,
)

pytestmark = pytest.mark.no_fixture


@pytest.fixture
def workbook():
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    fte = wb.create_sheet('FTE')
    for cell, value in (
        ('B5', 'Effective days'), ('D5', 260), ('E5', 8), ('F5', 2080),
        ('B6', 'Holiday'), ('D6', 28), ('E6', 8), ('F6', -224),
        ('B7', 'ATV'), ('D7', 14), ('E7', 8), ('F7', -112),
        ('B8', 'Public holidays in workweek'), ('D8', 6), ('E8', 8), ('F8', -48),
        ('B9', 'Working hours after holidays'), ('F9', 1696),
        ('B10', 'Sick leave'), ('C10', 0.1), ('F10', -169.6),
        ('B11', 'Training'), ('C11', 0.02), ('F11', -33.92),
        ('B13', 'Working hours per FTE per yr'), ('F13', 1492.48),
        ('B16', 'Bezettingsgraad'), ('D16', 0.85),
        ('B17', '2-ploegen'), ('C17', 4160),
        ('B18', '3-ploegen'), ('C18', 6240),
        ('B19', '24/7'), ('C19', 8760),
    ):
        fte[cell] = value

    model = wb.create_sheet('OEE Model MST ')
    # Kolomkoppen: rij 7 = OEE, rij 8 = capaciteit, rij 10 = naam.
    for column, (name, oee, capacity) in enumerate(
            [('MRL', 0.7, 50), ('PM01', 0.8, 3.5), ('Pneu', 0.7, 35)], start=8):
        model.cell(row=10, column=column, value=name)
        model.cell(row=7, column=column, value=oee)
        model.cell(row=8, column=column, value=capacity)
    # Trucks
    for cell, value in (
        ('D185', 'Container'), ('C185', 0.35), ('E185', 1.2), ('F185', 14644.6),
        ('G185', 22), ('H185', 665.663), ('I185', 0.535213),
        ('D186', 'Pallet/BB'), ('E186', 1), ('F186', 27197.1), ('G186', 24),
        ('H186', 1133.21), ('I186', 0.759281),
        ('D192', 'Containers'), ('E192', 1.5), ('F192', 7035.22), ('G192', 22),
        ('H192', 319.783), ('I192', 0.321394),
        ('B198', 'FTE Direct Maintenance'), ('D198', 9), ('E198', 'x / FTE'),
        ('D200', 67134.6), ('E200', 7459.4),
        ('D201', 1750000), ('E201', 194444),
    ):
        model[cell] = value

    peer = wb.create_sheet('PEER_Capacity')
    peer.append(['Facility Description', 'FullDescription', 'FullDescription',
                 'Throughput (tonnes/hour)'])
    # Draaitabelvorm: de installatienaam staat alleen op de eerste regel.
    peer.append(['NL-PP-Maastricht', 'AMB Ball Mill 3 (PML06)', 'Total', 27.79])
    peer.append([None, None, 'Ca-Carb A125 PO (600003728)', 26.23])
    peer.append([None, None, 'Dolomite DS19 PO (600003818)', 38.6])
    peer.append([None, 'AMB Bagging Machine 7 (PBA07)', 'Total', 6.21])
    peer.append([None, None, 'BAGGING', 6.21])
    return wb


def test_fte_derivation_matches_the_workbook(workbook):
    params, effective, shift_hours, checks = read_fte(workbook['FTE'])

    assert params == {
        'utilization_rate': 0.85, 'gross_hours_per_year': 2080.0,
        'leave_hours_per_year': 224.0, 'adv_hours_per_year': 112.0,
        'holiday_hours_per_year': 48.0, 'illness_pct': 0.1, 'training_pct': 0.02,
    }
    assert effective == pytest.approx(1492.48)
    assert shift_hours['3-shift system'] == pytest.approx(520.0)
    assert all('AFWIJKING' not in check for check in checks[:2])
    # De derde controleregel toont juist het verschil met stapelend rekenen.
    assert '+3.39' in checks[2]


def test_peer_forward_fills_the_pivot(workbook):
    """Zonder doorvullen leest élke productregel als 'geen machine' en valt de
    hele tabel weg — dat was de bug die 71 benchmarks tot 11 reduceerde."""
    rows, skipped = read_peer(workbook['PEER_Capacity'])
    by_key = {(r['machine_code'], r['material_number']): r['throughput'] for r in rows}

    assert by_key[('PML06', '')] == pytest.approx(27.79)          # installatietotaal
    assert by_key[('PML06', '600003728')] == pytest.approx(26.23)  # productregel
    assert by_key[('PML06', '600003818')] == pytest.approx(38.6)
    assert by_key[('PBA07', '')] == pytest.approx(6.21)
    assert any('BAGGING' in s for s in skipped)                    # geen materiaalnummer


def test_truck_rows_are_read_with_their_derivation(workbook):
    loading, unloading = read_truck_rows(workbook['OEE Model MST '])

    container = next(r for r in loading if r['label'] == 'Container')
    assert container['tons_per_truck'] == 22
    assert container['hours_per_truck'] == pytest.approx(1.2)
    assert container['volume'] / container['tons_per_truck'] == pytest.approx(
        container['trucks'], rel=1e-3)
    assert container['trucks'] * container['hours_per_truck'] / 1492.48 == pytest.approx(
        container['fte'], rel=1e-3)
    assert [r['label'] for r in unloading] == ['Containers']


def test_maintenance_is_a_headcount_not_a_ratio(workbook):
    """Rij 198 leest als '9 x / FTE'. Het klantmodel deelt de kengetallen in
    rij 200/201 dóór 9, dus 9 is het AANTAL onderhouds-FTE — niet '9 machines
    per FTE', zoals het plan aanvankelijk aannam."""
    maintenance = read_maintenance(workbook['OEE Model MST '])

    assert maintenance['fte'] == 9
    assert maintenance['machine_hours_total'] / 9 == pytest.approx(
        maintenance['machine_hours_per_fte'], rel=1e-4)
    assert maintenance['opex_total'] / 9 == pytest.approx(
        maintenance['opex_per_fte'], rel=1e-4)


def test_mapping_is_verified_against_the_masterdata_oee(workbook):
    model_machines = read_model_machines(workbook['OEE Model MST '])
    assert set(model_machines) == {'MRL', 'PM01', 'Pneu'}

    sap = {'PSS13': {'oee': 0.7}, 'PML01': {'oee': 0.8}, 'PPM09': {'oee': 0.8}}
    table = verify_mapping(model_machines, sap)
    joined = '\n'.join(table)

    assert '| MRL | PSS13 | 0.7 | 0.7 | 50 | OK |' in joined
    assert '| PM01 | PML01 | 0.8 | 0.8 | 3.5 | OK |' in joined
    # Pneu: model 0,7 vs masterdata 0,8 — moet als afwijking naar boven komen
    # in plaats van stilzwijgend te worden gekoppeld.
    assert 'Pneu' in joined and 'OEE WIJKT AF' in joined


def test_every_mapped_machine_has_a_unique_purpose():
    """Twee klantnamen mogen naar dezelfde SAP-machine wijzen (PE20 komt in het
    model zowel als big-bag- als als zaklijn voor), maar een SAP-code mag nooit
    leeg of onbekend zijn."""
    for name, (code, label) in MODEL_TO_SAP.items():
        assert code and code.isalnum(), f'{name} heeft geen bruikbare SAP-code'
        assert label, f'{name} heeft geen omschrijving'
