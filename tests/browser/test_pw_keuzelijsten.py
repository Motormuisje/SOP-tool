"""Keuzelijsten op sleutel- en code-invoer (klantvraag 2026-08-06).

"Bij dingen zoals product toevoegen is er teveel risico op een verkeerde naam
of sleutel intypen; zorg dat je kan selecteren van een lijst als je een deel
van de naam of machine invult."

Het antwoord: elke vrije sleutel-invoer kreeg een keuzelijst die uit de
masterdata zelf put — de sleutelkiezer verving de kale prompt() van
"+ rij toevoegen", paarsleutels (MACHINE|MATERIAAL) zijn twee velden met elk
hun eigen lijst, en de wizard, de csv-cellen en het configformulier
suggereren op een deel van naam óf code. Deze tests pinnen dat vast: zoeken
op naamfragment levert de code, een onbekende code wordt geweigerd, en vrije
ID-velden (nieuwe combinatie) blijven vrij.
"""

import pytest
import requests
from playwright.sync_api import expect

from tests.browser.test_pw_masterdata import _ensure_store, _open_config


def _prepare(page, golden_fixture_path):
    page.reload(wait_until="networkidle")
    _open_config(page)
    _ensure_store(page.server["base_url"], golden_fixture_path)
    page.evaluate(
        """() => {
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


def _open_dataset(page, dataset):
    page.evaluate("(ds) => openMasterDatasetModal(ds)", dataset)
    page.wait_for_function(
        "() => document.querySelectorAll('#masterDatasetBody tr').length > 0",
        timeout=30000)


def _machine_and_material(base_url):
    machines = requests.get(base_url + "/api/master_data/machines", timeout=60).json()["value"]
    materials = requests.get(base_url + "/api/master_data/materials", timeout=60).json()["value"]
    named = next(m for m in materials if len(str(m.get("name") or "")) >= 6)
    return str(machines[0]["machine_code"]), named


def test_sleutelkiezer_vervangt_prompt_en_zoekt_op_deel_van_code(browser_page, golden_fixture_path):
    """"+ rij toevoegen" opent een kiezer met keuzelijst in plaats van een
    prompt; een deel van de code typen toont de lijst met code én naam, en
    kiezen zet de exacte code in het veld."""
    page = browser_page
    _prepare(page, golden_fixture_path)
    _open_dataset(page, "staffing_norms")

    page.click('button[onclick="addMasterDatasetRow()"]')
    expect(page.locator("#masterKeyModal")).to_be_visible()

    veld = page.locator('#masterKeyFields input[data-key-part="0"]')
    veld.fill("ZZ_")
    expect(page.locator("#suggestDropdown")).to_be_visible(timeout=10000)
    eerste = page.evaluate(
        """() => {
            const el = document.querySelector('#suggestDropdown [data-suggest-index="0"]');
            return el ? el.textContent.trim() : null;
        }""")
    assert eerste and "ZZ_" in eerste

    page.locator('#suggestDropdown [data-suggest-index="0"]').click()
    gekozen = veld.input_value()
    assert gekozen.startswith("ZZ_") and " " not in gekozen, gekozen
    # Kiezen moet ook VOELEN als kiezen: de lijst sluit (de focus-handler
    # heropende hem eerst meteen) en het veld draagt de gekozen-status.
    expect(page.locator("#suggestDropdown")).to_be_hidden()
    assert veld.get_attribute("data-suggest-state") == "known"

    page.click('button[onclick="confirmMasterKeyPicker()"]')
    expect(page.locator("#masterKeyModal")).to_be_hidden()
    expect(page.locator(f'#masterDatasetBody tr[data-master-key="{gekozen}"]')).to_be_attached()
    # Niet opgeslagen: de rij bestaat alleen in het grid, de store is schoon.
    assert page.js_errors == []


def test_paarsleutel_machine_en_materiaal_worden_gekozen(browser_page, golden_fixture_path):
    """MACHINE|MATERIAAL wordt nooit meer met de hand geplakt: twee velden,
    elk met een lijst — en het materiaal is vindbaar op een deel van de NAAM,
    niet alleen het nummer."""
    page = browser_page
    _prepare(page, golden_fixture_path)
    machine, materiaal = _machine_and_material(page.server["base_url"])
    _open_dataset(page, "throughput_overrides")

    page.click('button[onclick="addMasterDatasetRow()"]')
    expect(page.locator("#masterKeyModal")).to_be_visible()

    page.locator('#masterKeyFields input[data-key-part="0"]').fill(machine[:3])
    expect(page.locator("#suggestDropdown")).to_be_visible(timeout=10000)
    page.evaluate(
        """(code) => {
            const i = _suggestActive.items.findIndex(o => o.code === code);
            _pickSuggest(i === -1 ? 0 : i);
        }""", machine)
    assert page.locator('#masterKeyFields input[data-key-part="0"]').input_value() == machine

    naamdeel = str(materiaal["name"])[:5]
    veld2 = page.locator('#masterKeyFields input[data-key-part="1"]')
    veld2.click()
    veld2.fill(naamdeel)
    expect(page.locator("#suggestDropdown")).to_be_visible(timeout=10000)
    treffer = page.evaluate(
        "(nr) => _suggestActive.items.some(o => o.code === nr)", str(materiaal["material_number"]))
    assert treffer, f"materiaal is niet vindbaar op naamdeel {naamdeel!r}"
    page.evaluate(
        """(nr) => _pickSuggest(_suggestActive.items.findIndex(o => o.code === nr))""",
        str(materiaal["material_number"]))

    page.click('button[onclick="confirmMasterKeyPicker()"]')
    sleutel = f'{machine}|{materiaal["material_number"]}'
    expect(page.locator(f'#masterDatasetBody tr[data-master-key="{sleutel}"]')).to_be_attached()
    assert page.js_errors == []


def test_onbekende_code_geweigerd_maar_vrije_id_toegestaan(browser_page, golden_fixture_path):
    """Twee kanten van dezelfde regel: een suggestieveld accepteert geen code
    die niet in de lijst staat (anders is de kiezer een omweg naar dezelfde
    typfout), maar een bewust vrij veld — een nieuwe combinatie-ID — blijft
    vrij."""
    page = browser_page
    _prepare(page, golden_fixture_path)
    _open_dataset(page, "staffing_norms")

    page.click('button[onclick="addMasterDatasetRow()"]')
    page.locator('#masterKeyFields input[data-key-part="0"]').fill("BESTAATNIET_99")
    # Het veld waarschuwt al vóór de knop: onbekende code = amber status.
    page.wait_for_function(
        """() => document.querySelector('#masterKeyFields input[data-key-part="0"]')
                     ?.dataset.suggestState === 'unknown'""", timeout=10000)
    page.click('button[onclick="confirmMasterKeyPicker()"]')
    page.wait_for_function(
        "() => (window.__notes || []).some(n => n.includes('staat niet in de lijst'))",
        timeout=10000)
    expect(page.locator("#masterKeyModal")).to_be_visible()  # blijft open voor herstel
    assert page.locator('#masterDatasetBody tr[data-master-key="BESTAATNIET_99"]').count() == 0
    page.evaluate("() => closeMasterKeyPicker()")

    _open_dataset(page, "machine_combinations")
    page.click('button[onclick="addMasterDatasetRow()"]')
    page.locator('#masterKeyFields input[data-key-part="0"]').fill("KEUZETEST_COMBI")
    page.click('button[onclick="confirmMasterKeyPicker()"]')
    expect(page.locator('#masterDatasetBody tr[data-master-key="KEUZETEST_COMBI"]')).to_be_attached()
    assert page.js_errors == []


def test_wizard_vindt_bestaand_product_op_naamdeel(browser_page, golden_fixture_path):
    """De productwizard: een deel van de NAAM typen toont de lijst; kiezen
    zet het nummer in het veld en de bestaat-al-hint verschijnt — precies het
    scenario waarin een handgetypt nummer een spookproduct zou maken."""
    page = browser_page
    _prepare(page, golden_fixture_path)
    _, materiaal = _machine_and_material(page.server["base_url"])

    page.evaluate("() => openMasterProductWizard()")
    expect(page.locator("#masterProductModal")).to_be_visible()
    try:
        veld = page.locator("#mwNumber")
        veld.fill(str(materiaal["name"])[:5])
        expect(page.locator("#suggestDropdown")).to_be_visible(timeout=10000)
        page.evaluate(
            """(nr) => _pickSuggest(_suggestActive.items.findIndex(o => o.code === nr))""",
            str(materiaal["material_number"]))
        assert veld.input_value() == str(materiaal["material_number"])
        expect(page.locator("#mwNumberHint")).to_contain_text("Bestaat al", timeout=5000)
    finally:
        page.evaluate(
            "() => { document.getElementById('masterProductModal').style.display = 'none'; }")
    assert page.js_errors == []


def test_csv_cel_suggereert_ook_na_een_komma(browser_page, golden_fixture_path):
    """De machinelijst van een combinatie is komma-gescheiden invoer; de
    keuzelijst moet per token werken zodat óók de tweede machine gekozen
    wordt in plaats van getypt."""
    page = browser_page
    _prepare(page, golden_fixture_path)
    base_url = page.server["base_url"]
    machines = requests.get(base_url + "/api/master_data/machines", timeout=60).json()["value"]
    eerste, tweede = str(machines[0]["machine_code"]), str(machines[1]["machine_code"])
    _open_dataset(page, "machine_combinations")

    page.evaluate("() => _insertMasterRow('machine_combinations', 'KEUZETEST_CSV')")
    cel = page.locator('#masterDatasetBody tr[data-master-key="KEUZETEST_CSV"] '
                       '[data-master-col="machine_codes"] input')
    cel.click()
    cel.fill(eerste[:3])
    expect(page.locator("#suggestDropdown")).to_be_visible(timeout=10000)
    page.evaluate(
        "(c) => _pickSuggest(Math.max(0, _suggestActive.items.findIndex(o => o.code === c)))", eerste)
    assert cel.input_value() == eerste

    cel.fill(f"{eerste}, {tweede[:3]}")
    cel.dispatch_event("input")
    expect(page.locator("#suggestDropdown")).to_be_visible(timeout=10000)
    aangeboden = page.evaluate("() => _suggestActive.items.map(o => o.code)")
    assert eerste not in aangeboden, "de al gekozen machine wordt opnieuw aangeboden"
    page.evaluate(
        "(c) => _pickSuggest(Math.max(0, _suggestActive.items.findIndex(o => o.code === c)))", tweede)
    assert cel.input_value() == f"{eerste}, {tweede}"
    assert page.js_errors == []


def test_config_unlimited_machines_heeft_keuzelijst(browser_page, golden_fixture_path):
    """Ook het configformulier: unlimited-machines is komma-gescheiden
    machinecodes en kreeg dezelfde keuzelijst."""
    page = browser_page
    _prepare(page, golden_fixture_path)
    _open_dataset(page, "config")

    veld = page.locator('#masterDatasetBody tr[data-master-field="unlimited_capacity_machine"] input')
    assert veld.get_attribute("data-suggest-wired") == "1"
    waarde = veld.input_value()
    veld.click()
    veld.fill((waarde + ", P") if waarde else "P")
    veld.dispatch_event("input")
    expect(page.locator("#suggestDropdown")).to_be_visible(timeout=10000)
    codes = page.evaluate("() => _suggestActive.items.map(o => o.code)")
    assert codes and all(c.startswith("P") for c in codes)
    page.keyboard.press("Escape")
    # Terugzetten zonder op te slaan: het grid is nooit gePATCHt.
    veld.fill(waarde)
    assert page.js_errors == []
