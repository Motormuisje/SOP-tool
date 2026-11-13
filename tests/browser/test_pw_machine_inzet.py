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


def _nl(v, dec):
    """nl-NL-formattering in Python (duizendtalpunt, decimale komma, geen
    volgnullen) — onafhankelijk van de _fmtNlNum van de app."""
    s = f"{v:,.{dec}f}".rstrip("0").rstrip(".")
    return s.replace(",", "X").replace(".", ",").replace("X", ".") or "0"


def _check_kpis(page, api):
    """De vier tegels tonen exact de API-formules (verwachting in Python)."""
    horizon = api["totals"]["horizon"]
    codes = [c for c, m in api["machines"].items()
             if any(cel["hours"] > 0 for cel in m["per_period"].values()) or c in api["changeover_times"]]
    zonder_tijd = [c for c in codes if api["machines"][c]["hours_per_changeover"] is None
                   and api["machines"][c]["total"]["run_hours"] > 0]
    zonder_tarief = [c for c in codes if api["machines"][c]["hours_per_changeover"] is not None
                     and not api["machines"][c]["rate"] > 0]
    tegels = page.evaluate("() => [...document.querySelectorAll('#inzetKpis .kpi-card')].map(k => k.textContent.replace(/\\s+/g, ' ').trim())")
    fmt = lambda v, d: _nl(v or 0, d)
    assert tegels[0].startswith("Omstellingen (horizon) " + fmt(horizon["changeovers"], 0)), tegels[0]
    assert f"{len(codes)} machine(s)" in tegels[0] and fmt(horizon["run_hours"], 0) in tegels[0]
    assert tegels[1].startswith("Omsteluren " + fmt(horizon["changeover_hours"], 1) + " u"), tegels[1]
    if horizon["run_hours"] > 0 and horizon["changeover_hours"] > 0:
        pct = fmt(horizon["changeover_hours"] / horizon["run_hours"] * 100, 1)
        assert f"{pct}% van de draaiuren" in tegels[1], tegels[1]
    assert tegels[2].startswith("Omstelkosten € " + fmt(horizon["cost"], 0)), tegels[2]
    assert tegels[3].startswith(f"Invulstatus {len(zonder_tijd)} zonder omsteltijd"), tegels[3]
    if zonder_tarief:
        assert f"{len(zonder_tarief)} zonder tarief" in tegels[3], tegels[3]
    else:
        assert "elke omsteltijd heeft een tarief" in tegels[3], tegels[3]


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
    _check_kpis(page, api)

    # Standaardsortering: binnen een groep kosten aflopend, daarna code.
    def kosten(c): return api["machines"][c]["total"]["cost"]
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

    # Zoeken: exact de verwachte set (machinecode, naam of productnaam/-nummer,
    # hoofdletterongevoelig); het veld zelf blijft staan (caret intact).
    def _verwacht(q):
        q = q.lower()
        return sorted(c for c in alle if q in c.lower() or q in api["machines"][c]["name"].lower()
                      or any(q in m.lower() or q in n.lower()
                             for m, n in api["machines"][c]["product_names"].items()))

    def _zoek(q):
        page.fill("#inzetSearch", q)
        page.wait_for_function("(q) => _inzetState.query === q", arg=q, timeout=5000)
        return sorted(page.evaluate("() => [...document.querySelectorAll('#inzetRailList [data-inzet-row]')].map(b => b.dataset.inzetRow)"))

    productnaam = api["machines"][doel]["product_names"][api["machines"][doel]["sequence"][0]]
    for q in (productnaam, doel.lower(), api["machines"][doel]["name"][:6].upper(), "ZZ-BESTAAT-NIET"):
        assert _zoek(q) == _verwacht(q), q
    page.fill("#inzetSearch", "abc")
    page.keyboard.press("Home")
    page.keyboard.type("x")
    assert page.input_value("#inzetSearch") == "xabc", "caret sprong naar het einde"
    page.fill("#inzetSearch", "")
    page.wait_for_function("(n) => document.querySelectorAll('#inzetRailList [data-inzet-row]').length === n",
                           arg=len(alle), timeout=10000)

    # Sorteringen: exact de spec, per groep.
    def _groepen():
        return page.evaluate(
            """() => {
                const uit = {}; let g = null;
                for (const el of document.querySelectorAll('#inzetRailList [data-inzet-group], #inzetRailList [data-inzet-row]')) {
                    if (el.dataset.inzetGroup !== undefined) { g = el.dataset.inzetGroup; uit[g] = []; }
                    else uit[g].push(el.dataset.inzetRow);
                }
                return uit;
            }""")
    m = api["machines"]
    keys = {
        "kosten": lambda c: (-m[c]["total"]["cost"], c),
        "omstellingen": lambda c: (-m[c]["total"]["changeovers"], c),
        "zonder tijd eerst": lambda c: (0 if m[c]["hours_per_changeover"] is None else 1, -m[c]["total"]["changeovers"], c),
    }
    for label, key in keys.items():
        page.click(f'#inzetRailTools button:has-text("{label}")')
        page.wait_for_function("(l) => [...document.querySelectorAll('#inzetRailTools button')].some(b => b.textContent === l && b.className.includes('bg-blue-600/40'))",
                               arg=label, timeout=5000)
        for g, codes in _groepen().items():
            assert codes == sorted(codes, key=key), (label, g, codes)
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

    try:
        veld = page.locator(f'input[data-inzet-machine="{machine}"]')
        veld.fill("1,5")
        with page.expect_response(lambda r: "/api/master_data/changeover_times" in r.url
                                  and r.request.method == "PATCH" and r.ok):
            veld.dispatch_event("change")
        page.wait_for_function(
            "(m) => (_inzetState.data.changeover_times[m] || {}).hours_per_changeover === 1.5",
            arg=machine, timeout=30000)
        # Opgeslagen waarde in nl-NL-notatie terug in het veld.
        assert page.input_value(f'input[data-inzet-machine="{machine}"]') == "1,5"

        store = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
        assert store["version"] == version_before + 1
        assert store["value"][machine]["hours_per_changeover"] == pytest.approx(1.5)
        periode = next(p for p, cel in api["machines"][machine]["per_period"].items() if cel["changeovers"] > 0)
        cel = page.locator(f'#inzetBoard [data-inzet-month="{periode}"] button[data-inzet-cell]')
        assert "u" in cel.inner_text()
        gaten = page.evaluate(
            "(p) => document.querySelectorAll(`#inzetBoard [data-inzet-month=\"${p}\"] .inzet-gap`).length", periode)
        assert gaten == len(api["machines"][machine]["per_period"][periode]["products"]) - 1

        veld2 = page.locator(f'input[data-inzet-machine="{machine}"]')
        veld2.fill("")
        with page.expect_response(lambda r: "/api/master_data/changeover_times" in r.url
                                  and r.request.method == "PATCH" and r.ok):
            veld2.dispatch_event("change")
        page.wait_for_function(
            "(m) => _inzetState.data.changeover_times[m] === undefined",
            arg=machine, timeout=30000)
    finally:
        _verwijder_record(base_url, machine)
    eind = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
    assert machine not in (eind["value"] or {})
    assert page.js_errors == []


def _verwijder_record(base_url, machine):
    """Opruimen via de API (niet via de UI): het record weg, versie precies +1
    als er iets te verwijderen was."""
    cur = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
    value = dict(cur["value"] or {})
    if machine not in value:
        return
    del value[machine]
    res = requests.patch(base_url + "/api/master_data/changeover_times",
                         json={"value": value, "base_version": cur["version"]}, timeout=60)
    assert res.ok, res.text
    assert res.json()["version"] == cur["version"] + 1


def _zet_sequences(base_url, sequences):
    res = requests.post(base_url + "/api/machine_inzet/sequences", json={"sequences": sequences}, timeout=60)
    assert res.ok, res.text
    return res.json()


def _zet_overrides(base_url, overrides):
    res = requests.post(base_url + "/api/machine_inzet/overrides", json={"overrides": overrides}, timeout=60)
    assert res.ok, res.text
    return res.json()


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

    try:
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

        # Ongewijzigd wegklikken: geen POST, knop komt lokaal terug.
        posts = []
        page.on("request", lambda r: posts.append(r.url) if "/api/machine_inzet/overrides" in r.url else None)
        page.evaluate(
            """(p) => {
                const rij = document.querySelector(`#inzetBoard [data-inzet-month="${p}"]`);
                rij.querySelector('button[data-inzet-cell]').click();
                rij.querySelector('input[data-inzet-edit]').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            }""", doel["p"])
        page.wait_for_function("(p) => !!document.querySelector(`#inzetBoard [data-inzet-month=\"${p}\"] button[data-inzet-cell]`)",
                               arg=doel["p"], timeout=5000)
        page.evaluate(
            """(p) => {
                const rij = document.querySelector(`#inzetBoard [data-inzet-month="${p}"]`);
                rij.querySelector('button[data-inzet-cell]').click();
                rij.querySelector('input[data-inzet-edit]').dispatchEvent(new Event('blur'));
            }""", doel["p"])
        page.wait_for_function("(p) => !!document.querySelector(`#inzetBoard [data-inzet-month=\"${p}\"] button[data-inzet-cell]`)",
                               arg=doel["p"], timeout=5000)
        page.wait_for_timeout(300)
        assert posts == [], posts

        _typ(doel["est"])
        page.wait_for_function(
            "() => Object.keys(_inzetState.overrides).length === 0", timeout=15000)
    finally:
        _zet_overrides(page.server["base_url"], {})
    assert page.js_errors == []


def test_bordgaten_volgen_het_aantal_ook_bij_wat_als(browser_page, golden_fixture_path):
    """Met een omsteltijd tekent het bord per maand precies zoveel gaten als
    het aantal: schatting = producten − 1; wat-als 0 = geen gaten; wat-als
    boven het aantal overgangen = één extra gat achteraan."""
    page = browser_page
    _ensure_store(page.server["base_url"], golden_fixture_path)
    _open_inzet(page)
    base_url = page.server["base_url"]
    api = _api(base_url)
    code = _machine_met_minstens(api, 3)
    if code is None:
        pytest.skip("geen machine met drie producten in deze fixture")
    periode = next(p for p, cel in api["machines"][code]["per_period"].items() if len(cel["products"]) >= 3)
    n = len(api["machines"][code]["per_period"][periode]["products"])
    try:
        cur = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
        value = dict(cur["value"] or {})
        value[code] = {"machine_code": code, "hours_per_changeover": 1.0}
        assert requests.patch(base_url + "/api/master_data/changeover_times",
                              json={"value": value, "base_version": cur["version"]}, timeout=60).ok

        def _gaten(count):
            _zet_overrides(base_url, {f"{code}|{periode}": count} if count is not None else {})
            _open_inzet(page)
            _select(page, code)
            return page.evaluate(
                "(p) => [...document.querySelectorAll(`#inzetBoard [data-inzet-month=\"${p}\"] .inzet-gap`)].map(g => g.title)", periode)

        assert len(_gaten(None)) == n - 1                      # schatting
        assert _gaten(0) == []                                  # wat-als 0: geen wissel getekend
        extra = _gaten(n + 1)                                   # 2 meer dan overgangen
        assert len(extra) == n and "2 extra" in extra[-1]
        assert page.js_errors == []
    finally:
        _zet_overrides(base_url, {})
        _verwijder_record(base_url, code)


def test_volgorde_is_wat_als_en_overleeft_herlaad(browser_page):
    """De volgordechips volgen de API (standaard: grootste run eerst). Een
    verplaatsing (programmatisch én via de drop-handler) is sessie-wat-als: de API draagt de
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

    def _blokvolgorde():
        """Per maandregel de productvolgorde van de blokken (materiaalnummers)."""
        return page.evaluate(
            "() => [...document.querySelectorAll('#inzetBoard [data-inzet-month]')].map(r =>"
            " [r.dataset.inzetMonth, [...r.querySelectorAll('[data-inzet-mat]')].map(b => b.dataset.inzetMat)])")

    def _check_blokken(seq):
        for maand, blokken in _blokvolgorde():
            assert blokken == [m for m in seq if m in blokken], (maand, blokken, seq)
            assert len(blokken) == len(api["machines"][code]["per_period"][maand]["products"])
    _check_blokken(verwacht)

    # Eerste product ná het tweede zetten (de drop-handler, zonder muis).
    with page.expect_response(lambda r: "/api/machine_inzet/sequences" in r.url and r.ok):
        page.evaluate("([c, s]) => _inzetDropProduct(c, s[0], s[1], true)", [code, verwacht])
    page.wait_for_function(
        "(c) => _inzetState.data.machines[c].sequence_source === 'wat-als' && _inzetState.selected === c",
        arg=code, timeout=15000)
    nieuw = page.evaluate("(c) => _inzetState.data.machines[c].sequence", code)
    assert nieuw[:2] == [verwacht[1], verwacht[0]] and nieuw[2:] == verwacht[2:]

    # No-op-drops doen géén POST: op zichzelf, direct vóór/na de buur, op een
    # onbekend product.
    posts = []
    page.on("request", lambda r: posts.append(r.url) if "/api/machine_inzet/sequences" in r.url else None)
    page.evaluate("""([c, s]) => {
        _inzetDropProduct(c, s[0], s[0], true);
        _inzetDropProduct(c, s[1], s[0], true);
        _inzetDropProduct(c, s[0], s[1], false);
        _inzetDropProduct(c, s[0], 'SPOOK', false);
        _inzetDropProduct(c, 'SPOOK', s[0], false);
    }""", [code, nieuw])
    page.wait_for_timeout(400)
    assert posts == [], posts
    _check_blokken(nieuw)
    na = _api(base_url)
    assert na["machines"][code]["total"]["changeovers"] == api["machines"][code]["total"]["changeovers"]

    # Slepen naar het einde: het eerste product ná het laatste zetten.
    with page.expect_response(lambda r: "/api/machine_inzet/sequences" in r.url and r.ok):
        page.evaluate("([c, s]) => _inzetDropProduct(c, s[0], s[s.length - 1], true)", [code, nieuw])
    page.wait_for_function(
        "([c, last]) => _inzetState.data.machines[c].sequence[_inzetState.data.machines[c].sequence.length - 1] === last",
        arg=[code, nieuw[0]], timeout=15000)
    gesleept = page.evaluate("(c) => _inzetState.data.machines[c].sequence", code)
    assert gesleept == nieuw[1:] + nieuw[:1], (gesleept, nieuw)
    assert page.evaluate("() => document.querySelectorAll('#inzetBoard .inzet-block[draggable=\"true\"]').length > 0")
    # Elk blok heeft een handvat (minimaal 20 px; in een smal venster krimpt dat tot minimaal 8 px) en de balk blijft binnen zijn regel.
    assert page.evaluate("() => [...document.querySelectorAll('#inzetBoard .inzet-block')].every(b => b.getBoundingClientRect().width >= 8)")
    assert page.evaluate("() => [...document.querySelectorAll('#inzetBoard [data-inzet-month]')].every(r => { const first = r.querySelector('[data-inzet-mat]'); if (!first) return true; const bar = first.parentElement; return [...bar.children].reduce((a, k) => a + k.getBoundingClientRect().width, 0) <= bar.getBoundingClientRect().width + 1; })")
    assert page.evaluate("(c) => document.querySelectorAll(`#inzetBoard [data-inzet-legend=\"${c}\"] span[title]`).length", code) == len(gesleept)
    _check_blokken(gesleept)
    nieuw = gesleept

    _open_inzet(page)
    assert page.evaluate("(c) => _inzetState.sequences[c]", code) == nieuw
    _select(page, code)

    # Snoei via de UI-route: een POST met een verouderde entry slaagt, de
    # server snoeit, en de gebruiker ZIET de waarschuwing (notify).
    page.evaluate(
        """() => {
            window.__notes = [];
            const original = window.notify;
            window.notify = (msg, ...rest) => { window.__notes.push(String(msg)); return original(msg, ...rest); };
        }""")
    with page.expect_response(lambda r: "/api/machine_inzet/sequences" in r.url and r.ok):
        page.evaluate("([c, s]) => _postInzetSequences({ [c]: s, ZZ_SPOOK: ['X'] })", [code, nieuw])
    page.wait_for_function(
        "(c) => _inzetState.data && _inzetState.sequences[c] !== undefined && !('ZZ_SPOOK' in _inzetState.sequences)",
        arg=code, timeout=15000)
    assert any("ZZ_SPOOK" in n for n in page.evaluate("() => window.__notes")), "snoei-waarschuwing niet getoond"
    _select(page, code)
    with page.expect_response(lambda r: "/api/machine_inzet/sequences" in r.url and r.ok):
        page.click('#inzetBoard button:has-text("Terug naar standaard")')
    page.wait_for_function(
        "(c) => _inzetState.sequences[c] === undefined && _inzetState.data.machines[c].sequence_source === 'standaard'",
        arg=code, timeout=15000)
    assert page.evaluate("(c) => _inzetState.data.machines[c].sequence", code) == verwacht
    assert requests.get(base_url + "/api/machine_inzet", timeout=60).json()["sequences"] == {}
    assert page.js_errors == []


def test_bord_ververst_na_reset_en_wist_geen_serverstate(browser_page):
    """Na Reset (server wist de wat-als) mag een verouderde clientkopie nooit
    de gewiste volgorde/aantallen terugschrijven: _invalidateInzet herlaadt
    het open tabblad en de eerstvolgende actie stuurt alleen de echte stand."""
    page = browser_page
    _open_inzet(page)
    base_url = page.server["base_url"]
    api = _api(base_url)
    code = _machine_met_minstens(api, 2)
    if code is None:
        pytest.skip("geen machine met twee producten in deze fixture")
    seq = api["machines"][code]["sequence"]
    periode = api["periods"][0]
    try:
        _zet_sequences(base_url, {code: seq[1:] + seq[:1]})
        _zet_overrides(base_url, {f"{code}|{periode}": 7})
        _open_inzet(page)
        assert page.evaluate("(c) => _inzetState.data.machines[c].sequence_source", code) == "wat-als"
        # Server-side 'Reset' zonder de UI: daarna is de clientkopie verouderd.
        _zet_sequences(base_url, {})
        _zet_overrides(base_url, {})
        with page.expect_response(lambda r: "/api/machine_inzet" in r.url and r.request.method == "GET" and r.ok):
            page.evaluate("() => _invalidateInzet()")
        page.wait_for_function(
            "(c) => _inzetState.data && _inzetState.data.machines[c].sequence_source === 'standaard' && Object.keys(_inzetState.overrides).length === 0",
            arg=code, timeout=15000)
        _select(page, code)
        # Een nieuwe volgorde-actie stuurt alleen déze machine, niet de oude kopie.
        with page.expect_response(lambda r: "/api/machine_inzet/sequences" in r.url and r.ok) as resp:
            page.evaluate("([c, s]) => _inzetDropProduct(c, s[0], s[1], true)", [code, seq])
        assert set(resp.value.request.post_data_json["sequences"]) == {code}
        na = requests.get(base_url + "/api/machine_inzet", timeout=60).json()
        assert na["overrides"] == {} and set(na["sequences"]) == {code}
    finally:
        _zet_sequences(base_url, {})
        _zet_overrides(base_url, {})
    assert page.js_errors == []


def test_labels_zijn_uniek_en_kort(browser_page):
    """_inzetLabels: basisnaam; bij botsing het gewicht; dan alleen de
    afwijkende specvelden; als laatste het materiaalnummer. Altijd uniek."""
    page = browser_page
    _open_inzet(page)
    names = {
        "1": "Chalk B38 PO 800:B4S:H4:NB:800",
        "2": "Chalk B38 PO 1000:B4S:H4:NB:1000",
        "3": "Chalk B38 PO 750:B4S:H4:NB:750",
        "4": "Bentonite D90 PO 1000:B4S:NO:NB:1000",
        "5": "Bentonite D90 PO 1000:B4S:H2:NB:1000",
        "6": "Glass Fibre GL3B PO 1000:B4S:H4:NB:1000",
        "7": "Kaolin K1 BB 1000:B4S",
        "8": "Kaolin K1",
        "9": "Zelfde naam",
        "10": "Zelfde naam",
        "11": "",
    }
    labels = page.evaluate("([mats, names]) => _inzetLabels(mats, names)", [list(names), names])
    assert labels["1"] == "Chalk B38 · 800" and labels["2"] == "Chalk B38 · 1000" and labels["3"] == "Chalk B38 · 750"
    assert labels["4"] == "Bentonite D90 · 1000 · NO" and labels["5"] == "Bentonite D90 · 1000 · H2"
    assert labels["6"] == "Glass Fibre GL3B"
    assert labels["7"] == "Kaolin K1 · BB 1000" and labels["8"] == "Kaolin K1"
    assert labels["9"] == "Zelfde naam · 9" and labels["10"] == "Zelfde naam · 10"
    assert labels["11"] == "11"
    assert len(set(labels.values())) == len(names)
    assert page.js_errors == []


def test_grid_leegmaken_van_tarief_verwijdert_het_veld(browser_page, golden_fixture_path):
    """Bestaand tarief leegmaken in het grid → sleutel weg (terugval op het
    machinetarief), niet 0 en geen fout; omsteltijd leegmaken → fout."""
    page = browser_page
    from tests.browser.test_pw_masterdata import _open_config
    base_url = page.server["base_url"]
    _ensure_store(base_url, golden_fixture_path)
    machine = sorted(_api(base_url)["machines"])[0]
    try:
        cur = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
        value = dict(cur["value"] or {})
        value[machine] = {"machine_code": machine, "hours_per_changeover": 1.0, "cost_per_hour": 50.0}
        assert requests.patch(base_url + "/api/master_data/changeover_times",
                              json={"value": value, "base_version": cur["version"]}, timeout=60).ok
        page.reload(wait_until="networkidle")
        _open_config(page)
        page.evaluate("() => loadMasterDataStatus()")
        page.wait_for_function("() => document.querySelectorAll('#masterDatasetButtons button').length > 0", timeout=30000)
        page.evaluate("() => openMasterDatasetModal('changeover_times')")
        page.wait_for_selector(f'#masterDatasetBody tr[data-master-key="{machine}"]', timeout=30000)
        page.evaluate(
            """(m) => { document.querySelector(`#masterDatasetBody tr[data-master-key="${m}"] [data-master-col="cost_per_hour"] .master-edit`).value = ''; }""", machine)
        verzameld = page.evaluate("() => collectMasterDataset('changeover_times')")
        assert "error" not in verzameld, verzameld
        assert verzameld["value"][machine].get("cost_per_hour") is None
        assert verzameld["value"][machine]["hours_per_changeover"] == 1.0
        # Omsteltijd leegmaken is wél een fout (kind 'number').
        page.evaluate(
            """(m) => { document.querySelector(`#masterDatasetBody tr[data-master-key="${m}"] [data-master-col="hours_per_changeover"] .master-edit`).value = ''; }""", machine)
        assert "error" in page.evaluate("() => collectMasterDataset('changeover_times')")
        assert page.js_errors == []
    finally:
        _verwijder_record(base_url, machine)


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

        # Omsteltijd leegmaken terwijl er een tarief staat: geweigerd (geen
        # stil dataverlies), record ongewijzigd, versie ongewijzigd.
        versie = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()["version"]
        veld = page.locator(f'input[data-inzet-machine="{machine}"]')
        veld.fill("")
        veld.dispatch_event("change")
        page.wait_for_function("(m) => document.querySelector(`input[data-inzet-machine=\"${m}\"]`).value !== ''",
                               arg=machine, timeout=15000)
        assert requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()["version"] == versie

        _zet(f'input[data-inzet-rate="{machine}"]', "",
             "(m) => _inzetState.data.machines[m].rate_source !== 'omsteltijden'")
        store = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
        assert store["value"][machine].get("cost_per_hour") is None
        assert store["value"][machine]["hours_per_changeover"] == pytest.approx(2.0)
        # Zonder tarief mag leegmaken wél: het record verdwijnt.
        veld = page.locator(f'input[data-inzet-machine="{machine}"]')
        veld.fill("")
        with page.expect_response(lambda r: "/api/master_data/changeover_times" in r.url
                                  and r.request.method == "PATCH" and r.ok):
            veld.dispatch_event("change")
        page.wait_for_function("(m) => _inzetState.data.changeover_times[m] === undefined",
                               arg=machine, timeout=30000)
    finally:
        _verwijder_record(base_url, machine)
    eind = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
    assert machine not in (eind["value"] or {})
    assert page.js_errors == []


def test_combinaties_wonen_hier_en_werkbank_heeft_een_eigen_ingang(browser_page):
    """De combinatiekaart staat op Machine-inzet. De werkbank toonde daarna
    alleen de stand met een sprong hierheen; sinds de inspecteur
    (docs/plan-werkbank-inspecteur.md §3) is die standregel vervangen door een
    eigen ingang: de knop 'Combineren'. Deze test pinde nog de standregel en
    faalde sinds die verdween."""
    page = browser_page
    _open_inzet(page)
    assert page.evaluate(
        "() => document.getElementById('fteCombinations').closest('.tab-content').id") == "inzet-tab"
    page.evaluate("() => showTab('fte')")
    expect(page.locator("#fteCombineBtn")).to_have_text("Combineren", timeout=15000)
    assert page.evaluate(
        "() => document.getElementById('fteCombineBtn').closest('.tab-content').id") == "fte-tab"
    expect(page.locator("#fteCombiSummary")).to_have_count(0)
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


def test_opslagketen_omsteltijd_en_tarief_direct_na_elkaar(browser_page, golden_fixture_path):
    """Omsteltijd invullen en meteen het tarief (zonder op de PATCH te
    wachten): de keten serialiseert, beide landen in de masterdata, geen
    'Vul eerst een omsteltijd in' en geen valse 409."""
    page = browser_page
    _ensure_store(page.server["base_url"], golden_fixture_path)
    _open_inzet(page)
    base_url = page.server["base_url"]
    api = _api(base_url)
    machine = next(c for c in sorted(api["machines"])
                   if api["machines"][c]["total"]["changeovers"] > 0
                   and api["machines"][c]["hours_per_changeover"] is None)
    _select(page, machine)
    page.evaluate(
        """() => {
            window.__notes = [];
            const original = window.notify;
            window.notify = (msg, ...rest) => { window.__notes.push(String(msg)); return original(msg, ...rest); };
        }""")
    try:
        versie = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()["version"]
        page.evaluate(
            """(m) => {
                const uren = document.querySelector(`input[data-inzet-machine="${m}"]`);
                const tarief = document.querySelector(`input[data-inzet-rate="${m}"]`);
                uren.value = '2'; tarief.value = '50';
                saveChangeoverTime(uren);
                saveChangeoverRate(tarief);   // direct erachteraan, zonder te wachten
            }""", machine)
        page.wait_for_function(
            "(m) => _inzetState.data && _inzetState.data.machines[m] && _inzetState.data.machines[m].rate === 50"
            " && _inzetState.data.machines[m].rate_source === 'omsteltijden'"
            " && _inzetState.data.machines[m].hours_per_changeover === 2", arg=machine, timeout=30000)
        store = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
        assert store["value"][machine]["hours_per_changeover"] == pytest.approx(2.0)
        assert store["value"][machine]["cost_per_hour"] == pytest.approx(50.0)
        assert store["version"] == versie + 2
        notes = page.evaluate("() => window.__notes")
        assert not any("Vul eerst" in n or "Iemand anders" in n for n in notes), notes
    finally:
        _verwijder_record(page.server["base_url"], machine)
    assert page.js_errors == []


def test_typend_veld_wordt_niet_half_gecommit_door_een_herlaad(browser_page, golden_fixture_path):
    """Terwijl de omsteltijd-PATCH loopt typt de gebruiker het tarief. De
    re-render na de PATCH mag het half getypte tarief NIET committen (change
    bij DOM-verwijdering is geen invoer) en niet wegvegen; pas de echte
    Tab/blur slaat het volledige bedrag op."""
    page = browser_page
    _ensure_store(page.server["base_url"], golden_fixture_path)
    _open_inzet(page)
    base_url = page.server["base_url"]
    api = _api(base_url)
    machine = next(c for c in sorted(api["machines"])
                   if api["machines"][c]["total"]["changeovers"] > 0
                   and api["machines"][c]["hours_per_changeover"] is None)
    _select(page, machine)
    vastgehouden = []

    def _onderschep(route):
        if route.request.method == "PATCH":
            vastgehouden.append(route)
        else:
            route.continue_()

    page.route("**/api/master_data/changeover_times", _onderschep)
    try:
        uren = page.locator(f'input[data-inzet-machine="{machine}"]')
        uren.fill("2")
        uren.dispatch_event("change")           # PATCH wordt vastgehouden
        tarief = page.locator(f'input[data-inzet-rate="{machine}"]')
        tarief.click()
        tarief.type("12")                        # half getypt bedrag
        for _ in range(100):
            if vastgehouden:
                break
            page.wait_for_timeout(100)
        assert vastgehouden, "PATCH niet onderschept"
        vastgehouden[0].continue_()              # opslag rondt af → herlaad + re-render
        page.unroute("**/api/master_data/changeover_times")   # ná de continue: unroute zou hem zelf al afhandelen
        page.wait_for_function(
            "(m) => _inzetState.data && _inzetState.data.machines[m] && _inzetState.data.machines[m].hours_per_changeover === 2",
            arg=machine, timeout=30000)
        page.wait_for_timeout(400)               # eventuele (foute) tweede PATCH de kans geven
        store = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
        assert store["value"][machine].get("cost_per_hour") is None, "half getypt tarief is gecommit"
        # De ingetypte tekst staat er nog; afronden met een echte change slaat 120 op.
        veld = page.locator(f'input[data-inzet-rate="{machine}"]')
        assert veld.input_value() == "12"
        veld.type("0")
        with page.expect_response(lambda r: "/api/master_data/changeover_times" in r.url
                                  and r.request.method == "PATCH" and r.ok):
            veld.dispatch_event("change")
        page.wait_for_function(
            "(m) => _inzetState.data && _inzetState.data.machines[m].rate === 120", arg=machine, timeout=30000)
        store = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
        assert store["value"][machine]["cost_per_hour"] == pytest.approx(120.0)
    finally:
        try:
            page.unroute("**/api/master_data/changeover_times")
        except Exception:
            pass
        _verwijder_record(base_url, machine)
    assert page.js_errors == []


def test_duizendtal_invoer_wordt_niet_als_decimaal_gelezen(browser_page, golden_fixture_path):
    """'1.250' is nl-NL-groepering: opgeslagen als 1250, en het veld toont
    daarna '1250' (zonder duizendtalpunt) zodat weergave en parser elkaars
    inverse blijven."""
    page = browser_page
    _ensure_store(page.server["base_url"], golden_fixture_path)
    _open_inzet(page)
    base_url = page.server["base_url"]
    api = _api(base_url)
    machine = next(c for c in sorted(api["machines"])
                   if api["machines"][c]["total"]["changeovers"] > 0
                   and api["machines"][c]["hours_per_changeover"] is None)
    _select(page, machine)
    try:
        veld = page.locator(f'input[data-inzet-machine="{machine}"]')
        veld.fill("1")
        with page.expect_response(lambda r: "/api/master_data/changeover_times" in r.url
                                  and r.request.method == "PATCH" and r.ok):
            veld.dispatch_event("change")
        page.wait_for_function(
            "(m) => _inzetState.data && _inzetState.data.machines[m].hours_per_changeover === 1",
            arg=machine, timeout=30000)
        tarief = page.locator(f'input[data-inzet-rate="{machine}"]')
        tarief.fill("1.250")
        with page.expect_response(lambda r: "/api/master_data/changeover_times" in r.url
                                  and r.request.method == "PATCH" and r.ok):
            tarief.dispatch_event("change")
        page.wait_for_function(
            "(m) => _inzetState.data && _inzetState.data.machines[m].rate === 1250", arg=machine, timeout=30000)
        store = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
        assert store["value"][machine]["cost_per_hour"] == pytest.approx(1250.0)
        assert page.input_value(f'input[data-inzet-rate="{machine}"]') == "1250"
        assert ",25" not in page.input_value(f'input[data-inzet-rate="{machine}"]')
    finally:
        _verwijder_record(base_url, machine)
    assert page.js_errors == []


def test_override_gelijk_aan_de_schatting_blijft_opruimbaar(browser_page):
    """Een wat-als dat toevallig gelijk is aan de schatting blijft amber; de
    schatting typen ruimt hem alsnog op (de geen-POST-kortsluiting geldt
    alleen zonder override)."""
    page = browser_page
    _open_inzet(page)
    base_url = page.server["base_url"]
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
    try:
        _zet_overrides(base_url, {f"{doel['code']}|{doel['p']}": doel["est"]})
        _open_inzet(page)
        _select(page, doel["code"])
        assert page.evaluate(
            "(d) => _inzetCount(d.code, d.p).isOverride", doel) is True
        with page.expect_response(lambda r: "/api/machine_inzet/overrides" in r.url and r.ok):
            page.evaluate(
                """(d) => {
                    const rij = document.querySelector(`#inzetBoard [data-inzet-month="${d.p}"]`);
                    rij.querySelector('button[data-inzet-cell]').click();
                    const invoer = rij.querySelector('input[data-inzet-edit]');
                    invoer.value = String(d.est);
                    invoer.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                }""", doel)
        page.wait_for_function("() => Object.keys(_inzetState.overrides).length === 0", timeout=15000)
    finally:
        _zet_overrides(base_url, {})
    assert page.js_errors == []


def test_reset_ververst_het_bord_via_het_echte_pad(browser_page):
    """Reset via de echte knopfunctie (resetAllEdits) ververst het bord: de
    wat-als is weg en de verouderde clientkopie kan niets terugschrijven.
    Een klik op de al-actieve sessie herlaadt juist NIET (geen onnodige GET)."""
    page = browser_page
    _open_inzet(page)
    base_url = page.server["base_url"]
    api = _api(base_url)
    code = _machine_met_minstens(api, 2)
    if code is None:
        pytest.skip("geen machine met twee producten in deze fixture")
    seq = api["machines"][code]["sequence"]
    try:
        _zet_sequences(base_url, {code: seq[1:] + seq[:1]})
        _open_inzet(page)
        assert page.evaluate("(c) => _inzetState.data.machines[c].sequence_source", code) == "wat-als"
        page.evaluate("() => { window.confirm = () => true; }")
        with page.expect_response(lambda r: "/api/machine_inzet" in r.url and r.request.method == "GET" and r.ok):
            page.evaluate("() => resetAllEdits()")
        page.wait_for_function(
            "(c) => _inzetState.data && _inzetState.data.machines[c].sequence_source === 'standaard'",
            arg=code, timeout=30000)
        assert requests.get(base_url + "/api/machine_inzet", timeout=60).json()["sequences"] == {}
        # Volgende actie stuurt alleen de eigen wijziging (kopie is vers).
        _select(page, code)
        with page.expect_response(lambda r: "/api/machine_inzet/sequences" in r.url and r.ok) as resp:
            page.evaluate("([c, s]) => _inzetDropProduct(c, s[0], s[1], true)", [code, seq])
        assert set(resp.value.request.post_data_json["sequences"]) == {code}
        # Wissel naar de al-actieve sessie: géén onnodige herlaad van het bord.
        actief = requests.get(base_url + "/api/sessions", timeout=60).json()["active_session_id"]
        gets = []
        page.on("request", lambda r: gets.append(r.url) if "/api/machine_inzet" in r.url and r.method == "GET" else None)
        page.evaluate("(sid) => switchSession(sid)", actief)
        page.wait_for_timeout(800)
        assert gets == [], gets
    finally:
        _zet_sequences(base_url, {})
        _open_inzet(page)
    assert page.js_errors == []


def test_aannames_voor_ontbrekende_omsteltijden(browser_page, golden_fixture_path):
    """Ontbrekende omsteltijden zijn met één knop als AANNAME in te vullen:
    ze tellen meteen mee in uren en kosten, staan zichtbaar als 'aanname'
    gemarkeerd, en 'verwijder ongewijzigde aannames' haalt ze weer weg zonder
    een aangepaste waarde mee te nemen. De test ruimt zelf op: de server
    wordt gedeeld met tests die juist machines zónder omsteltijd zoeken."""
    page = browser_page
    base_url = page.server["base_url"]
    _ensure_store(base_url, golden_fixture_path)
    page.on("dialog", lambda dialog: dialog.accept())
    _open_inzet(page)
    page.wait_for_selector('#inzetPlaceholders [data-inzet-placeholder="apply"]', timeout=30000)
    status = requests.get(base_url + "/api/machine_inzet/placeholders", timeout=60).json()
    missing = status["would_add"]
    assert missing, status
    adjusted = None
    try:
        with page.expect_response(lambda r: "/api/machine_inzet/placeholders" in r.url
                                  and r.request.method == "POST" and r.ok):
            page.click('#inzetPlaceholders [data-inzet-placeholder="apply"]')
        page.wait_for_function(
            "(n) => _inzetPlaceholders && (_inzetPlaceholders.assumed || []).length === n",
            arg=len(missing), timeout=30000)
        api = _api(base_url)
        for code in missing:
            if code in api["machines"]:
                assert api["machines"][code]["hours_origin"] == "aanname", code
                assert api["machines"][code]["hours_per_changeover"] is not None
        chip_count = page.evaluate(
            "() => [...document.querySelectorAll('#inzetRailList [data-inzet-row]')]"
            ".filter(b => b.textContent.includes('aanname')).length")
        assert chip_count == sum(1 for c in missing if c in api["machines"])
        assert "aanname" in page.inner_text("#inzetPlaceholders")

        # Eén waarde aanpassen op het bord: telt daarna niet meer als aanname.
        adjusted = next(c for c in sorted(missing) if c in api["machines"])
        _select(page, adjusted)
        veld = page.locator(f'input[data-inzet-machine="{adjusted}"]')
        veld.fill("3,25")
        with page.expect_response(lambda r: "/api/master_data/changeover_times" in r.url
                                  and r.request.method == "PATCH" and r.ok):
            veld.dispatch_event("change")
        page.wait_for_function(
            "(m) => (_inzetPlaceholders.adjusted || []).includes(m)", arg=adjusted, timeout=30000)

        with page.expect_response(lambda r: "/api/machine_inzet/placeholders" in r.url
                                  and r.request.method == "POST" and r.ok):
            page.click('#inzetPlaceholders [data-inzet-placeholder="remove"]')
        page.wait_for_function(
            "() => _inzetPlaceholders && (_inzetPlaceholders.assumed || []).length === 0", timeout=30000)
        store = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()["value"]
        assert store[adjusted]["hours_per_changeover"] == pytest.approx(3.25)
        assert not any(c in store for c in missing if c != adjusted)
        assert page.js_errors == []
    finally:
        record = requests.get(base_url + "/api/master_data/changeover_times", timeout=60).json()
        value = {k: v for k, v in (record.get("value") or {}).items()
                 if k not in missing}
        requests.patch(base_url + "/api/master_data/changeover_times",
                       json={"value": value, "base_version": record.get("version")}, timeout=60)
