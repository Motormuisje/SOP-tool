"""Machine-inzet: planbord per machine (fase 1 + 1b, ontwerp C2 van 2026-08-26).

De planning is de bron: het tabblad leest Line 07 en schat omstellingen als
producten − 1 (eerlijk gelabeld — de volgorde is een sessie-wat-als, van→naar-
tijden zijn fase 3). Links de machinelijst (groepen, sortering, zoeken),
rechts één machine over alle maanden. Omsteltijd en tarief zijn masterdata
met write-through; aantal en volgorde zijn sessie-wat-als.
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
        "() => document.querySelectorAll('#inzetRailList [data-inzet-row]').length > 0", timeout=30000)


def _api(base_url):
    return requests.get(base_url + "/api/machine_inzet", timeout=120).json()


def _select(page, code):
    """Kies een machine in de lijst; het bord toont daarna haar invoervelden."""
    page.click(f'#inzetRailList [data-inzet-row="{code}"]')
    page.wait_for_function(
        "(c) => _inzetState.selected === c && !!document.querySelector(`input[data-inzet-machine=\"${c}\"]`)",
        arg=code, timeout=15000)


def _machine_met_minstens(api, n_producten):
    """Eerste machine (alfabetisch) die in de horizon ≥ n producten draait."""
    for code in sorted(api["machines"]):
        if len(api["machines"][code]["sequence"]) >= n_producten:
            return code
    return None


def test_lijst_en_bord_spiegelen_de_planning(browser_page):
    """De lijst toont precies de machines met draaiuren (of een omsteltijd),
    de KPI-strip het horizontotaal, en het bord van de gekozen machine één
    rij per periode met de schattingsformule van de API."""
    page = browser_page
    _open_inzet(page)
    api = _api(page.server["base_url"])

    rows = page.evaluate(
        "() => [...document.querySelectorAll('#inzetRailList [data-inzet-row]')].map(b => b.dataset.inzetRow)")
    verwacht = sorted(c for c, m in api["machines"].items()
                      if any(cel["hours"] > 0 for cel in m["per_period"].values())
                      or c in api["changeover_times"])
    assert sorted(rows) == verwacht, (rows, verwacht)
    assert page.evaluate("() => document.querySelectorAll('#inzetKpis .kpi-card').length") == 4
    assert str(api["totals"]["horizon"]["changeovers"]) in page.evaluate(
        "() => document.getElementById('inzetKpis').textContent")

    # Standaardsortering: kosten aflopend, daarna code.
    def kosten(c): return api["machines"][c]["total"]["cost"]
    assert rows == sorted(rows, key=lambda c: (-kosten(c), c)) or True  # groepen kunnen de volgorde breken
    # Binnen een groep is de volgorde wel kosten-aflopend.
    groepen = page.evaluate(
        """() => {
            const uit = {};
            let g = null;
            for (const el of document.querySelectorAll('#inzetRailList [data-inzet-group], #inzetRailList [data-inzet-row]')) {
                if (el.dataset.inzetGroup !== undefined) { g = el.dataset.inzetGroup; uit[g] = []; }
                else uit[g].push(el.dataset.inzetRow);
            }
            return uit;
        }""")
    for g, codes in groepen.items():
        assert codes == sorted(codes, key=lambda c: (-kosten(c), c)), (g, codes)

    sel = page.evaluate("() => _inzetState.selected")
    assert sel in rows
    maanden = page.evaluate("() => [...document.querySelectorAll('#inzetBoard [data-inzet-month]')].map(r => r.dataset.inzetMonth)")
    assert maanden == api["periods"]
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


def test_zoeken_sorteren_en_kiezen(browser_page):
    """Zoeken filtert op machine én product, 'zonder tijd eerst' zet de
    invullijst bovenaan, en een klik in de lijst wisselt het bord."""
    page = browser_page
    _open_inzet(page)
    api = _api(page.server["base_url"])
    alle = page.evaluate("() => [...document.querySelectorAll('#inzetRailList [data-inzet-row]')].map(b => b.dataset.inzetRow)")
    assert len(alle) >= 2, "te weinig machines om te wisselen"

    # Kiezen: het bord volgt de selectie.
    doel = [c for c in alle if c != page.evaluate("() => _inzetState.selected")][0]
    _select(page, doel)
    assert page.evaluate("() => document.querySelector('#inzetBoard .font-mono.font-semibold').textContent") == doel

    # Zoeken op een productnaam van die machine vindt haar terug.
    mat = api["machines"][doel]["sequence"][0]
    page.fill("#inzetSearch", mat[-4:])
    page.wait_for_function(
        "(c) => [...document.querySelectorAll('#inzetRailList [data-inzet-row]')].some(b => b.dataset.inzetRow === c)",
        arg=doel, timeout=10000)
    page.fill("#inzetSearch", "ZZ-BESTAAT-NIET")
    page.wait_for_function(
        "() => document.querySelectorAll('#inzetRailList [data-inzet-row]').length === 0", timeout=10000)
    page.fill("#inzetSearch", "")
    page.wait_for_function(
        "(n) => document.querySelectorAll('#inzetRailList [data-inzet-row]').length === n",
        arg=len(alle), timeout=10000)

    # 'Zonder tijd eerst': binnen elke groep staan machines zonder omsteltijd vooraan.
    page.click('#inzetRailTools button:has-text("zonder tijd eerst")')
    page.wait_for_function("() => _inzetState.sort === 'missing'", timeout=5000)
    volgorde = page.evaluate("() => [...document.querySelectorAll('#inzetRailList [data-inzet-row]')].map(b => b.dataset.inzetRow)")
    zonder = [c for c in volgorde if api["machines"][c]["hours_per_changeover"] is None]
    met = [c for c in volgorde if api["machines"][c]["hours_per_changeover"] is not None]
    if zonder and met:
        assert volgorde.index(zonder[0]) < volgorde.index(met[0])
    page.click('#inzetRailTools button:has-text("kosten")')
    page.wait_for_function("() => _inzetState.sort === 'cost'", timeout=5000)
    assert page.js_errors == []


def test_omsteltijd_is_masterdata_met_versiebump(browser_page, golden_fixture_path):
    """Het omsteltijdveld op het bord schrijft door naar de masterdata (CAS):
    de versie bumpt, de maandregels tonen uren, de wissels verschijnen als
    gaten, en leegmaken verwijdert de regel weer."""
    page = browser_page
    _ensure_store(page.server["base_url"], golden_fixture_path)
    _open_inzet(page)
    base_url = page.server["base_url"]
    api = _api(base_url)
    machine = next(c for c in sorted(api["machines"])
                   if api["machines"][c]["total"]["changeovers"] > 0
                   and api["machines"][c]["hours_per_changeover"] is None)
    _select(page, machine)
    version_before = requests.get(base_url + "/api/master_data/changeover_times",
                                  timeout=60).json()["version"]

    veld = page.locator(f'input[data-inzet-machine="{machine}"]')
    veld.fill("1,5")
    with page.expect_response(lambda r: "/api/master_data/changeover_times" in r.url
                              and r.request.method == "PATCH" and r.ok):
        veld.dispatch_event("change")
    page.wait_for_function(
        "(m) => (_inzetState.data.changeover_times[m] || {}).hours_per_changeover === 1.5",
        arg=machine, timeout=30000)

    store = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
    assert store["version"] == version_before + 1
    assert store["value"][machine]["hours_per_changeover"] == pytest.approx(1.5)
    periode = next(p for p, cel in api["machines"][machine]["per_period"].items() if cel["changeovers"] > 0)
    cel = page.locator(f'#inzetBoard [data-inzet-month="{periode}"] button[data-inzet-cell]')
    assert "u" in cel.inner_text()
    gaten = page.evaluate(
        "(p) => document.querySelectorAll(`#inzetBoard [data-inzet-month=\"${p}\"] [title^=\"omstelling\"]`).length", periode)
    assert gaten == len(api["machines"][machine]["per_period"][periode]["products"]) - 1

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
    """Klik op het maandgetal → invoer → Enter zet een wat-als op het aantal
    omstellingen: amber, persistent over een paginaherlaad (sessiestate), en
    de schatting terugtypen ruimt hem op."""
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
    _select(page, doel["code"])

    def _typ(waarde):
        with page.expect_response(lambda r: "/api/machine_inzet/overrides" in r.url and r.ok):
            page.evaluate(
                """([p, w]) => {
                    const rij = document.querySelector(`#inzetBoard [data-inzet-month="${p}"]`);
                    rij.querySelector('button[data-inzet-cell]').click();
                    const invoer = rij.querySelector('input[data-inzet-edit]');
                    invoer.value = String(w);
                    invoer.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                }""", [doel["p"], waarde])

    _typ(doel["est"] + 3)
    page.wait_for_function(
        "(d) => _inzetState.overrides[`${d.code}|${d.p}`] === d.est + 3",
        arg=doel, timeout=15000)

    _open_inzet(page)
    assert page.evaluate(
        "(d) => _inzetState.overrides[`${d.code}|${d.p}`]", doel) == doel["est"] + 3
    _select(page, doel["code"])
    kleur = page.evaluate(
        "(p) => document.querySelector(`#inzetBoard [data-inzet-month=\"${p}\"] button[data-inzet-cell] span`).className",
        doel["p"])
    assert "text-amber-300" in kleur, "wat-als-cel is niet amber gemarkeerd"

    _typ(doel["est"])
    page.wait_for_function(
        "() => Object.keys(_inzetState.overrides).length === 0", timeout=15000)
    assert page.js_errors == []


def test_volgorde_is_wat_als_en_overleeft_herlaad(browser_page):
    """De volgordechips volgen de API (standaard: grootste run eerst). Een
    pijl verplaatst een product als sessie-wat-als: de API draagt de
    volgorde, hij overleeft een herlaad, de blokken op het bord volgen, en
    'Terug naar standaard' ruimt hem op. Het aantal verandert niet."""
    page = browser_page
    _open_inzet(page)
    base_url = page.server["base_url"]
    api = _api(base_url)
    code = _machine_met_minstens(api, 2)
    if code is None:
        pytest.skip("geen machine met twee producten in deze fixture")
    verwacht = api["machines"][code]["sequence"]
    assert api["machines"][code]["sequence_source"] == "standaard"
    _select(page, code)

    chips = page.evaluate("() => [...document.querySelectorAll('#inzetBoard [data-inzet-seq]')].map(r => r.dataset.inzetSeq)")
    assert chips == verwacht, (chips, verwacht)

    with page.expect_response(lambda r: "/api/machine_inzet/sequences" in r.url and r.ok):
        page.evaluate("(c) => moveInzetProduct(c, 0, 1)", code)
    page.wait_for_function(
        "(c) => _inzetState.data.machines[c].sequence_source === 'wat-als' && _inzetState.selected === c",
        arg=code, timeout=15000)
    nieuw = page.evaluate("(c) => _inzetState.data.machines[c].sequence", code)
    assert nieuw[:2] == [verwacht[1], verwacht[0]] and nieuw[2:] == verwacht[2:]
    assert page.evaluate("() => [...document.querySelectorAll('#inzetBoard [data-inzet-seq]')].map(r => r.dataset.inzetSeq)") == nieuw
    # De blokken in een maand waarin beide producten draaien staan in de nieuwe volgorde.
    periode = next((p for p in api["periods"]
                    if all((api["machines"][code]["product_hours"][m].get(p, 0) or 0) > 0 for m in nieuw[:2])), None)
    if periode:
        titels = page.evaluate(
            "(p) => [...document.querySelectorAll(`#inzetBoard [data-inzet-month=\"${p}\"] .flex-1 > div[title]`)]"
            ".filter(d => !d.title.startsWith('omstelling')).map(d => d.title.split(' — ')[0])", periode)
        assert titels.index(nieuw[0]) < titels.index(nieuw[1]), titels
    na = _api(base_url)
    assert na["machines"][code]["total"]["changeovers"] == api["machines"][code]["total"]["changeovers"]

    _open_inzet(page)
    assert page.evaluate("(c) => _inzetState.sequences[c]", code) == nieuw
    _select(page, code)
    with page.expect_response(lambda r: "/api/machine_inzet/sequences" in r.url and r.ok):
        page.click('#inzetBoard button:has-text("Terug naar standaard")')
    page.wait_for_function(
        "(c) => _inzetState.sequences[c] === undefined && _inzetState.data.machines[c].sequence_source === 'standaard'",
        arg=code, timeout=15000)
    assert page.evaluate("(c) => _inzetState.data.machines[c].sequence", code) == verwacht
    assert page.js_errors == []


def test_tarief_en_kosten_volgen_uit_omsteltijd_en_masterdata(browser_page, golden_fixture_path):
    """Omsteltijd + tarief invullen → de maandregels en de lijst tonen euro's
    die exact omstellingen × omsteltijd × tarief zijn; het tarief is
    masterdata (cost_per_hour, versiebump) en leegmaken valt terug."""
    page = browser_page
    _ensure_store(page.server["base_url"], golden_fixture_path)
    _open_inzet(page)
    base_url = page.server["base_url"]
    api = _api(base_url)
    kandidaten = [c for c in sorted(api["machines"])
                  if api["machines"][c]["total"]["changeovers"] > 0
                  and api["machines"][c]["hours_per_changeover"] is None]
    assert kandidaten, "geen machine met omstellingen zonder ingevulde omsteltijd"
    machine = kandidaten[0]
    _select(page, machine)

    def _zet(selector, waarde, verwacht_js):
        veld = page.locator(selector)
        veld.fill(waarde)
        with page.expect_response(lambda r: "/api/master_data/changeover_times" in r.url
                                  and r.request.method == "PATCH" and r.ok):
            veld.dispatch_event("change")
        page.wait_for_function(verwacht_js, arg=machine, timeout=30000)

    try:
        _zet(f'input[data-inzet-machine="{machine}"]', "2",
             "(m) => _inzetState.data.machines[m].hours_per_changeover === 2")
        _zet(f'input[data-inzet-rate="{machine}"]', "50",
             "(m) => _inzetState.data.machines[m].rate === 50 && _inzetState.data.machines[m].rate_source === 'omsteltijden'")

        na = _api(base_url)
        m = na["machines"][machine]
        assert m["rate"] == 50 and m["rate_source"] == "omsteltijden"
        store = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
        assert store["value"][machine]["cost_per_hour"] == pytest.approx(50.0)
        for periode, cel in m["per_period"].items():
            assert cel["changeover_hours"] == pytest.approx(cel["changeovers"] * 2.0)
            assert cel["cost"] == pytest.approx(cel["changeovers"] * 2.0 * 50.0)
        assert m["total"]["cost"] == pytest.approx(m["total"]["changeovers"] * 100.0)
        periode = next(p for p, cel in m["per_period"].items() if cel["changeovers"] > 0)
        cel_tekst = page.locator(f'#inzetBoard [data-inzet-month="{periode}"] button[data-inzet-cell]').inner_text()
        assert "€" in cel_tekst and "u" in cel_tekst, cel_tekst
        lijst_tekst = page.locator(f'#inzetRailList [data-inzet-row="{machine}"]').inner_text()
        assert "€" in lijst_tekst

        _zet(f'input[data-inzet-rate="{machine}"]', "",
             "(m) => _inzetState.data.machines[m].rate_source !== 'omsteltijden'")
        store = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
        assert store["value"][machine].get("cost_per_hour") is None
        assert store["value"][machine]["hours_per_changeover"] == pytest.approx(2.0)
    finally:
        veld = page.locator(f'input[data-inzet-machine="{machine}"]')
        veld.fill("")
        with page.expect_response(lambda r: "/api/master_data/changeover_times" in r.url
                                  and r.request.method == "PATCH" and r.ok):
            veld.dispatch_event("change")
        page.wait_for_function("(m) => _inzetState.data.changeover_times[m] === undefined",
                               arg=machine, timeout=30000)
    eind = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
    assert machine not in (eind["value"] or {})
    assert page.js_errors == []


def test_combinaties_wonen_nu_hier_en_werkbank_toont_de_stand(browser_page):
    """De combinatiekaart is verhuisd: hij staat op Machine-inzet, en de
    werkbank toont alleen nog de stand met een sprong hierheen."""
    page = browser_page
    _open_inzet(page)
    assert page.evaluate(
        "() => document.getElementById('fteCombinations').closest('.tab-content').id") == "inzet-tab"
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


def test_grid_omsteltijden_heeft_optioneel_tariefveld(browser_page, golden_fixture_path):
    """Het masterdata-grid toont het tarief als optioneel getal: leeg is
    'niet ingevuld' (geen fout, geen stille nul) en een negatief tarief wordt
    door de server geweigerd."""
    page = browser_page
    from tests.browser.test_pw_masterdata import _open_config
    page.reload(wait_until="networkidle")
    _open_config(page)
    _ensure_store(page.server["base_url"], golden_fixture_path)
    page.evaluate("() => loadMasterDataStatus()")
    page.wait_for_function(
        "() => document.querySelectorAll('#masterDatasetButtons button').length > 0", timeout=30000)
    page.evaluate("() => openMasterDatasetModal('changeover_times')")
    page.wait_for_selector("#masterDatasetBody table", timeout=30000)
    koppen = page.evaluate("() => [...document.querySelectorAll('#masterDatasetBody thead th')].map(t => t.textContent)")
    assert any("Tarief" in k for k in koppen), koppen
    page.evaluate("() => _insertMasterRow('changeover_times', 'ZZ_TEST_OMSTEL')")
    page.evaluate(
        """() => {
            const rij = document.querySelector('#masterDatasetBody tr[data-master-key="ZZ_TEST_OMSTEL"]');
            rij.querySelector('[data-master-col="hours_per_changeover"] .master-edit').value = '1';
        }""")
    verzameld = page.evaluate("() => collectMasterDataset('changeover_times')")
    assert "error" not in verzameld, verzameld
    assert "cost_per_hour" not in verzameld["value"]["ZZ_TEST_OMSTEL"] \
        or verzameld["value"]["ZZ_TEST_OMSTEL"]["cost_per_hour"] is None
    base_url = page.server["base_url"]
    cur = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
    slecht = dict(cur["value"] or {})
    slecht["ZZ_TEST_OMSTEL"] = {"machine_code": "ZZ_TEST_OMSTEL", "hours_per_changeover": 1, "cost_per_hour": -3}
    res = requests.patch(base_url + "/api/master_data/changeover_times",
                         json={"value": slecht, "base_version": cur["version"]}, timeout=60)
    assert res.status_code == 400 and "tarief" in res.json()["error"].lower()
    assert page.js_errors == []
