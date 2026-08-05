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
def test_overlay_refuses_a_store_from_another_site():
    """De sitepoort. Zonder deze poort mengde de overlay machines van twee
    sites (PML01-03 bestaan op meerdere sites: de store-machine VERVING de
    werkboekmachine, met de OEE en groepsindeling van de verkeerde site) en
    liet hij Maastricht-bemensingsnormen stil op de groepen van een andere
    site los. Gezien in het echt: een NLK1-werkboeksessie in de gedeelde
    datamap, gebouwd tegen de NLX1-store (v109)."""
    from modules.master_data import overlay_master_data

    base = fake_master_loader()
    master = json.loads(json.dumps(serialize_master(base), default=str))

    loader = DataLoader(master_data=master)
    with contextlib.redirect_stdout(io.StringIO()):
        hydrate_loader(loader, master)
    loader.config.site = 'NLK1'  # het werkboek verklaart een andere site
    machines_before = {code: machine.name for code, machine in loader.machines.items()}
    norms_before = dict(getattr(loader, 'staffing_norms', None) or {})

    store = json.loads(json.dumps(master))
    store['config']['site'] = 'NLX1'
    store['machines'][0]['name'] = 'Vreemde-site-machine'
    store['machines'].append({**store['machines'][0],
                              'machine_id': 'PZZ99', 'machine_code': 'PZZ99',
                              'name': 'Machine van de andere site'})
    store['staffing_norms'] = {'ZZ_GROUP01': {
        'code': 'ZZ_GROUP01', 'operators_per_hour': 3.0, 'scope': 'group'}}

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        overlay_master_data(loader, store)

    assert loader.master_overlay_skipped == {'store_site': 'NLX1',
                                             'workbook_site': 'NLK1'}
    assert 'overlay overgeslagen' in output.getvalue()
    # Niets van de vreemde store is binnengekomen: geen vervangen naam, geen
    # extra machine, geen normen.
    assert {c: m.name for c, m in loader.machines.items()} == machines_before
    assert 'PZZ99' not in loader.machines
    assert dict(getattr(loader, 'staffing_norms', None) or {}) == norms_before


@pytest.mark.no_fixture
def test_overlay_applies_when_sites_match_and_clears_the_flag():
    """Dezelfde site (of een store zonder site: geen identiteit om tegen te
    toetsen) moet gewoon blijven overlayen — de poort mag het normale pad
    niet raken, en een eerder gezette vlag moet worden gewist."""
    from modules.master_data import overlay_master_data

    base = fake_master_loader()
    master = json.loads(json.dumps(serialize_master(base), default=str))

    for store_site in (master['config'].get('site') or 'NLX1', ''):
        loader = DataLoader(master_data=master)
        with contextlib.redirect_stdout(io.StringIO()):
            hydrate_loader(loader, master)
        loader.master_overlay_skipped = {'store_site': 'X', 'workbook_site': 'Y'}

        store = json.loads(json.dumps(master))
        store['config']['site'] = store_site
        store['machines'][0]['name'] = 'App-naam'

        with contextlib.redirect_stdout(io.StringIO()):
            overlay_master_data(loader, store)

        first = store['machines'][0]['machine_code']
        assert loader.machines[first].name == 'App-naam', f'store_site={store_site!r}'
        assert loader.master_overlay_skipped is None


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


@pytest.mark.no_fixture
def test_overlay_applies_structural_config_from_store():
    """Masterdata-tabellen = enige bron van waarheid: unlimited-machines en
    forecast-uitlijning uit de store gelden ook op werkboeksessies via de
    overlay; kalenderankers en site blijven van het werkboek (die sturen de
    load zelf)."""
    from modules.data_loader import DataLoader
    from modules.master_data import overlay_master_data
    from modules.models import ShiftSystem

    base = fake_master_loader()
    master = json.loads(json.dumps(serialize_master(base), default=str))
    loader = DataLoader(master_data=master)
    with contextlib.redirect_stdout(io.StringIO()):
        hydrate_loader(loader, master)
    # "Werkboek"-staat: geen unlimited, uitlijning aan.
    assert loader.machines['PBA01'].shift_system == ShiftSystem.THREE_SHIFT

    store = json.loads(json.dumps(master))
    store['config']['unlimited_capacity_machine'] = ['PBA01']
    store['config']['forecast_align_to_month'] = False
    store['config']['purchased_and_produced'] = {'MAT-X': 0.4}
    # Site blijft die van het werkboek. Een AFWIJKENDE site testen kan hier
    # niet meer: sinds de sitepoort weigert de overlay dan integraal (zie
    # test_overlay_refuses_a_store_from_another_site) — een strikt sterkere
    # garantie dan alleen het siteveld met rust laten.
    store['config']['forecast_actuals_months'] = 3
    original_anchor = loader.config.initial_date
    original_site = loader.config.site
    original_actuals = loader.forecast_actuals_months
    with contextlib.redirect_stdout(io.StringIO()):
        overlay_master_data(loader, store)

    assert loader.config.unlimited_capacity_machine == ['PBA01']
    assert loader.machines['PBA01'].shift_system == ShiftSystem.UNLIMITED
    assert loader.config.forecast_align_to_month is False
    assert loader.purchased_and_produced == {'MAT-X': 0.4}
    assert loader.config.initial_date == original_anchor  # anker onaangetast
    assert loader.config.site == original_site
    assert loader.forecast_actuals_months == original_actuals  # anker idem


@pytest.mark.no_fixture
def test_overlay_pap_respects_session_override():
    '''Sessie-wat-als (PAP-override) wint van de masterdefault. Regressie:
    de overlay draait in load_all NA _apply_config_overrides en clobberde de
    override bij elke rebuild van een werkboek+store-sessie.'''
    from modules.data_loader import DataLoader
    from modules.master_data import overlay_master_data

    base = fake_master_loader()
    master = json.loads(json.dumps(serialize_master(base), default=str))
    loader = DataLoader(master_data=master,
                        config_overrides={'purchased_and_produced': 'MAT-X:0.9'})
    with contextlib.redirect_stdout(io.StringIO()):
        hydrate_loader(loader, master)
    loader._apply_pap_override(replace=True)  # zoals load_all op het storepad
    assert loader.purchased_and_produced['MAT-X'] == 0.9

    store = json.loads(json.dumps(master))
    store['config']['purchased_and_produced'] = {'MAT-X': 0.4, 'MAT-Y': 0.2}
    with contextlib.redirect_stdout(io.StringIO()):
        overlay_master_data(loader, store)
    # De override is de VOLLEDIGE PAP-set van de sessie: MAT-X wint met 0.9
    # en het via de editor verwijderde MAT-Y komt niet terug uit de store.
    assert loader.purchased_and_produced == {'MAT-X': 0.9}

    # Alles gewist ('' = bewust leeg) blijft ook echt leeg.
    loader.config_overrides['purchased_and_produced'] = ''
    with contextlib.redirect_stdout(io.StringIO()):
        overlay_master_data(loader, store)
    assert loader.purchased_and_produced == {}

    # Zonder override (nooit gezet) geldt de masterdefault onverkort.
    loader.config_overrides.pop('purchased_and_produced')
    with contextlib.redirect_stdout(io.StringIO()):
        overlay_master_data(loader, store)
    assert loader.purchased_and_produced == {'MAT-X': 0.4, 'MAT-Y': 0.2}
