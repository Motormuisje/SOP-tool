"""Machine-inzet fase 1 (klantvraag 2026-08-09): omstellingen & combinaties.

De planning is de bron: het tabblad leest Line 07 en schat omstellingen als
producten − 1 (eerlijk gelabeld — de volgorde is onbekend tot fase 3). De
omsteltijd is masterdata met write-through; het aantal is sessie-wat-als.
"""

import pytest
import requests
from playwright.sync_api import expect

from tests.browser.test_pw_masterdata import _ensure_store


def _open_inzet(page):
    page.reload(wait_until="networkidle")
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    with page.expect_response(lambda r: "/api/machine_inzet" in r.url and r.ok):
        page.evaluate("() => showTab('inzet')")
    page.wait_for_function(
        "() => document.querySelectorAll('#inzetTableBody tr').length > 0", timeout=30000)


def _api(base_url):
    return requests.get(base_url + "/api/machine_inzet", timeout=120).json()


def test_tabel_spiegelt_de_planning(browser_page):
    """Rijen en celwaarden komen exact uit /api/machine_inzet, en de
    schatting is producten − 1 met ondergrens 0 — geen fantoomomstelling op
    een machine met één product."""
    page = browser_page
    _open_inzet(page)
    api = _api(page.server["base_url"])

    report = page.evaluate(
        """() => {
            const rows = [...document.querySelectorAll('#inzetTableBody tr[data-inzet-row]')];
            return { rows: rows.length, eerste: rows[0]?.dataset.inzetRow || null };
        }""")
    draaiend = [c for c, m in api["machines"].items()
                if any(cel["hours"] > 0 for cel in m["per_period"].values())]
    assert report["rows"] == len(draaiend), (report, len(draaiend))

    # De schattingsformule, gepind tegen de API voor elke machine × periode.
    formule = page.evaluate(
        """() => {
            const uit = [];
            for (const code of Object.keys(_inzetState.data.machines)) {
                for (const p of _inzetState.data.periods) {
                    const { est, info } = _inzetCount(code, p);
                    uit.push([code, p, est, (info.products || []).length]);
                }
            }
            return uit;
        }""")
    for code, periode, est, n_producten in formule:
        assert est == max(0, n_producten - 1), (code, periode, est, n_producten)
    assert page.js_errors == []


def test_omsteltijd_is_masterdata_met_versiebump(browser_page, golden_fixture_path):
    """De omsteltijdkolom schrijft door naar de masterdata (CAS): de versie
    bumpt, de cellen tonen count × tijd = uren, en leegmaken verwijdert de
    regel weer."""
    page = browser_page
    _ensure_store(page.server["base_url"], golden_fixture_path)
    _open_inzet(page)
    base_url = page.server["base_url"]

    machine = page.evaluate(
        "() => document.querySelector('#inzetTableBody tr[data-inzet-row]').dataset.inzetRow")
    version_before = requests.get(base_url + "/api/master_data/changeover_times",
                                  timeout=60).json()["version"]

    veld = page.locator(f'input[data-inzet-machine="{machine}"]')
    veld.fill("1,5")
    with page.expect_response(lambda r: "/api/master_data/changeover_times" in r.url
                              and r.request.method == "PATCH" and r.ok):
        veld.dispatch_event("change")
    # Wachten tot de re-render de OPGESLAGEN staat toont (niet op een knop
    # die er altijd is): daarna is het veld vers en de handler-race voorbij.
    page.wait_for_function(
        """(m) => (_inzetState.data.changeover_times[m] || {}).hours_per_changeover === 1.5""",
        arg=machine, timeout=30000)

    store = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
    assert store["version"] == version_before + 1
    assert store["value"][machine]["hours_per_changeover"] == pytest.approx(1.5)
    # De cellen van die machine tonen nu uren (count × 1,5).
    cel = page.locator(f'#inzetTableBody tr[data-inzet-row="{machine}"] td button').first
    assert "u" in cel.inner_text()

    # Opruimen: leegmaken verwijdert de masterdata-regel weer.
    veld2 = page.locator(f'input[data-inzet-machine="{machine}"]')
    veld2.fill("")
    with page.expect_response(lambda r: "/api/master_data/changeover_times" in r.url
                              and r.request.method == "PATCH" and r.ok):
        veld2.dispatch_event("change")
    page.wait_for_function(
        "(m) => _inzetState.data.changeover_times[m] === undefined",
        arg=machine, timeout=30000)
    eind = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
    assert machine not in (eind["value"] or {})
    assert page.js_errors == []


def test_aantal_is_sessie_wat_als_en_overleeft_herlaad(browser_page):
    """Celklik → invoer → Enter zet een wat-als op het aantal omstellingen:
    amber, persistent over een paginaherlaad (sessiestate), en de schatting
    terugtypen ruimt hem op."""
    page = browser_page
    _open_inzet(page)

    doel = page.evaluate(
        """() => {
            for (const code of Object.keys(_inzetState.data.machines)) {
                for (const p of _inzetState.data.periods) {
                    const { est, isOverride, info } = _inzetCount(code, p);
                    if (!isOverride && info.hours > 0) return { code, p, est };
                }
            }
            return null;
        }""")
    assert doel, "geen cel zonder override gevonden"

    with page.expect_response(lambda r: "/api/machine_inzet/overrides" in r.url and r.ok):
        page.evaluate(
            """(d) => {
                const rij = document.querySelector(`#inzetTableBody tr[data-inzet-row="${d.code}"]`);
                const knop = [...rij.querySelectorAll('td button')]
                    .find(b => b.getAttribute('onclick').includes(`'${d.p}'`));
                knop.click();
                const invoer = rij.querySelector('td input:not([data-inzet-machine])');
                invoer.value = String(d.est + 3);
                invoer.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            }""", doel)
    # De JS-continuatie (json → state → render) loopt ná de response: wachten
    # op de toestand, niet op het netwerk.
    page.wait_for_function(
        "(d) => _inzetState.overrides[`${d.code}|${d.p}`] === d.est + 3",
        arg=doel, timeout=15000)

    # Herlaad: de wat-als komt uit de sessie terug (server draagt hem).
    _open_inzet(page)
    assert page.evaluate(
        "(d) => _inzetState.overrides[`${d.code}|${d.p}`]", doel) == doel["est"] + 3
    kleur = page.evaluate(
        """(d) => {
            const rij = document.querySelector(`#inzetTableBody tr[data-inzet-row="${d.code}"]`);
            const knop = [...rij.querySelectorAll('td button')]
                .find(b => b.getAttribute('onclick').includes(`'${d.p}'`));
            return knop.className;
        }""", doel)
    assert "text-amber-300" in kleur, "wat-als-cel is niet amber gemarkeerd"

    # De schatting terugtypen = override weg.
    with page.expect_response(lambda r: "/api/machine_inzet/overrides" in r.url and r.ok):
        page.evaluate(
            """(d) => {
                const rij = document.querySelector(`#inzetTableBody tr[data-inzet-row="${d.code}"]`);
                const knop = [...rij.querySelectorAll('td button')]
                    .find(b => b.getAttribute('onclick').includes(`'${d.p}'`));
                knop.click();
                const invoer = rij.querySelector('td input:not([data-inzet-machine])');
                invoer.value = String(d.est);
                invoer.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            }""", doel)
    page.wait_for_function(
        "() => Object.keys(_inzetState.overrides).length === 0", timeout=15000)
    assert page.js_errors == []


def test_combinaties_wonen_nu_hier_en_werkbank_toont_de_stand(browser_page):
    """De combinatiekaart is verhuisd: hij staat op Machine-inzet, en de
    werkbank toont alleen nog de stand met een sprong hierheen."""
    page = browser_page
    _open_inzet(page)

    # De kaart staat in het inzet-tabblad.
    assert page.evaluate(
        "() => document.getElementById('fteCombinations').closest('.tab-content').id") == "inzet-tab"

    # De werkbank toont de samenvatting; de knop springt naar Machine-inzet.
    page.evaluate("() => showTab('fte')")
    expect(page.locator("#fteCombiSummary")).to_be_attached()
    page.wait_for_function(
        "() => document.getElementById('fteCombiSummary').textContent !== ''", timeout=15000)
    page.evaluate("() => showTab('inzet')")
    expect(page.locator("#inzet-tab")).to_be_visible()
    assert page.js_errors == []


def test_masterdata_grid_omsteltijden_bestaat_met_sleutelkiezer(browser_page, golden_fixture_path):
    """De dataset is ook via Config → Masterdata-tabellen bereikbaar, met de
    sleutelkiezer die machines suggereert — geen vrij getypte machinecode."""
    page = browser_page
    from tests.browser.test_pw_masterdata import _open_config
    page.reload(wait_until="networkidle")
    _open_config(page)
    _ensure_store(page.server["base_url"], golden_fixture_path)
    page.evaluate("() => loadMasterDataStatus()")
    page.wait_for_function(
        "() => document.querySelectorAll('#masterDatasetButtons button').length > 0",
        timeout=30000)

    page.evaluate("() => openMasterDatasetModal('changeover_times')")
    page.wait_for_selector("#masterDatasetBody table", timeout=30000)
    page.click('button[onclick="addMasterDatasetRow()"]')
    expect(page.locator("#masterKeyModal")).to_be_visible()
    veld = page.locator('#masterKeyFields input[data-key-part="0"]')
    veld.fill("PBA")
    expect(page.locator("#suggestDropdown")).to_be_visible(timeout=10000)
    codes = page.evaluate("() => _suggestActive.items.map(o => o.code)")
    assert codes and all(c.startswith("PBA") for c in codes)
    page.evaluate("() => closeMasterKeyPicker()")
    assert page.js_errors == []
