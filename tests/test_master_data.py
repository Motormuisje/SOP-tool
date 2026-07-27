"""Master-config vervanging — serialisatie, hydratie en de werkboek-vrije run.

Kerngarantie: de store bevat POST-PARSE data. serialize→JSON→hydrate levert
exact dezelfde DataLoader-structuren op als de xlsm-loaders (golden test);
de maandelijkse extract-loaders zijn gedeelde code voor beide paden, dus
structurele pariteit ⇒ enginepariteit bij gelijke extracts. Daarnaast een
volledige engine-run ZONDER enig werkboek (master dict + synthetische
extracts) als end-to-end-bewijs.
"""

import contextlib
import io
import json

import pytest

from tests.master_fixtures import fake_master_loader, write_extract_files

from modules.data_loader import DataLoader
from modules.master_data import (
    MASTER_SCHEMA_VERSION,
    finalize_shift_systems,
    hydrate_loader,
    serialize_master,
)
from modules.models import LineType, ShiftSystem


# ---------------------------------------------------------------- golden parity

def test_serialize_hydrate_round_trip_matches_xlsm_loader(golden_fixture_path):
    with contextlib.redirect_stdout(io.StringIO()):
        source = DataLoader(str(golden_fixture_path))
        source.load_all()

    master = json.loads(json.dumps(serialize_master(source), default=str))
    assert master['schema_version'] == MASTER_SCHEMA_VERSION

    target = DataLoader(master_data=master)
    with contextlib.redirect_stdout(io.StringIO()):
        hydrate_loader(target, master)
        finalize_shift_systems(target)

    assert target.config.initial_date == source.config.initial_date
    assert target.config.forecast_months == source.config.forecast_months
    assert target.config.site == source.config.site
    assert target.config.unlimited_capacity_machine == source.config.unlimited_capacity_machine
    assert target.forecast_actuals_months == source.forecast_actuals_months
    assert target.periods == source.periods
    assert target.purchased_and_produced == source.purchased_and_produced

    assert target.fte_hours_per_year == source.fte_hours_per_year
    assert target.shift_hours == source.shift_hours
    assert target.default_shift_name == source.default_shift_name

    assert target.materials == source.materials
    assert target.machines == source.machines
    assert target.machine_groups == source.machine_groups
    assert target.safety_stock == source.safety_stock
    assert target.purchase_lead_times == source.purchase_lead_times
    assert target.purchase_moq == source.purchase_moq
    assert target.purchase_sheet_materials == source.purchase_sheet_materials
    assert target.purchase_actuals == source.purchase_actuals
    assert target.sales_prices == source.sales_prices
    assert target.material_costs == source.material_costs
    assert target.machine_costs == source.machine_costs
    assert target.valuation_params == source.valuation_params


# --------------------------------------------------- werkboek-vrije engine-run

def test_full_engine_run_without_any_workbook(tmp_path):
    """Master store + maandelijkse extracts: geen basis-.xlsm meer nodig."""
    from modules.planning_engine import PlanningEngine

    master = json.loads(json.dumps(serialize_master(fake_master_loader()), default=str))
    extracts = write_extract_files(tmp_path)

    with contextlib.redirect_stdout(io.StringIO()):
        engine = PlanningEngine(
            None, planning_month=None, months_actuals=1, months_forecast=3,
            extract_files=extracts, master_data=master,
        )
        engine.run()

    assert engine.data.periods == ['2026-01', '2026-02', '2026-03']
    l01 = [r for r in engine.results[LineType.DEMAND_FORECAST.value]
           if r.material_number == 'M1']
    assert l01 and l01[0].values == {'2026-01': 100.0, '2026-02': 110.0, '2026-03': 120.0}

    # M1 is BOM-parent met routing → productie; M2 krijgt afhankelijke vraag.
    prod = [r for r in engine.results[LineType.PRODUCTION_PLAN.value]
            if r.material_number == 'M1']
    assert prod and sum(prod[0].values.values()) > 0
    dep = [r for r in engine.results[LineType.DEPENDENT_DEMAND.value]
           if r.material_number == 'M2' and r.aux_column == 'M1']
    assert dep, 'kind kreeg geen afhankelijke vraag zonder werkboek'

    # Machines + waardeplanning draaien mee vanuit de store.
    machine_rows = [r for r in engine.results[LineType.CAPACITY_UTILIZATION.value]
                    if r.product_type == 'Machine']
    assert machine_rows, 'machinerijen ontbreken in de werkboek-vrije run'
    assert engine.data.machines['PBA01'].shift_system == ShiftSystem.THREE_SHIFT
    value_l01 = [r for r in engine.value_results.get(LineType.DEMAND_FORECAST.value, [])
                 if r.material_number == 'M1']
    assert value_l01 and sum(value_l01[0].values.values()) == pytest.approx(12.0 * 330.0)


def test_master_store_persistence_round_trip(tmp_path):
    from ui.master_store import load_master_store, master_counts, save_master_store

    master = json.loads(json.dumps(serialize_master(fake_master_loader()), default=str))
    store_path = tmp_path / 'master_store.json'
    record = save_master_store(store_path, master, source_filename='MS_RECONC.xlsm')
    assert record['version'] == 1 and record['source_filename'] == 'MS_RECONC.xlsm'

    loaded = load_master_store(store_path)
    assert loaded['master'] == master
    counts = master_counts(loaded['master'])
    assert counts['materials'] == 2 and counts['machines'] == 1
    assert counts['valuation_params'] == 1

    # Bewerking: versie omhoog, import-metadata blijft, edited_at gezet.
    record2 = save_master_store(store_path, master, previous=loaded, edited=True)
    assert record2['version'] == 2
    assert record2['source_filename'] == 'MS_RECONC.xlsm'
    assert record2['edited_at']

    # Corrupt bestand → None + quarantaine, geen crash.
    store_path.write_text('{{{', encoding='utf-8')
    assert load_master_store(store_path) is None
    assert not store_path.exists()


def test_workbook_overlay_applies_app_edits(golden_fixture_path):
    """Gemelde bug: naam wijzigen in de masterdata-grid + herberekenen paste
    de naam niet toe op een werkboek-sessie. De app is de bron van waarheid:
    met een store overlayt die het werkboek — hernoemde materialen en
    app-only materialen komen door, werkboek-Config en transactiedata
    blijven van het werkboek."""
    from modules.master_data import overlay_master_data

    with contextlib.redirect_stdout(io.StringIO()):
        baseline = DataLoader(str(golden_fixture_path))
        baseline.load_all()

    master = json.loads(json.dumps(serialize_master(baseline), default=str))
    first_mn = master['materials'][0]['material_number']
    master['materials'][0]['name'] = 'HERNOEMD IN APP'
    master['materials'].append({**master['materials'][1],
                                'material_number': 'APPONLY1',
                                'name': 'App-only materiaal'})

    with contextlib.redirect_stdout(io.StringIO()):
        hybrid = DataLoader(str(golden_fixture_path), master_data=master)
        hybrid.load_all()

    # App wint per sleutel; app-only komt erbij; de rest is ongewijzigd.
    assert hybrid.materials[first_mn].name == 'HERNOEMD IN APP'
    assert 'APPONLY1' in hybrid.materials
    unchanged = [mn for mn in baseline.materials if mn != first_mn]
    for mn in unchanged[:25]:
        assert hybrid.materials[mn] == baseline.materials[mn]

    # Werkboek blijft leidend voor Config-ankers en transactiedata.
    assert hybrid.config.initial_date == baseline.config.initial_date
    assert hybrid.forecast_actuals_months == baseline.forecast_actuals_months
    assert hybrid.forecasts == baseline.forecasts
    assert hybrid.stock_levels == baseline.stock_levels
    assert len(hybrid.bom) == len(baseline.bom)


def test_workbook_session_rebuild_picks_up_store_edit(golden_fixture_path, tmp_path):
    """Route-niveau van de gemelde bug: een sessie MET werkboek herbouwt met
    de laatste app-masterdata zodra de store bestaat."""
    from ui import master_store
    from ui.engine_rebuild import build_clean_engine_for_session
    from ui.master_store import save_master_store

    with contextlib.redirect_stdout(io.StringIO()):
        loader = DataLoader(str(golden_fixture_path))
        loader.load_all()
    master = json.loads(json.dumps(serialize_master(loader), default=str))
    first_mn = master['materials'][0]['material_number']
    master['materials'][0]['name'] = 'HERNOEMD VIA STORE'

    store_path = tmp_path / 'master_store.json'
    save_master_store(store_path, master, source_filename='edit.xlsm')
    master_store.set_store_path(store_path)

    sess = {
        'id': 'wb', 'file_path': str(golden_fixture_path), 'extract_files': None,
        'parameters': {'planning_month': '2025-12', 'months_actuals': 11,
                       'months_forecast': 12},
        'pending_edits': {}, 'value_aux_overrides': {}, 'machine_overrides': {},
        'inventory_overrides': {}, 'capacity_overrides': {}, 'engine': None,
    }
    with contextlib.redirect_stdout(io.StringIO()):
        engine = build_clean_engine_for_session(sess, {})
    assert engine is not None
    assert engine.data.materials[first_mn].name == 'HERNOEMD VIA STORE'


# ------------------------------------------------- F2: storezuivering (maanddata)


@pytest.mark.no_fixture
def test_overlay_keeps_workbook_machine_availability():
    """De overlay verving hele Machine-objecten, waardoor geplande stilstand
    uit het VERSE werkboek werd overschreven door de bevroren importmaand-
    snapshot uit de store. Mastervelden (naam, OEE) komen uit de app;
    availability_by_period blijft maanddata van het werkboek."""
    from modules.master_data import overlay_master_data

    base = fake_master_loader()
    master = json.loads(json.dumps(serialize_master(base), default=str))

    # "Werkboek"-toestand: hydrate + verse geplande stilstand voor jan/feb.
    loader = DataLoader(master_data=master)
    with contextlib.redirect_stdout(io.StringIO()):
        hydrate_loader(loader, master)
    loader.machines['PBA01'].availability_by_period = {'2026-01': 0.5, '2026-02': 0.7}

    # Store-toestand: naam gewijzigd in de app, beschikbaarheid bevroren op 1.0,
    # plus een app-only machine.
    store = json.loads(json.dumps(master))
    store['machines'][0]['name'] = 'Press HERNOEMD'
    store['machines'].append({**store['machines'][0],
                              'machine_id': 'PBA02', 'machine_code': 'PBA02',
                              'name': 'App-only pers',
                              'availability_by_period': {'2026-01': 0.9}})

    with contextlib.redirect_stdout(io.StringIO()):
        overlay_master_data(loader, store)

    merged = loader.machines['PBA01']
    assert merged.name == 'Press HERNOEMD'          # masterveld: app wint
    assert merged.availability_by_period['2026-01'] == 0.5  # maanddata: werkboek wint
    assert merged.availability_by_period['2026-02'] == 0.7
    # App-only machine komt binnen mét zijn store-beschikbaarheid.
    assert loader.machines['PBA02'].availability_by_period['2026-01'] == 0.9


@pytest.mark.no_fixture
def test_forecast_align_flag_survives_store_round_trip():
    """forecast_align_to_month ontbrak in de serialisatie: werkboek-vrij viel
    de vlag altijd terug op de default en was de parallelle-run-validatie
    (positionele modus) onbereikbaar. Feature-gedetecteerd: werkt ook als
    PlanningConfig het veld (nog) niet als dataclass-veld heeft."""
    base = fake_master_loader()
    base.config.forecast_align_to_month = False

    master = json.loads(json.dumps(serialize_master(base), default=str))
    assert master['config']['forecast_align_to_month'] is False

    loader = DataLoader(master_data=master)
    with contextlib.redirect_stdout(io.StringIO()):
        hydrate_loader(loader, master)
    assert loader.config.forecast_align_to_month is False
