"""Sessies (instanties) en scenario's — een gescripte werksessie in de browser.

De consultant houdt varianten uit elkaar met INSTANTIES (hernoemen, "Opslaan als
instantie", wisselen) en met SCENARIO'S (opslaan, laden, vergelijken). Beide
raken de gekoppelde state-lagen uit docs/ontwikkelhandleiding.md: sessie-dict, live engine en
`sessions_store.json`. Gaat daar iets stuk, dan ziet de gebruiker geen foutmelding
maar STIL verkeerde cijfers — een kopie die anders rekent dan zijn bron, een
scenario dat een bewerking laat staan, of een instantiewissel die de vorige
cijfers blijft tonen.

Daarom controleert elke stap hier het GETAL uit `/api/results` van de ACTIEVE
sessie, niet alleen de tekst in de zijbalk.

Draait op een EIGEN server (`own_server`): deze module dupliceert instanties,
hernoemt ze en laadt scenario's. Op de gedeelde server zou de uitkomst afhangen
van wat er eerder in de suite draaide. De tests bouwen bewust op elkaar voort
(genummerd; draaien met `-p no:randomly`), zoals `test_fte_worksession.py`.
"""

import json
import re
import time

import pytest
import requests
from playwright.sync_api import expect

TIMEOUT = 300
DEMAND = "01. Demand forecast"
TOTAL_DEMAND = "03. Total demand"

CELL = (
    '#planBody td.editable-cell[data-tt="val"]'
    f'[data-lt="{DEMAND}"][data-period]'
)

NAME_A = "Instantie A (hernoemd)"
NAME_B = "Instantie B (kopie)"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ctx(own_server):
    """Draagt sessie- en scenario-id's tussen de genummerde stappen."""
    return {"server": own_server}


@pytest.fixture
def app_page(page, own_server):
    """Een verse pagina op de EIGEN server, met console-bewaking.

    Zelfde opzet als `browser_page` uit conftest.py, maar tegen `own_server`;
    die fixture is aan de gedeelde `server` gekoppeld en die mogen deze
    stateful stappen niet aanraken.
    """
    js_errors = []

    def collect_console_error(message):
        if message.type == "error":
            if not message.text.startswith("Failed to load resource:"):
                js_errors.append(message.text)

    page.on("console", collect_console_error)
    response = page.goto(own_server["base_url"], wait_until="networkidle")
    assert response is not None and response.ok
    page.js_errors = js_errors
    page.server = own_server
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=120000)
    page.wait_for_function("() => !!state.results", timeout=300000)
    return page


# --------------------------------------------------------------------------
# Serverkant: getallen ophalen en vergelijken
# --------------------------------------------------------------------------

def _get(server, path):
    response = requests.get(server["base_url"] + path, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def _results(server):
    """De planningregels van de ACTIEVE sessie."""
    return _get(server, "/api/results")["results"]


def _rows(results, line_type):
    return [
        (str(row["material_number"]), str(row.get("aux_column") or ""), dict(row["values"]))
        for row in results.get(line_type, [])
    ]


def _total(results, line_type):
    return sum(sum(row["values"].values()) for row in results.get(line_type, []))


def _value_of(results, line_type, material, period):
    for row in results.get(line_type, []):
        if str(row["material_number"]) == str(material):
            return float(row["values"].get(period, 0.0))
    raise AssertionError(f"{line_type}: materiaal {material} niet gevonden")


def _differing_cells(rows_a, rows_b, tol=0.01):
    """Cellen die tussen twee momentopnamen afwijken.

    De app noemt zelf pas iets een verschil boven 0,01 (_build_diff_rows in
    ui/routes/scenarios.py); die drempel houden we aan.
    """
    assert len(rows_a) == len(rows_b), (
        f"ander aantal regels: {len(rows_a)} vs {len(rows_b)}")
    differing = []
    for (mat_a, aux_a, values_a), (mat_b, aux_b, values_b) in zip(rows_a, rows_b):
        assert (mat_a, aux_a) == (mat_b, aux_b), (
            f"regelvolgorde wijkt af: {mat_a}/{aux_a} vs {mat_b}/{aux_b}")
        for period, value in values_a.items():
            other = values_b.get(period, 0.0)
            if abs(value - other) > tol:
                differing.append((mat_a, period, value, other))
    return differing


def _sessions(server):
    return _get(server, "/api/sessions")


def _session_entry(server, session_id):
    body = _sessions(server)
    for group in body.get("groups", {}).values():
        for entry in group:
            if entry["id"] == session_id:
                return entry
    return None


def _wait_until_warm(server, session_id, seconds=600):
    """Wacht tot een gedupliceerde (koude) instantie klaar is met opwarmen.

    De opwarming draait in een achtergrondthread en meldt zich via
    `restore_status` in /api/sessions; dat is de enige echte voortgangsbron
    (dezelfde aanpak als `_poll_home` in conftest.py). Pollen dus, met een
    deadline — geen vaste wachttijd.
    """
    deadline = time.monotonic() + seconds
    status = None
    while time.monotonic() < deadline:
        status = (_session_entry(server, session_id) or {}).get("restore_status")
        if status in ("ready", "failed"):
            return status
        time.sleep(0.5)
    return status


# --------------------------------------------------------------------------
# Browserkant: tabbladen, bewerken, wisselen, scenario's
# --------------------------------------------------------------------------

def _session_item(page, session_id):
    return page.locator(
        f'.session-item:has(.session-name-edit[data-session-id="{session_id}"])')


def _switch_via_sidebar(page, session_id):
    """Wissel zoals de gebruiker: klik op de instantie in de zijbalk."""
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=120000)
    page.evaluate("() => loadSessions()")
    item = _session_item(page, session_id)
    expect(item).to_be_visible(timeout=120000)
    item.locator(".session-badge").click()
    page.wait_for_function(
        "(sid) => state.activeSessionId === sid && !_isSwitchingSession",
        arg=session_id, timeout=300000)
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=300000)
    page.wait_for_function("() => !!state.results", timeout=300000)


def _open_planning(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=120000)
    page.evaluate("() => window.showTab('planning')")
    page.wait_for_selector("#planBody tr[data-material]", timeout=120000)


def _enable_edit_mode(page):
    if not page.evaluate("() => document.body.classList.contains('edit-mode')"):
        page.locator("#planning-tab .edit-mode-btn").click()
    expect(page.locator("body")).to_have_class(re.compile(r".*edit-mode.*"))


def _edit_a_demand_cell(page, new_value):
    """Zet de eerste bruikbare Line 01-cel op `new_value`.

    Geeft (materiaal, periode, oude waarde) terug zodat de test het VERSCHIL
    kan narekenen in plaats van alleen "er staat iets anders".
    """
    cells = page.locator(CELL)
    expect(cells.first).to_be_visible(timeout=120000)
    target = None
    original = None
    for index in range(min(cells.count(), 40)):
        candidate = cells.nth(index)
        raw = float(candidate.get_attribute("data-raw") or "0")
        if abs(raw - new_value) > 1.0:
            target, original = candidate, raw
            break
    assert target is not None, "geen bewerkbare vraagcel gevonden om te wijzigen"

    material = target.get_attribute("data-mat")
    period = target.get_attribute("data-period")
    target.click()
    expect(target).to_have_attribute("contenteditable", "true")
    target.fill(str(new_value))
    with page.expect_response(
        lambda response: "/api/update_volume" in response.url and response.ok,
        timeout=TIMEOUT * 1000,
    ):
        target.press("Enter")
    page.wait_for_load_state("networkidle")
    return material, period, original


def _save_scenario(page, name):
    """Scenario opslaan via de echte UI-functie (prompt afgevangen)."""
    with page.expect_response(
        lambda response: "/api/scenarios/save" in response.url and response.ok,
        timeout=TIMEOUT * 1000,
    ) as saved:
        page.evaluate(
            """(name) => {
                window.__alerts = [];
                window.alert = (msg) => window.__alerts.push(String(msg));
                window.prompt = () => name;
                return promptSaveScenario();
            }""",
            name,
        )
    body = saved.value.json()
    assert body.get("success"), body
    assert page.evaluate("() => window.__alerts") == []
    return body["scenario_id"]


def _load_scenario(page, scenario_id):
    """Scenario laden via de dropdown, inclusief de bevestigingsvraag."""
    with page.expect_response(
        lambda response: "/api/scenarios/load" in response.url,
        timeout=TIMEOUT * 1000,
    ) as loaded:
        page.evaluate(
            """async (scenarioId) => {
                window.__alerts = [];
                window.alert = (msg) => window.__alerts.push(String(msg));
                window.confirm = () => true;
                await refreshScenarioDrop();
                const drop = document.getElementById('scenarioDrop');
                if (!Array.from(drop.options).some(o => o.value === scenarioId)) {
                    // Verouderde dropdown (tweede tabblad): de optie bestaat
                    // nog wel in het scherm maar niet meer in de lijst.
                    const stale = document.createElement('option');
                    stale.value = scenarioId;
                    stale.textContent = 'verouderde optie';
                    drop.appendChild(stale);
                }
                drop.value = scenarioId;
                await loadScenarioFromDrop(drop);
            }""",
            scenario_id,
        )
    page.wait_for_load_state("networkidle")
    return loaded.value


def _compare_scenarios(page, id_a, id_b):
    """Vergelijk twee scenario's via de Compare-modal; geef het antwoord terug."""
    with page.expect_response(
        lambda response: "/api/scenarios/compare" in response.url and response.ok,
        timeout=TIMEOUT * 1000,
    ) as compared:
        page.evaluate(
            """async ([idA, idB]) => {
                window.__alerts = [];
                window.alert = (msg) => window.__alerts.push(String(msg));
                await openCompareModal();
                document.getElementById('cmpSelA').value = idA;
                document.getElementById('cmpSelB').value = idB;
                await runCompare();
            }""",
            [id_a, id_b],
        )
    expect(page.locator("#compareModal")).to_be_visible()
    return compared.value.json()


# --------------------------------------------------------------------------
# 1. Hernoemen
# --------------------------------------------------------------------------

def test_01_sessie_hernoemen_werkt_en_blijft_na_herladen(app_page, ctx):
    """De naam is het enige waaraan de consultant zijn varianten herkent.

    Hernoemen loopt via `_commitRename` -> /api/sessions/rename ->
    `save_sessions_to_disk`. Blijft de naam alleen in het geheugen of alleen in
    de DOM staan, dan heet na F5 of na een herstart alles weer gelijk en kiest
    de gebruiker de verkeerde instantie om mee te rekenen.
    """
    page = app_page
    server = page.server
    session_a = _sessions(server)["active_session_id"]
    ctx["session_a"] = session_a

    name_edit = page.locator(f'.session-name-edit[data-session-id="{session_a}"]')
    expect(name_edit).to_be_visible(timeout=120000)
    old_name = name_edit.inner_text().strip()
    assert old_name and old_name != NAME_A

    with page.expect_response(
        lambda response: "/api/sessions/rename" in response.url and response.ok,
        timeout=120000,
    ) as renamed:
        name_edit.click()
        name_edit.press("Control+A")
        name_edit.fill(NAME_A)
        name_edit.press("Enter")
    assert renamed.value.json().get("success")

    expect(page.locator(f'.session-name-edit[data-session-id="{session_a}"]')
           ).to_have_text(NAME_A, timeout=120000)

    # Herladen: de naam komt van de server, niet uit de DOM van zonet.
    page.reload(wait_until="networkidle")
    expect(page.locator(f'.session-name-edit[data-session-id="{session_a}"]')
           ).to_have_text(NAME_A, timeout=120000)

    assert _session_entry(server, session_a)["custom_name"] == NAME_A
    # En op SCHIJF, want dat is wat een herstart terugleest.
    store = json.loads((server["app_data_dir"] / "sessions_store.json")
                       .read_text(encoding="utf-8"))
    assert store["sessions"][session_a]["custom_name"] == NAME_A, (
        "de nieuwe naam staat niet in sessions_store.json")
    assert page.js_errors == []


# --------------------------------------------------------------------------
# 2. Dupliceren
# --------------------------------------------------------------------------

def test_02_opslaan_als_instantie_maakt_een_warme_kopie_met_dezelfde_cijfers(app_page, ctx):
    """"Opslaan als instantie" moet een KOPIE geven, geen bijna-kopie.

    Het duplicaat wordt koud aangemaakt en op de achtergrond opnieuw
    doorgerekend (upload -> berekenen -> edits terugspelen). Ontbreekt daarbij
    een veld uit `_get_session_config_overrides`, dan wordt de kopie wel warm
    maar rekent hij stil met andere aannames. Daarom vergelijken we hier elke
    cel van Line 03 met de bron in plaats van alleen te kijken of hij bestaat.
    """
    page = app_page
    server = page.server
    source = _results(server)
    ctx["base_rows_01"] = _rows(source, DEMAND)
    ctx["base_rows_03"] = _rows(source, TOTAL_DEMAND)
    ctx["base_total_01"] = _total(source, DEMAND)
    assert ctx["base_total_01"] > 0, "de bronsessie rekent 0 vraag; test is zinloos"

    _open_planning(page)
    with page.expect_response(
        lambda response: "/api/sessions/snapshot" in response.url and response.ok,
        timeout=TIMEOUT * 1000,
    ) as snapshot:
        page.locator('button[onclick="openSaveInstanceModal()"]').click()
        expect(page.locator("#saveInstanceName")).to_be_visible()
        page.locator("#saveInstanceName").fill(NAME_B)
        page.locator("#saveInstanceModal button", has_text="Opslaan").click()
    payload = snapshot.value.json()
    assert payload.get("success"), payload
    session_b = payload["session"]["id"]
    ctx["session_b"] = session_b
    assert session_b != ctx["session_a"]

    # Wachten tot de kopie warm is — precies waar de gebruiker op het
    # spinnertje wacht.
    assert _wait_until_warm(server, session_b) == "ready", _session_entry(server, session_b)
    entry = _session_entry(server, session_b)
    assert entry["custom_name"] == NAME_B

    page.evaluate("() => loadSessions()")
    badge = _session_item(page, session_b).locator(".session-badge")
    expect(badge).to_have_text("Ready", timeout=120000)

    # De bron blijft ondertussen ongewijzigd actief.
    assert _sessions(server)["active_session_id"] == ctx["session_a"]

    _switch_via_sidebar(page, session_b)
    copy_results = _results(server)
    assert _differing_cells(ctx["base_rows_03"],
                            _rows(copy_results, TOTAL_DEMAND)) == [], (
        "de kopie rekent andere totale vraag dan zijn bron")
    assert _differing_cells(ctx["base_rows_01"],
                            _rows(copy_results, DEMAND)) == []
    assert page.js_errors == []


# --------------------------------------------------------------------------
# 3. Wisselen
# --------------------------------------------------------------------------

def test_03_wisselen_tussen_instanties_toont_andere_cijfers(app_page, ctx):
    """Twee instanties, twee verschillende cijferbeelden.

    Klassieke faalmodus uit docs/ontwikkelhandleiding.md ("Switching instances shows wrong
    values"): de wissel gebeurt wel, maar tabel en API blijven de vorige
    instantie tonen. We bewerken daarom ALLEEN de kopie en controleren daarna
    dat de bron nog exact op zijn oude cijfers staat — in de API én in de cel
    die de gebruiker ziet.
    """
    page = app_page
    server = page.server
    assert _sessions(server)["active_session_id"] == ctx["session_b"]

    _open_planning(page)
    _enable_edit_mode(page)
    material, period, original = _edit_a_demand_cell(page, 999)
    ctx["edit_b"] = (material, period, original)
    assert abs(999 - original) > 1.0

    edited = _results(server)
    assert _value_of(edited, DEMAND, material, period) == pytest.approx(999, abs=0.01)
    # Precies één cel van de vraagvoorspelling veranderde mee.
    changed = _differing_cells(ctx["base_rows_01"], _rows(edited, DEMAND))
    assert len(changed) == 1, changed
    changed_material, changed_period, was, now = changed[0]
    assert (changed_material, changed_period) == (material, period)
    assert was == pytest.approx(original, abs=0.01)
    assert now == pytest.approx(999, abs=0.01)
    assert _total(edited, DEMAND) == pytest.approx(
        ctx["base_total_01"] + (999 - original), abs=0.5)
    assert float(page.locator(
        f'{CELL}[data-mat="{material}"][data-period="{period}"]'
    ).first.get_attribute("data-raw")) == pytest.approx(999, abs=0.01)

    _switch_via_sidebar(page, ctx["session_a"])
    back = _results(server)
    assert _differing_cells(ctx["base_rows_01"], _rows(back, DEMAND)) == [], (
        "de bron toont de bewerking van de kopie — sessies lekken in elkaar")
    assert _total(back, DEMAND) == pytest.approx(ctx["base_total_01"], rel=1e-9)
    assert _total(back, DEMAND) != pytest.approx(_total(edited, DEMAND), abs=0.5)

    _open_planning(page)
    shown = float(page.locator(
        f'{CELL}[data-mat="{material}"][data-period="{period}"]'
    ).first.get_attribute("data-raw"))
    assert shown == pytest.approx(original, abs=0.01), (
        "de planningstabel toont na de wissel nog de waarde van de andere instantie")
    assert page.js_errors == []


# --------------------------------------------------------------------------
# 4. Scenario opslaan en laden
# --------------------------------------------------------------------------

def test_04_scenario_opslaan_en_laden_herstelt_de_cijfers_exact(app_page, ctx):
    """Een scenario is een terugkeerpunt; "bijna terug" is waardeloos.

    Laden vervangt `engine.results` door de momentopname en leidt de
    override-stores opnieuw af. Blijft daar één bewerking hangen, dan wijkt het
    herstelde beeld af van het opgeslagen beeld zonder dat iemand het ziet.
    Daarom vergelijken we hier ELKE cel van Line 01 en Line 03.
    """
    page = app_page
    server = page.server
    assert _sessions(server)["active_session_id"] == ctx["session_a"]

    before = _results(server)
    rows_01 = _rows(before, DEMAND)
    rows_03 = _rows(before, TOTAL_DEMAND)
    ctx["sc_basis"] = _save_scenario(page, "Basis A")

    _open_planning(page)
    _enable_edit_mode(page)
    material, period, original = _edit_a_demand_cell(page, 4321)
    ctx["edit_a"] = (material, period, original)
    edited = _results(server)
    assert _value_of(edited, DEMAND, material, period) == pytest.approx(4321, abs=0.01)
    assert _differing_cells(rows_01, _rows(edited, DEMAND)) != []
    ctx["sc_edit"] = _save_scenario(page, "A met 4321")

    _load_scenario(page, ctx["sc_basis"])
    restored = _results(server)
    assert _differing_cells(rows_01, _rows(restored, DEMAND), tol=1e-6) == [], (
        "de vraagvoorspelling kwam niet exact terug uit het scenario")
    assert _differing_cells(rows_03, _rows(restored, TOTAL_DEMAND), tol=1e-6) == [], (
        "de totale vraag kwam niet exact terug uit het scenario")
    assert _value_of(restored, DEMAND, material, period) == pytest.approx(
        original, rel=1e-9)
    assert page.evaluate("() => window.__alerts") == []
    assert page.js_errors == []


# --------------------------------------------------------------------------
# 5. Scenario laden ruimt de bewerkingen erna op
# --------------------------------------------------------------------------

def test_05_scenario_laden_wist_de_bewerkingen_van_daarna(app_page, ctx):
    """Laden moet ook de BEWERKINGSSTAAT terugzetten, niet alleen de cijfers.

    `pending_edits` is wat na een herstart wordt teruggespeeld. Blijft een
    bewerking van na het scenario daarin staan, dan klopt het scherm vandaag
    maar rekent dezelfde instantie morgen anders. De teller in de balk is het
    enige dat de gebruiker daarvan ziet, dus die controleren we samen met het
    getal in de API.
    """
    page = app_page
    server = page.server
    assert _sessions(server)["active_session_id"] == ctx["session_a"]

    _open_planning(page)
    _enable_edit_mode(page)
    material, period, original = _edit_a_demand_cell(page, 777)
    expect(page.locator("#editSummaryBar")).to_be_visible(timeout=60000)
    expect(page.locator("#editSummaryCount")).to_contain_text("1")
    assert _value_of(_results(server), DEMAND, material, period) == pytest.approx(
        777, abs=0.01)

    _load_scenario(page, ctx["sc_basis"])

    expect(page.locator("#editSummaryBar")).not_to_be_visible(timeout=120000)
    assert page.evaluate("() => Object.keys(state.cellEdits || {}).length") == 0
    after = _results(server)
    assert _value_of(after, DEMAND, material, period) == pytest.approx(
        original, rel=1e-9), "de bewerking van na het scenario staat er nog"
    assert _differing_cells(ctx["base_rows_01"], _rows(after, DEMAND), tol=1e-6) == []
    assert page.js_errors == []


# --------------------------------------------------------------------------
# 6. Twee scenario's vergelijken
# --------------------------------------------------------------------------

def test_06_twee_scenarios_vergelijken_toont_het_verschil_op_de_cel(app_page, ctx):
    """De vergelijking is het rapport waarop een beslissing wordt genomen.

    Hij moet niet "er is iets anders" zeggen maar exact hoeveel: het verschil
    op de bewerkte cel hoort de bewerking zelf te zijn (oud - 4321). Een
    verschil dat op de verkeerde regel landt (rijkoppeling op materiaal +
    aux) is precies de fout die je in een tabel met duizenden regels niet ziet.
    """
    page = app_page
    material, period, original = ctx["edit_a"]

    body = _compare_scenarios(page, ctx["sc_basis"], ctx["sc_edit"])
    summary = body["summary"]
    assert summary["scenario_a_name"] == "Basis A"
    assert summary["scenario_b_name"] == "A met 4321"
    assert summary["changed_rows"] > 0

    demand_rows = [row for row in body["rows"]
                   if row["line_type"] == DEMAND
                   and str(row["material_number"]) == str(material)]
    assert len(demand_rows) == 1, demand_rows
    row = demand_rows[0]
    assert row["diff"][period] == pytest.approx(original - 4321, abs=0.01)
    assert row["values_a"][period] == pytest.approx(original, abs=0.01)
    assert row["values_b"][period] == pytest.approx(4321, abs=0.01)
    # Alleen die ene periode van die regel verschilt.
    assert [p for p, v in row["diff"].items() if abs(v) > 0.01] == [period]

    # En de gebruiker ziet het ook echt in de modal.
    expect(page.locator("#cmpSummary")).to_contain_text(str(summary["changed_rows"]))
    expect(page.locator("#cmpTableWrap")).to_contain_text(str(material))
    page.evaluate("() => document.getElementById('compareModal').remove()")
    assert page.js_errors == []


def test_07_twee_identieke_scenarios_tonen_geen_verschillen(app_page, ctx):
    """Tegenproef bij de vorige test: geen ruis.

    Twee scenario's uit dezelfde toestand moeten 0 gewijzigde regels geven.
    Zonder deze test zou een vergelijking die alles als "gewijzigd" markeert
    (afrondingsruis, verschoven rijkoppeling) er nog steeds overtuigend
    uitzien.
    """
    page = app_page
    server = page.server
    assert _sessions(server)["active_session_id"] == ctx["session_a"]

    twin_one = _save_scenario(page, "Tweeling 1")
    twin_two = _save_scenario(page, "Tweeling 2")
    assert twin_one != twin_two

    body = _compare_scenarios(page, twin_one, twin_two)
    assert body["summary"]["changed_rows"] == 0, body["rows"][:3]
    assert body["rows"] == []
    assert all(abs(v) <= 0.01
               for v in body["summary"]["total_demand_diff"].values())
    expect(page.locator("#cmpTableWrap")).to_contain_text("No differences found")
    page.evaluate("() => document.getElementById('compareModal').remove()")
    assert page.js_errors == []


# --------------------------------------------------------------------------
# 8 en 9. Scenario's horen bij één instantie
# --------------------------------------------------------------------------

def test_08_scenario_van_een_andere_instantie_wordt_geweigerd(app_page, ctx):
    """Een scenario draagt de cijfers van ZIJN instantie.

    Laden in een andere instantie zou de resultaten van instantie B in
    instantie A schuiven — dezelfde materialen, andere cijfers, geen melding.
    Dit gebeurt echt: twee tabbladen open, in het ene gewisseld, in het andere
    nog de oude dropdown. Dat bootsen we na door de verouderde optie in de
    dropdown te zetten en hem te laden.
    """
    page = app_page
    server = page.server

    # Scenario opslaan IN instantie B ...
    _switch_via_sidebar(page, ctx["session_b"])
    scenario_b = _save_scenario(page, "Scenario van B")
    ctx["sc_van_b"] = scenario_b

    # ... en het daarna in instantie A proberen te laden.
    _switch_via_sidebar(page, ctx["session_a"])
    before = _rows(_results(server), DEMAND)

    response = _load_scenario(page, scenario_b)
    assert response.status == 403, response.status
    assert "different session" in response.json().get("error", "")
    alerts = page.evaluate("() => window.__alerts")
    assert any("Load failed" in alert for alert in alerts), alerts

    after = _rows(_results(server), DEMAND)
    assert _differing_cells(before, after, tol=1e-6) == [], (
        "een geweigerd scenario heeft de planning toch aangeraakt")

    # Ook verwijderen en vergelijken over de instantiegrens wordt geweigerd.
    delete = requests.delete(
        f'{server["base_url"]}/api/scenarios/{scenario_b}', timeout=TIMEOUT)
    assert delete.status_code == 403, delete.text
    compare = requests.post(
        server["base_url"] + "/api/scenarios/compare",
        json={"scenario_a_id": ctx["sc_basis"], "scenario_b_id": scenario_b},
        timeout=TIMEOUT)
    assert compare.status_code == 403, compare.text
    assert page.js_errors == []


def test_09_de_scenariolijst_toont_alleen_de_eigen_instantie(app_page, ctx):
    """De dropdown mag scenario's van een andere instantie niet aanbieden.

    De weigering uit de vorige test is het vangnet; dit is de voordeur. Lekt
    de lijst, dan kiest de gebruiker een scenario dat hij niet kan laden — of
    erger, hij denkt dat de varianten van zijn collega bij deze instantie
    horen.
    """
    page = app_page
    server = page.server
    assert _sessions(server)["active_session_id"] == ctx["session_a"]

    def _drop_ids():
        return page.evaluate(
            """async () => {
                await refreshScenarioDrop();
                return Array.from(document.querySelectorAll('#scenarioDrop option'))
                    .map(o => o.value).filter(Boolean);
            }""")

    ids_a = _drop_ids()
    api_ids_a = [sc["id"] for sc in _get(server, "/api/scenarios")["scenarios"]]
    assert set(ids_a) == set(api_ids_a)
    assert ctx["sc_basis"] in ids_a and ctx["sc_edit"] in ids_a
    assert ctx["sc_van_b"] not in ids_a, "scenario van instantie B lekt in de lijst van A"

    _switch_via_sidebar(page, ctx["session_b"])
    ids_b = _drop_ids()
    api_ids_b = [sc["id"] for sc in _get(server, "/api/scenarios")["scenarios"]]
    assert set(ids_b) == set(api_ids_b)
    assert ids_b == [ctx["sc_van_b"]], ids_b
    assert not set(ids_a) & set(ids_b)
    assert page.js_errors == []
