"""Machine-inzet fase 1 + 1b: omstellingen, volgorde, kosten & combinaties.

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
    cel = page.locator(f'#inzetTableBody tr[data-inzet-row="{machine}"] td button[data-inzet-cell]').first
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
                const invoer = rij.querySelector('td input[data-inzet-edit]');
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
                const invoer = rij.querySelector('td input[data-inzet-edit]');
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


# ── Fase 1b (klantvraag 2026-08-26): volgorde, tarief en kosten ──────────────

def _machine_met_minstens(api, n_producten):
    """Eerste machine (alfabetisch) die in de horizon ≥ n producten draait."""
    for code in sorted(api["machines"]):
        if len(api["machines"][code]["sequence"]) >= n_producten:
            return code
    return None


def test_detailrij_toont_producten_in_volgorde_en_pijlen_zijn_wat_als(browser_page):
    """Klik op een machine → detailrij met de producten in de volgorde van de
    API (standaard: grootste run eerst). Een pijl verplaatst een product als
    sessie-wat-als: de API draagt de volgorde, hij overleeft een herlaad, en
    'Terug naar standaard' ruimt hem op."""
    page = browser_page
    _open_inzet(page)
    base_url = page.server["base_url"]
    api = _api(base_url)
    code = _machine_met_minstens(api, 2)
    if code is None:
        pytest.skip("geen machine met twee producten in deze fixture")
    verwacht = api["machines"][code]["sequence"]
    assert api["machines"][code]["sequence_source"] == "standaard"

    # KPI-strip staat er met vier tegels en het horizontotaal van de API.
    tegels = page.evaluate("() => document.querySelectorAll('#inzetKpis .kpi-card').length")
    assert tegels == 4
    assert page.evaluate("() => document.getElementById('inzetKpis').textContent") \
        .find(str(api["totals"]["horizon"]["changeovers"])) >= 0

    page.click(f'#inzetTableBody tr[data-inzet-row="{code}"] td button')
    expect(page.locator(f'tr[data-inzet-detail="{code}"]')).to_be_visible(timeout=15000)
    getoond = page.evaluate(
        "(c) => [...document.querySelectorAll(`tr[data-inzet-detail=\"${c}\"] tr[data-inzet-seq]`)]"
        ".map(r => r.dataset.inzetSeq)", code)
    assert getoond == verwacht, (getoond, verwacht)

    # Eerste product één plaats omlaag: POST /sequences, daarna herrekent de server.
    with page.expect_response(lambda r: "/api/machine_inzet/sequences" in r.url and r.ok):
        page.evaluate("(c) => moveInzetProduct(c, 0, 1)", code)
    page.wait_for_function(
        "(c) => (_inzetState.sequences[c] || [])[0] === _inzetState.data.machines[c].sequence[0]"
        " && _inzetState.data.machines[c].sequence_source === 'wat-als'", arg=code, timeout=15000)
    nieuw = page.evaluate("(c) => _inzetState.data.machines[c].sequence", code)
    assert nieuw[:2] == [verwacht[1], verwacht[0]] and nieuw[2:] == verwacht[2:]
    # De detailrij is na de herlaad van de data nog open (gebruikersstaat
    # mag een re-render niet stil terugdraaien) en toont de nieuwe volgorde.
    expect(page.locator(f'tr[data-inzet-detail="{code}"]')).to_be_visible()
    assert page.evaluate(
        "(c) => [...document.querySelectorAll(`tr[data-inzet-detail=\"${c}\"] tr[data-inzet-seq]`)]"
        ".map(r => r.dataset.inzetSeq)", code) == nieuw
    # Het aantal omstellingen verandert niet door de volgorde (fase 3-grens).
    assert _api(base_url)["machines"][code]["total"]["changeovers"] \
        == api["machines"][code]["total"]["changeovers"]

    # Herlaad: de wat-als komt uit de sessie terug.
    _open_inzet(page)
    assert page.evaluate("(c) => _inzetState.sequences[c]", code) == nieuw
    assert page.evaluate("(c) => _inzetState.data.machines[c].sequence_source", code) == "wat-als"

    # Opruimen: terug naar standaard.
    page.click(f'#inzetTableBody tr[data-inzet-row="{code}"] td button')
    expect(page.locator(f'tr[data-inzet-detail="{code}"]')).to_be_visible(timeout=15000)
    with page.expect_response(lambda r: "/api/machine_inzet/sequences" in r.url and r.ok):
        page.click(f'tr[data-inzet-detail="{code}"] button:has-text("Terug naar standaard")')
    page.wait_for_function(
        "(c) => _inzetState.sequences[c] === undefined"
        " && _inzetState.data.machines[c].sequence_source === 'standaard'", arg=code, timeout=15000)
    assert page.evaluate("(c) => _inzetState.data.machines[c].sequence", code) == verwacht
    assert page.js_errors == []


def test_tarief_en_kosten_volgen_uit_omsteltijd_en_masterdata(browser_page, golden_fixture_path):
    """Omsteltijd + tarief invullen → de cellen en totalen tonen euro's die
    exact omstellingen × omsteltijd × tarief zijn; het tarief is masterdata
    (cost_per_hour, versiebump) en leegmaken valt terug op het machinetarief."""
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
        assert store["value"][machine]["hours_per_changeover"] == pytest.approx(2.0)
        for periode, cel in m["per_period"].items():
            assert cel["changeover_hours"] == pytest.approx(cel["changeovers"] * 2.0)
            assert cel["cost"] == pytest.approx(cel["changeovers"] * 2.0 * 50.0)
        assert m["total"]["cost"] == pytest.approx(m["total"]["changeovers"] * 100.0)
        assert na["totals"]["horizon"]["cost"] >= m["total"]["cost"]
        # Een cel met omstellingen toont de euro's; de horizonkolom ook.
        periode = next(p for p, cel in m["per_period"].items() if cel["changeovers"] > 0)
        cel_tekst = page.evaluate(
            """([m, p]) => [...document.querySelectorAll(`#inzetTableBody tr[data-inzet-row="${m}"] td button`)]
                .find(b => b.getAttribute('onclick').includes(`'${p}'`)).textContent""", [machine, periode])
        assert "€" in cel_tekst and "u" in cel_tekst, cel_tekst
        rij_tekst = page.locator(f'#inzetTableBody tr[data-inzet-row="{machine}"] td:last-child').inner_text()
        assert "€" in rij_tekst

        # Tarief leegmaken: veld verdwijnt uit het record, terugval op het
        # machinetarief (of eerlijk 'geen tarief' als de machine er geen heeft).
        _zet(f'input[data-inzet-rate="{machine}"]', "",
             "(m) => _inzetState.data.machines[m].rate_source !== 'omsteltijden'")
        store = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
        assert store["value"][machine].get("cost_per_hour") is None
        assert store["value"][machine]["hours_per_changeover"] == pytest.approx(2.0)
    finally:
        # Opruimen: omsteltijd leegmaken verwijdert de regel weer.
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
    # Een rij met leeg tarief levert bij het verzamelen géén fout en géén 0.
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
    # Negatief tarief: server weigert (400), niets opgeslagen.
    base_url = page.server["base_url"]
    cur = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
    slecht = dict(cur["value"] or {})
    slecht["ZZ_TEST_OMSTEL"] = {"machine_code": "ZZ_TEST_OMSTEL", "hours_per_changeover": 1, "cost_per_hour": -3}
    res = requests.patch(base_url + "/api/master_data/changeover_times",
                         json={"value": slecht, "base_version": cur["version"]}, timeout=60)
    assert res.status_code == 400 and "tarief" in res.json()["error"].lower()
    assert page.js_errors == []
