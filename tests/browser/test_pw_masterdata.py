"""Config-tab, sectie "Masterdata-tabellen" — browsertests op een live server.

Deze sectie is sinds C4b het ENIGE bewerkgebied voor de masterdata: één
knoppenrij (`_MASTER_DATASETS`), één inline grid (`openMasterDatasetModal`),
één collect/save-pad (`collectMasterDataset`/`saveMasterDataset`). Alles wat
hier stukgaat, gaat stil stuk: een dataset die niet meer opent, een filter dat
blijft hangen, een grid dat bij opslaan de 24 ongewijzigde rijen herschrijft of
een nieuwe F2-CF-rij die zonder identiteitsveld in de store belandt. De cijfers
zijn klantdata — dus wordt hier op WAARDEN in de store gecontroleerd, niet op
"de PATCH gaf 200".

Aanvullend op tests/browser/test_master_data.py (import/hernoemen, prijzen,
locale-parser, config-/FTE-formulier): dit bestand dekt de knoppenrij, het
filter, de versiebump, de weigering van ongeldige getallen, de
base_version-botsing, "+ rij toevoegen" bij de F2-CF-datasets (select-, csv- en
map-kolommen) en de aantallen op de statuskaart.
"""

import re

import pytest
import requests
from playwright.sync_api import expect

COMBI_KEY = "BROWSERTEST_COMBI"
NORM_KEY = "ZZZ_PACKGROUP01"
THROUGHPUT_KEY = "PBA11|150000276"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _open_config(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.evaluate("() => window.showTab && window.showTab('config')")
    page.wait_for_selector("#masterDataStatus", timeout=15000)


def _ensure_store(base_url, golden_fixture_path):
    """Masterdata moet in de app staan; de sessie start met een lege store."""
    status = requests.get(base_url + "/api/master_data", timeout=60).json()
    if status.get("exists"):
        return status
    with golden_fixture_path.open("rb") as workbook:
        resp = requests.post(base_url + "/api/master_data/import",
                             files={"file": (golden_fixture_path.name, workbook)},
                             timeout=600)
    assert resp.ok and resp.json().get("success"), resp.text
    return requests.get(base_url + "/api/master_data", timeout=60).json()


def _prepare(page, golden_fixture_path):
    page.reload(wait_until="networkidle")
    _open_config(page)
    _ensure_store(page.server["base_url"], golden_fixture_path)
    # alert()/notify() opvangen: de weiger- en conflictpaden melden zich daar.
    page.evaluate(
        """() => {
            window.__alerts = [];
            window.alert = (msg) => { window.__alerts.push(String(msg)); };
            window.__notes = [];
            const original = window.notify;
            window.notify = (msg, ...rest) => {
                window.__notes.push(String(msg));
                return original ? original(msg, ...rest) : undefined;
            };
        }""")
    page.evaluate("() => loadMasterDataStatus()")
    page.wait_for_function(
        "() => document.querySelectorAll('#masterDatasetButtons button').length > 0",
        timeout=30000)


def _dataset(base_url, name):
    body = requests.get(f"{base_url}/api/master_data/{name}", timeout=120).json()
    assert "error" not in body, body
    return body["value"]


def _version(base_url):
    return requests.get(base_url + "/api/master_data", timeout=60).json()["version"]


def _open_dataset(page, dataset):
    """openMasterDatasetModal is async; evaluate wacht de fetch + render af."""
    page.evaluate("(ds) => openMasterDatasetModal(ds)", dataset)
    page.wait_for_function(
        "() => document.getElementById('masterDatasetInline').style.display !== 'none'"
        " && document.getElementById('masterDatasetBody').innerHTML !== ''",
        timeout=30000)


def _save_dataset(page, dataset, *, expect_ok=True):
    """Klik op Opslaan-gedrag; retourneert (response, payload).

    Bij succes wordt gewacht tot het grid opnieuw geladen is op de NIEUWE
    storeversie — saveMasterDataset roept openMasterDatasetModal zonder await
    aan, dus zonder deze wachtvoorwaarde leest de volgende stap het oude grid.
    """
    with page.expect_response(
            lambda r, d=dataset: r.url.endswith(f"/api/master_data/{d}")
            and r.request.method == "PATCH", timeout=120000) as info:
        page.evaluate("(ds) => saveMasterDataset(ds)", dataset)
    response = info.value
    payload = response.json()
    if expect_ok:
        assert response.ok, payload
        page.wait_for_function(
            "(v) => typeof _masterDatasetCache !== 'undefined' && _masterDatasetCache"
            " && _masterDatasetCache.version === v",
            arg=payload["version"], timeout=30000)
    return response, payload


def _visible_keys(page):
    return set(page.evaluate(
        """() => [...document.querySelectorAll('#masterDatasetBody tr[data-master-key]')]
            .filter(row => row.style.display !== 'none')
            .map(row => row.dataset.masterKey)"""))


def _cell(key, column):
    return (f'#masterDatasetBody tr[data-master-key="{key}"] '
            f'[data-master-col="{column}"] .master-edit')


def _set_cell(page, key, column, value):
    page.fill(_cell(key, column), value)


# --------------------------------------------------------------------------
# 1. knoppenrij
# --------------------------------------------------------------------------

def test_elke_datasetknop_opent_zijn_eigen_grid(browser_page, golden_fixture_path):
    """Eén knop per dataset in `_MASTER_DATASETS`, en elke knop opent ZIJN grid.

    Zou een knop de verkeerde dataset openen of een dataset niet renderen
    (denk aan een nieuwe dataset zonder render-tak), dan bewerkt de gebruiker
    ongemerkt de verkeerde tabel of ziet hij een lege tabel terwijl de store
    vol staat. Daarom: titel, actieve markering én het AANTAL gerenderde rijen
    vergeleken met wat de API voor die dataset teruggeeft.
    """
    page = browser_page
    base_url = page.server["base_url"]
    _prepare(page, golden_fixture_path)

    specs = page.evaluate(
        "() => Object.entries(_MASTER_DATASETS)"
        ".map(([ds, s]) => [ds, s.label, s.kind, !!s.addable])")
    assert len(specs) >= 16, specs
    buttons = page.evaluate(
        "() => [...document.querySelectorAll('#masterDatasetButtons button')]"
        ".map(b => b.dataset.ds)")
    assert buttons == [spec[0] for spec in specs], \
        "de knoppenrij dekt niet exact (en in dezelfde volgorde) _MASTER_DATASETS"

    for dataset, label, kind, addable in specs:
        page.click(f'#masterDatasetButtons button[data-ds="{dataset}"]')
        page.wait_for_function(
            "(label) => document.getElementById('masterDatasetTitle').textContent === label"
            " && document.getElementById('masterDatasetBody').innerHTML !== ''",
            arg=label, timeout=30000)
        expect(page.locator("#masterDatasetInline")).to_be_visible()
        expect(page.locator("#masterDatasetFooter")).to_be_visible()

        # De actieve pill is de aangeklikte — en alleen die.
        outlined = page.evaluate(
            "() => [...document.querySelectorAll('#masterDatasetButtons button')]"
            ".filter(b => b.style.outline).map(b => b.dataset.ds)")
        assert outlined == [dataset], outlined

        value = _dataset(base_url, dataset)
        rows = page.locator("#masterDatasetBody tr[data-master-key]").count()
        fields = page.locator("#masterDatasetBody tr[data-master-field]").count()
        if kind in ("list", "dict", "sales_prices"):
            assert rows == len(value or []), f"{dataset}: {rows} rijen voor {len(value or [])} records"
        elif kind == "purchase":
            expected = len(set((value or {}).get("lead_times") or {})
                           | set((value or {}).get("moq") or {}))
            assert rows == expected, f"{dataset}: {rows} rijen, verwacht {expected}"
        else:  # config / fte / valuation_params: platte formulieren
            assert rows == 0 and fields > 0, f"{dataset}: {rows} rijen / {fields} velden"

        # "+ rij toevoegen" hoort exact bij de datasets zonder bron in de
        # maandextracts te staan (de F2-CF-tabellen).
        add_button = page.locator(
            '#masterDatasetBody button:has-text("+ rij toevoegen")').count()
        assert bool(add_button) is addable, f"{dataset}: toevoegknop {add_button}, addable={addable}"

    assert page.js_errors == []


# --------------------------------------------------------------------------
# 2. + 3. filter
# --------------------------------------------------------------------------

def _expected_visible(machines, query):
    """De filterregel, onafhankelijk nagerekend: sleutel + zichtbare
    invoerwaarden (naam, groep). Getalkolommen kunnen een alfabetische
    zoekterm nooit matchen."""
    needle = query.lower()
    out = set()
    for machine in machines:
        haystack = [str(machine.get("machine_code") or ""),
                    str(machine.get("name") or ""),
                    str(machine.get("machine_group") or "")]
        if any(needle in part.lower() for part in haystack):
            out.add(str(machine["machine_code"]))
    return out


def test_filterveld_filtert_op_sleutel_en_op_invoerwaarde(browser_page, golden_fixture_path):
    """Het filter moet ook op de INHOUD van de invoervelden matchen.

    Een filter dat alleen `textContent` bekijkt vindt alleen de sleutelkolom —
    zoeken op een machinenaam levert dan een lege tabel op terwijl de rij er
    gewoon staat, en de gebruiker concludeert dat de machine ontbreekt.
    """
    page = browser_page
    base_url = page.server["base_url"]
    _prepare(page, golden_fixture_path)

    machines = _dataset(base_url, "machines")
    assert len(machines) >= 5, "test heeft meerdere machines nodig"
    all_keys = {str(m["machine_code"]) for m in machines}
    _open_dataset(page, "machines")
    assert _visible_keys(page) == all_keys

    # 1) Zoeken op sleutel: exact de rijen die de term bevatten.
    key_query = str(machines[0]["machine_code"]).lower()
    assert re.search(r"[a-z]", key_query), key_query
    expected = _expected_visible(machines, key_query)
    assert 0 < len(expected) < len(all_keys)
    page.fill("#masterDatasetFilter", key_query)
    page.wait_for_function(
        "(n) => [...document.querySelectorAll('#masterDatasetBody tr[data-master-key]')]"
        ".filter(r => r.style.display !== 'none').length === n",
        arg=len(expected), timeout=15000)
    assert _visible_keys(page) == expected

    # 2) Zoeken op een woord uit de NAAM (staat alleen in het invoerveld).
    name_query, name_expected = None, None
    for machine in machines:
        for word in re.findall(r"[A-Za-z]{5,}", str(machine.get("name") or "")):
            candidate = word.lower()
            hits = _expected_visible(machines, candidate)
            if hits and len(hits) < len(all_keys) and any(candidate not in k.lower() for k in hits):
                name_query, name_expected = candidate, hits
                break
        if name_query:
            break
    assert name_query, "geen bruikbaar naamwoord in de machinemasterdata"
    page.fill("#masterDatasetFilter", name_query)
    page.wait_for_function(
        "(n) => [...document.querySelectorAll('#masterDatasetBody tr[data-master-key]')]"
        ".filter(r => r.style.display !== 'none').length === n",
        arg=len(name_expected), timeout=15000)
    assert _visible_keys(page) == name_expected
    assert any(name_query not in key.lower() for key in name_expected), \
        "deze zoekterm bewijst het invoerveld-pad niet"

    # 3) Geen treffers → lege tabel; leegmaken → alles terug.
    page.fill("#masterDatasetFilter", "XXNIETBESTAANDXX")
    page.wait_for_function(
        "() => [...document.querySelectorAll('#masterDatasetBody tr[data-master-key]')]"
        ".every(r => r.style.display === 'none')", timeout=15000)
    assert _visible_keys(page) == set()
    page.fill("#masterDatasetFilter", "")
    page.wait_for_function(
        "(n) => [...document.querySelectorAll('#masterDatasetBody tr[data-master-key]')]"
        ".filter(r => r.style.display !== 'none').length === n",
        arg=len(all_keys), timeout=15000)
    assert _visible_keys(page) == all_keys
    assert page.js_errors == []


def test_andere_dataset_openen_wist_het_actieve_filter(browser_page, golden_fixture_path):
    """Het filterveld hoort bij de GETOONDE tabel, niet bij de sectie.

    Blijft de zoekterm staan terwijl er een andere dataset wordt geladen, dan
    opent die tabel (deels) verborgen: de gebruiker ziet 3 van de 83
    grondstofkosten en denkt dat de rest weg is.
    """
    page = browser_page
    base_url = page.server["base_url"]
    _prepare(page, golden_fixture_path)

    machines = _dataset(base_url, "machines")
    material_costs = _dataset(base_url, "material_costs")
    assert len(material_costs) > 5, "test heeft een tweede, gevulde dataset nodig"

    _open_dataset(page, "machines")
    query = str(machines[0]["machine_code"]).lower()
    page.fill("#masterDatasetFilter", query)
    page.wait_for_function(
        "(n) => [...document.querySelectorAll('#masterDatasetBody tr[data-master-key]')]"
        ".filter(r => r.style.display !== 'none').length < n",
        arg=len(machines), timeout=15000)

    _open_dataset(page, "material_costs")
    assert page.locator("#masterDatasetFilter").input_value() == ""
    assert page.locator("#masterDatasetBody tr[data-master-key]").count() == len(material_costs)
    assert len(_visible_keys(page)) == len(material_costs), \
        "rijen bleven verborgen door het filter van de vorige tabel"
    assert page.js_errors == []


# --------------------------------------------------------------------------
# 4. bewerken + opslaan
# --------------------------------------------------------------------------

def test_bewerking_en_opslaan_bumpen_de_storeversie(browser_page, golden_fixture_path):
    """Opslaan vervangt de HELE dataset — dus moet één bewerkte cel landen en
    mag geen enkele andere rij veranderen.

    De storeversie is het signaal waarop instanties zich herberekenen en waarop
    de base_version-botsing draait; blijft die staan, dan denkt iedereen met de
    oude cijfers te werken (of erger: een tweede tabblad overschrijft ze stil).
    """
    page = browser_page
    base_url = page.server["base_url"]
    _prepare(page, golden_fixture_path)

    original = _dataset(base_url, "machine_costs")
    keys = sorted(original)
    assert len(keys) >= 2, "test heeft minstens 2 machinekosten nodig"
    target = keys[0]
    old_cost = float(original[target]["variable_cost_per_hour"])
    new_cost = round(old_cost + 7.25, 2)
    assert new_cost != old_cost

    try:
        _open_dataset(page, "machine_costs")
        version_before = _version(base_url)
        _set_cell(page, target, "variable_cost_per_hour", str(new_cost))
        _, payload = _save_dataset(page, "machine_costs")

        assert payload["version"] == version_before + 1
        assert _version(base_url) == version_before + 1

        after = _dataset(base_url, "machine_costs")
        assert float(after[target]["variable_cost_per_hour"]) == pytest.approx(new_cost)
        # Overige velden van de bewerkte rij blijven ongemoeid...
        assert after[target]["cost_center"] == original[target]["cost_center"]
        assert after[target]["plant_code"] == original[target]["plant_code"]
        # ...en de 24 ongewijzigde rijen komen EXACT terug.
        assert {k: v for k, v in after.items() if k != target} == \
               {k: v for k, v in original.items() if k != target}

        # De statuskaart toont de nieuwe versie zonder herladen.
        page.wait_for_function(
            "(v) => document.getElementById('masterDataStatus').textContent"
            ".includes('versie ' + v)", arg=payload["version"], timeout=15000)
        # En het herladen grid toont de opgeslagen waarde als nieuwe basis.
        assert page.locator(_cell(target, "variable_cost_per_hour")).input_value() \
            == str(new_cost)
    finally:
        requests.patch(base_url + "/api/master_data/machine_costs",
                       json={"value": original}, timeout=120)
    assert page.js_errors == []


# --------------------------------------------------------------------------
# 5. weigeringen
# --------------------------------------------------------------------------

def test_opslaan_met_ongeldig_getal_wordt_geweigerd(browser_page, golden_fixture_path):
    """Twee weigerpaden, beide met "er wordt NIETS opgeslagen" als eis.

    (a) tekst in een getalkolom wordt in de grid afgevangen — zonder die
    controle stuurt de client `null` mee en zou de hydratie er een 0 van maken;
    (b) een doorzet van 0 komt door de client heen maar is rekenkundig fataal
    (0 t/u = oneindig veel uren), dus de server weigert hem. In beide gevallen
    mag de storeversie niet bewegen.
    """
    page = browser_page
    base_url = page.server["base_url"]
    _prepare(page, golden_fixture_path)

    machines_before = _dataset(base_url, "machines")
    version_before = _version(base_url)
    target = str(machines_before[0]["machine_code"])

    # (a) client-side: 'abc' in de OEE-kolom.
    _open_dataset(page, "machines")
    _set_cell(page, target, "oee", "abc")
    page.evaluate("() => saveMasterDataset('machines')")
    alerts = page.evaluate("() => window.__alerts")
    assert alerts and alerts[-1].startswith("Ongeldige waarde"), alerts
    assert target in alerts[-1] and "OEE" in alerts[-1], alerts[-1]
    assert _version(base_url) == version_before, "geweigerde bewerking bumpte toch de versie"
    assert _dataset(base_url, "machines") == machines_before

    # (b) server-side: een nieuwe doorzet-override met 0 t/u.
    overrides_before = _dataset(base_url, "throughput_overrides")
    _open_dataset(page, "throughput_overrides")
    page.evaluate("([ds, key]) => _insertMasterRow(ds, key)",
                  ["throughput_overrides", THROUGHPUT_KEY])
    page.wait_for_selector(f'#masterDatasetBody tr[data-master-key="{THROUGHPUT_KEY}"]',
                           timeout=15000)

    # (b1) client-side: de LEGE doorzetcel is 'niet ingevuld' en wordt al vóór
    # de server geweigerd — leeg werd vroeger stil 0 opgeslagen (dat zette
    # elders zelfs de OEE-correctie uit). Er mag geen PATCH vertrekken.
    posted = []
    page.on("request", lambda req: posted.append(req.url)
            if req.method == "PATCH" else None)
    page.evaluate("() => saveMasterDataset('throughput_overrides')")
    page.wait_for_function(
        "() => (window.__alerts || []).some(a => a.includes('Ongeldige waarde'))",
        timeout=15000)
    assert [u for u in posted if "/api/master_data/" in u] == []

    # (b2) server-side: een EXPLICIETE 0 t/u passeert de client en wordt door
    # de server met 400 geweigerd.
    page.evaluate(
        """(key) => {
            const cell = document.querySelector(
                `#masterDatasetBody tr[data-master-key="${key}"] [data-master-col="throughput_t_per_hour"] .master-edit`);
            cell.value = '0';
            cell.dispatchEvent(new Event('input', { bubbles: true }));
        }""", THROUGHPUT_KEY)
    response, payload = _save_dataset(page, "throughput_overrides", expect_ok=False)
    assert response.status == 400, payload
    assert "doorzet moet groter dan 0" in payload.get("error", ""), payload
    assert page.evaluate("() => window.__alerts")[-1] == payload["error"]
    assert _version(base_url) == version_before
    assert _dataset(base_url, "throughput_overrides") == overrides_before
    assert page.js_errors == []


def test_opslaan_op_een_verouderde_storeversie_wordt_geweigerd(browser_page,
                                                               golden_fixture_path):
    """Een PATCH vervangt de hele dataset, dus een grid dat op een oudere
    versie is geladen zou de wijziging van een tweede tabblad stil terugdraaien
    — met een 200 en een versiebump. De base_version-controle moet dat blokken
    én de wijziging van de ander laten staan.
    """
    page = browser_page
    base_url = page.server["base_url"]
    _prepare(page, golden_fixture_path)

    original = _dataset(base_url, "machine_costs")
    keys = sorted(original)
    assert len(keys) >= 2
    mine, theirs = keys[0], keys[1]
    try:
        _open_dataset(page, "machine_costs")  # grid staat nu op versie V
        loaded_version = page.evaluate("() => _masterDatasetCache.version")

        # "Het andere tabblad" wijzigt dezelfde dataset.
        out_of_band = {k: dict(v) for k, v in original.items()}
        out_of_band[theirs]["variable_cost_per_hour"] = 123.45
        resp = requests.patch(base_url + "/api/master_data/machine_costs",
                              json={"value": out_of_band}, timeout=120)
        assert resp.ok, resp.text
        conflicting_version = resp.json()["version"]
        assert conflicting_version == loaded_version + 1

        # Onze bewerking op het verouderde grid moet stuklopen.
        _set_cell(page, mine, "variable_cost_per_hour", "999")
        response, payload = _save_dataset(page, "machine_costs", expect_ok=False)
        assert response.status == 409, payload
        assert "gewijzigd" in payload.get("error", ""), payload
        assert page.evaluate("() => window.__alerts")[-1] == payload["error"]

        after = _dataset(base_url, "machine_costs")
        assert _version(base_url) == conflicting_version, "de conflict-PATCH bumpte toch"
        assert float(after[theirs]["variable_cost_per_hour"]) == pytest.approx(123.45), \
            "de wijziging van het andere tabblad is stil overschreven"
        assert float(after[mine]["variable_cost_per_hour"]) == \
            pytest.approx(float(original[mine]["variable_cost_per_hour"]))
    finally:
        requests.patch(base_url + "/api/master_data/machine_costs",
                       json={"value": original}, timeout=120)
    assert page.js_errors == []


# --------------------------------------------------------------------------
# 7. + 8. rij toevoegen bij de F2-CF-datasets
# --------------------------------------------------------------------------

def test_bemensingsnorm_toevoegen_met_select_kolom(browser_page, golden_fixture_path):
    """De F2-CF-datasets hebben geen bron in de maandextracts: zonder "+ rij
    toevoegen" is een bemensingsnorm alleen via het masterwerkboek aan te
    maken. De nieuwe rij moet compleet zijn — inclusief het identiteitsveld
    `code` uit de sleutel, want een record zonder code laat de hele store
    weigeren bij hydratie.

    Het bereik is een select met precies de twee toegestane waarden; vrije
    tekst ('groep') komt anders door de typecast heen en zet de norm stil uit.
    """
    page = browser_page
    base_url = page.server["base_url"]
    _prepare(page, golden_fixture_path)

    original = _dataset(base_url, "staffing_norms")
    assert NORM_KEY not in original, "testsleutel bestaat al in de store"
    try:
        _open_dataset(page, "staffing_norms")
        before_rows = page.locator("#masterDatasetBody tr[data-master-key]").count()
        page.evaluate("([ds, key]) => _insertMasterRow(ds, key)",
                      ["staffing_norms", NORM_KEY])
        page.wait_for_selector(f'#masterDatasetBody tr[data-master-key="{NORM_KEY}"]',
                               timeout=15000)
        assert page.locator("#masterDatasetBody tr[data-master-key]").count() == before_rows + 1

        # Defaults uit `identity` staan er meteen in.
        assert page.locator(_cell(NORM_KEY, "operators_per_hour")).input_value() == "1"
        scope = page.evaluate(
            """(key) => {
                const sel = document.querySelector(
                    `#masterDatasetBody tr[data-master-key="${key}"] [data-master-col="scope"] select`);
                return sel && { value: sel.value, options: [...sel.options].map(o => o.value) };
            }""", NORM_KEY)
        assert scope == {"value": "group", "options": ["group", "machine"]}

        # Dezelfde sleutel nog eens: geen dubbele rij, wel een melding.
        page.evaluate("([ds, key]) => _insertMasterRow(ds, key)",
                      ["staffing_norms", NORM_KEY])
        assert page.locator("#masterDatasetBody tr[data-master-key]").count() == before_rows + 1
        notes = page.evaluate("() => window.__notes")
        assert notes and "staat al in de tabel" in notes[-1], notes

        # Invullen (NL-komma in het getal) en opslaan.
        page.select_option(_cell(NORM_KEY, "scope"), "machine")
        _set_cell(page, NORM_KEY, "operators_per_hour", "1,5")
        _set_cell(page, NORM_KEY, "function_group", "Verpakking")
        version_before = _version(base_url)
        _, payload = _save_dataset(page, "staffing_norms")
        assert payload["version"] == version_before + 1

        after = _dataset(base_url, "staffing_norms")
        assert after[NORM_KEY] == {
            "code": NORM_KEY, "operators_per_hour": 1.5, "scope": "machine",
            "function_group": "Verpakking", "description": "",
        }
        assert {k: v for k, v in after.items() if k != NORM_KEY} == original
        assert payload["counts"]["staffing_norms"] == len(original) + 1
        # Na het herladen staat de rij er nog, met de opgeslagen waarden.
        assert page.locator(_cell(NORM_KEY, "operators_per_hour")).input_value() == "1.5"
        assert page.locator(_cell(NORM_KEY, "scope")).input_value() == "machine"
    finally:
        requests.patch(base_url + "/api/master_data/staffing_norms",
                       json={"value": original}, timeout=120)
    assert page.js_errors == []


def test_machinecombinatie_toevoegen_met_csv_en_map_kolommen(browser_page,
                                                             golden_fixture_path):
    """Een combinatie draagt twee samengestelde kolommen: de machinelijst
    (csv) en de factor per machine (map).

    De map-kolom gebruikt de komma als scheider, dus 'PBA20:0,75' MOET
    geweigerd worden — stil doorlaten maakt er factor 0 van (halve doorzet
    wordt geen doorzet) en dat is precies het soort fout dat niemand meer
    terugvindt. Onbekende machinecodes mogen wél opgeslagen worden, maar niet
    zonder waarschuwing: de combinatie doet dan niets.
    """
    page = browser_page
    base_url = page.server["base_url"]
    _prepare(page, golden_fixture_path)

    original = _dataset(base_url, "machine_combinations")
    assert COMBI_KEY not in original
    machine_codes = [str(m["machine_code"]) for m in _dataset(base_url, "machines")]
    first, second = machine_codes[0], machine_codes[1]
    try:
        _open_dataset(page, "machine_combinations")
        page.evaluate("([ds, key]) => _insertMasterRow(ds, key)",
                      ["machine_combinations", COMBI_KEY])
        page.wait_for_selector(f'#masterDatasetBody tr[data-master-key="{COMBI_KEY}"]',
                               timeout=15000)
        # Defaults: doorzetfactor 1 (0 zou geweigerd worden) en beschikbaar.
        assert page.locator(_cell(COMBI_KEY, "throughput_factor")).input_value() == "1"
        assert page.locator(_cell(COMBI_KEY, "operators")).input_value() == "1"
        assert page.locator(_cell(COMBI_KEY, "is_active")).is_checked()

        # Decimale komma in de map-kolom: geweigerd, niets opgeslagen.
        _set_cell(page, COMBI_KEY, "name", "Browsertest combi")
        _set_cell(page, COMBI_KEY, "machine_codes", f"{first}, {second}")
        _set_cell(page, COMBI_KEY, "throughput_factor_by_machine", f"{second}:0,75")
        error = page.evaluate(
            "() => (collectMasterDataset('machine_combinations').error || '')")
        assert error.startswith("Ongeldige waarde"), error
        assert COMBI_KEY in error and "Factor per machine" in error, error
        assert _dataset(base_url, "machine_combinations") == original

        # Onbekende machine: opslaan mag, maar met waarschuwing.
        _set_cell(page, COMBI_KEY, "throughput_factor_by_machine", f"{second}:0.75")
        _set_cell(page, COMBI_KEY, "machine_codes", f"{first}, NIETBESTAAND01")
        _, payload = _save_dataset(page, "machine_combinations")
        assert any("NIETBESTAAND01" in warning for warning in payload.get("warnings", [])), \
            payload.get("warnings")
        assert any("NIETBESTAAND01" in note for note in page.evaluate("() => window.__notes"))

        # Echte machines: csv splitst op komma EN trimt de spatie.
        _set_cell(page, COMBI_KEY, "machine_codes", f"{first}, {second}")
        _set_cell(page, COMBI_KEY, "operators", "2")
        _set_cell(page, COMBI_KEY, "throughput_factor", "0.9")
        _, payload = _save_dataset(page, "machine_combinations")
        assert not payload.get("warnings"), payload.get("warnings")

        after = _dataset(base_url, "machine_combinations")
        assert after[COMBI_KEY] == {
            "combination_id": COMBI_KEY, "name": "Browsertest combi",
            "machine_codes": [first, second], "operators": 2,
            "throughput_factor": 0.9, "throughput_factor_by_machine": {second: 0.75},
            "function_group": "", "description": "", "is_active": True,
        }
        assert {k: v for k, v in after.items() if k != COMBI_KEY} == original
        # Het herladen grid toont de lijst weer als komma-tekst.
        assert page.locator(_cell(COMBI_KEY, "machine_codes")).input_value() \
            == f"{first}, {second}"
    finally:
        requests.patch(base_url + "/api/master_data/machine_combinations",
                       json={"value": original}, timeout=120)
    assert page.js_errors == []


# --------------------------------------------------------------------------
# 9. statuskaart
# --------------------------------------------------------------------------

def test_statuskaart_toont_de_aantallen_van_de_store(browser_page, golden_fixture_path):
    """De statuskaart is de enige plek waar iemand ziet HOEVEEL masterdata er
    in de app zit; klopt een aantal niet, dan wordt een halve import niet
    opgemerkt. Daarom tellen we elke dataset zelf na en controleren we dat de
    kaart meebeweegt met een echte bewerking: een lead time op 0 zetten haalt
    de regel uit `lead_times`, dus het aantal inkoopregels moet dalen.
    """
    page = browser_page
    base_url = page.server["base_url"]
    _prepare(page, golden_fixture_path)

    status = requests.get(base_url + "/api/master_data", timeout=60).json()
    counts = status["counts"]
    purchase = _dataset(base_url, "purchase")

    # Elk getal onafhankelijk nageteld op de dataset zelf.
    assert counts["materials"] == len(_dataset(base_url, "materials")) > 0
    assert counts["machines"] == len(_dataset(base_url, "machines")) > 0
    assert counts["safety_stock"] == len(_dataset(base_url, "safety_stock")) > 0
    assert counts["sales_prices"] == len(_dataset(base_url, "sales_prices")) > 0
    assert counts["material_costs"] == len(_dataset(base_url, "material_costs")) > 0
    assert counts["machine_costs"] == len(_dataset(base_url, "machine_costs")) > 0
    assert counts["purchase"] == len(purchase["lead_times"]) > 0, \
        "inkoopregels tellen de lead times, niet de MOQ's"
    for dataset in ("staffing_norms", "labor_rates", "machine_combinations",
                    "indirect_activities", "throughput_overrides",
                    "benchmark_throughput"):
        assert counts[dataset] == len(_dataset(base_url, dataset)), dataset

    card = page.locator("#masterDataStatus").inner_text()
    for number, noun in ((counts["materials"], "materialen"),
                         (counts["machines"], "machines"),
                         (counts["safety_stock"], "veiligheidsvoorraden"),
                         (counts["purchase"], "inkoopregels"),
                         (counts["sales_prices"], "prijzen")):
        assert f"{number} {noun}" in card, (noun, card)
    assert f"versie {status['version']}" in card
    assert status["source_filename"] in card

    # Een materiaal met een ECHTE lead time bewerken (0 -> 5 zou samenvallen
    # met de gemelde bevinding hieronder en niets bewijzen).
    target = sorted(key for key, lead in purchase["lead_times"].items() if lead > 0)[0]
    positive_leads = {key for key, lead in purchase["lead_times"].items() if lead > 0}
    try:
        _open_dataset(page, "purchase")
        assert float(page.locator(_cell(target, "lead")).input_value()) \
            == float(purchase["lead_times"][target])
        _set_cell(page, target, "lead", "5")
        _, payload = _save_dataset(page, "purchase")

        after = _dataset(base_url, "purchase")
        assert after["lead_times"][target] == 5
        # Alle overige ingevulde lead times overleven de round-trip ongewijzigd.
        assert positive_leads <= set(after["lead_times"])
        for key, lead in after["lead_times"].items():
            if key != target:
                assert lead == purchase["lead_times"][key], key
        # MOQ's en actuals mogen niet meeveranderen door een lead-time-edit.
        assert after["moq"] == pytest.approx(
            {k: v for k, v in purchase["moq"].items() if v > 0})
        assert after["actuals"] == purchase["actuals"]
        assert after["sheet_materials"] == sorted(after["moq"])

        # De kaart telt wat er ECHT in de store staat — ook nadat het opslaan
        # de regels met lead time 0 heeft laten vallen (gemelde bevinding:
        # `collectMasterDataset` bewaart alleen lead > 0, terwijl
        # `get_lead_time` een ONTBREKEND materiaal op 1 maand zet).
        assert payload["counts"]["purchase"] == len(after["lead_times"])
        assert payload["counts"]["purchase"] <= counts["purchase"]
        page.wait_for_function(
            "(text) => document.getElementById('masterDataStatus').textContent.includes(text)",
            arg=f"{payload['counts']['purchase']} inkoopregels", timeout=15000)
    finally:
        requests.patch(base_url + "/api/master_data/purchase",
                       json={"value": purchase}, timeout=120)
    assert page.js_errors == []


def test_config_submenu_overlapt_de_tabellen_niet(browser_page, golden_fixture_path):
    """Het sticky submenu wordt bij scrollen position:fixed; zonder
    plaatshouder verliet het de flex-rij, schoof de tabellenkaart naar links
    en zweefde het menu transparant over de rijen heen (schermafdruk klant
    2026-08-06). De plaatshouder houdt de 200px vast en de kaart mag het
    menu nooit horizontaal snijden."""
    page = browser_page
    _prepare(page, golden_fixture_path)
    # Bemensingsnormen zijn leeg in een verse teststore (geen bron in de
    # maandextracts); het grid zelf — kop plus lege tabel — is genoeg om de
    # kaartbreedte en het menu te toetsen.
    page.evaluate("() => openMasterDatasetModal('staffing_norms')")
    page.wait_for_selector("#masterDatasetBody table", timeout=30000)

    # Naar de tabellenkaart scrollen zoals de gebruiker: venster-scroll.
    page.evaluate(
        """() => {
            const card = document.getElementById('cfgsec-tabellen');
            window.scrollTo(0, card.getBoundingClientRect().top + window.scrollY - 40);
        }""")
    page.wait_for_function(
        "() => document.getElementById('cfgNav').style.position === 'fixed'",
        timeout=10000)

    geom = page.evaluate(
        """() => {
            const nav = document.getElementById('cfgNav').getBoundingClientRect();
            const card = document.getElementById('cfgsec-tabellen').getBoundingClientRect();
            const spacer = document.getElementById('cfgNavSpacer');
            return {
                spacerZichtbaar: spacer && spacer.style.display === 'block',
                navRechts: nav.right, kaartLinks: card.left,
                achtergrond: getComputedStyle(document.getElementById('cfgNav')).backgroundColor,
            };
        }""")
    assert geom["spacerZichtbaar"] is True, "plaatshouder staat niet aan in fixed-toestand"
    assert geom["navRechts"] <= geom["kaartLinks"] + 1, (
        f"menu ({geom['navRechts']:.0f}px) snijdt de tabellenkaart ({geom['kaartLinks']:.0f}px)")
    assert geom["achtergrond"] not in ("rgba(0, 0, 0, 0)", "transparent"), (
        "fixed menu heeft geen dekkende achtergrond")

    # Terug omhoog: alles netjes terug naar de normale toestand.
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_function(
        "() => document.getElementById('cfgNav').style.position !== 'fixed'",
        timeout=10000)
    assert page.evaluate(
        "() => document.getElementById('cfgNavSpacer').style.display") == "none"
    assert page.js_errors == []


def test_fte_formulier_heeft_ploegselector_en_uitleg_per_regel(browser_page, golden_fixture_path):
    """Klantvraag 2026-08-06: het standaard ploegensysteem is een keuze uit de
    bestaande vensters (vrije tekst viel bij een typfout stil terug op de
    motor-default), en elke regel draagt rechts de uitleg hoe het getal in de
    berekening wordt gebruikt."""
    page = browser_page
    _prepare(page, golden_fixture_path)
    _open_dataset(page, "fte")

    report = page.evaluate(
        """() => {
            const row = document.querySelector('#masterDatasetBody tr[data-master-field="default_shift_name"]');
            const select = row && row.cells[1].querySelector('select.master-edit');
            const fte = _masterDatasetCache.value;
            const rows = [...document.querySelectorAll(
                '#masterDatasetBody tr[data-master-field], #masterDatasetBody tr[data-master-shift], #masterDatasetBody tr[data-master-param]')];
            return {
                isSelect: !!select,
                options: select ? [...select.options].map(o => o.value) : [],
                gekozen: select ? select.value : null,
                verwacht: Object.keys(fte.shift_hours || {}),
                huidig: fte.default_shift_name,
                totaal: rows.length,
                metUitleg: rows.filter(r => (r.cells[2]?.textContent || '').trim().length > 10).length,
            };
        }""")
    assert report["isSelect"], "standaard ploegensysteem is geen selector"
    assert set(report["verwacht"]).issubset(set(report["options"])), report
    assert report["gekozen"] == report["huidig"], "selector staat niet op de huidige waarde"
    # Elke invoerregel (velden, ploegvensters, parameters) draagt uitleg.
    assert report["totaal"] > 8
    assert report["metUitleg"] == report["totaal"], report

    # De selector overleeft de save-roundtrip: opslaan zonder wijziging laat
    # de waarde exact staan (bewaakt dat collect het select-veld goed leest).
    response, payload = _save_dataset(page, "fte")
    assert payload.get("success"), payload
    import requests as _rq
    fte = _rq.get(page.server["base_url"] + "/api/master_data/fte", timeout=60).json()["value"]
    assert fte["default_shift_name"] == report["huidig"]
    assert page.js_errors == []
