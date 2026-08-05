"""Algemene UI-navigatie en het MoM-tabblad, op een live server.

Deze twee horen bij elkaar: navigatie is het enige pad naar élk ander tabblad,
en MoM is het tabblad dat als enige volledig van een aparte API-payload leeft
(`/api/mom`). Gaat er iets stuk in `showTab`, `_saveUiPrefs`, de busy-overlay of
`notify`, dan merkt de gebruiker dat overal tegelijk — daarom worden ze hier op
gedrag getoetst en niet alleen op "element bestaat".

Selector-inventaris:
- `button.tab-btn[onclick*="showTab('<naam>'"]` — de tabknop; `#<naam>-tab` is
  het bijbehorende paneel (`.tab-content`, verborgen met de klasse `hidden`).
- `#busyOverlay` — modale wachtlaag; `hidden` = weg, `show` = zichtbaar.
- `#appNotice` — de toastmelding van `notify()`; `show` + `notice-<niveau>`.
- `#log` — de tekstbak van het Log-tabblad, gevuld door `log()`.
- `#momBannerText`, `#momKpi*`, `#momBody` — banner, KPI's en detailtabel van MoM.
"""

import re

import pytest
import requests
from playwright.sync_api import expect


pytestmark = pytest.mark.browser


# Alle tabbladen die de knoppenbalk aanbiedt, in schermvolgorde.
ALLE_TABBLADEN = [
    "dashboard",
    "planning",
    "values",
    "capacity",
    "fte",
    "inventory",
    "mom",
    "log",
    "config",
]


def _wacht_tot_geladen(page):
    """Wacht tot de app klaar is met opstarten (overlay weg)."""
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)


def _open_tab(page, naam):
    page.locator(f"button.tab-btn[onclick*=\"showTab('{naam}'\"]").click()
    expect(page.locator(f"#{naam}-tab")).to_be_visible(timeout=60000)


def _mom_payload(base_url, num_months=6):
    response = requests.get(f"{base_url}/api/mom?num_months={num_months}", timeout=180)
    response.raise_for_status()
    return response.json()


def _open_mom(page):
    """Open MoM en wacht tot de fetch klaar is (banner is niet meer 'Loading')."""
    _wacht_tot_geladen(page)
    _open_tab(page, "mom")
    page.wait_for_function(
        """() => {
            const t = document.getElementById('momBannerText').textContent || '';
            return t.trim() !== '' && !/^Loading MoM/.test(t);
        }""",
        timeout=120000,
    )


@pytest.mark.parametrize("tabnaam", ALLE_TABBLADEN)
def test_elk_tabblad_opent_zonder_js_fout(browser_page, tabnaam):
    """Elk tabblad moet met één klik open te krijgen zijn zonder JS-fout.

    `showTab()` doet per tabblad iets anders (laadt machines, FTE, inventory,
    config of MoM). Eén kapotte laadroutine zet niet alleen dat tabblad leeg,
    maar breekt de JS-uitvoering af — waarna óók de rest van de pagina niet
    meer reageert. Dit is de rookmelder daarvoor: paneel zichtbaar, de knop
    actief, exact één paneel open, en de console schoon.
    """
    page = browser_page
    _wacht_tot_geladen(page)

    _open_tab(page, tabnaam)
    page.wait_for_load_state("networkidle")

    zichtbaar = page.evaluate(
        """() => Array.from(document.querySelectorAll('.tab-content'))
                      .filter(el => !el.classList.contains('hidden'))
                      .map(el => el.id)"""
    )
    assert zichtbaar == [f"{tabnaam}-tab"], (
        f"na openen van {tabnaam} stonden deze panelen open: {zichtbaar}"
    )
    assert page.evaluate("() => _activeTabName") == tabnaam

    knoppen_actief = page.evaluate(
        """() => Array.from(document.querySelectorAll('button.tab-btn'))
                      .filter(b => b.classList.contains('active'))
                      .map(b => (b.getAttribute('onclick') || ''))"""
    )
    assert len(knoppen_actief) == 1, f"aantal actieve tabknoppen: {knoppen_actief}"
    assert f"showTab('{tabnaam}'" in knoppen_actief[0]

    assert page.js_errors == []


def test_actief_tabblad_overleeft_een_herlaad(browser_page):
    """Wie op Inventory staat en F5 drukt, hoort op Inventory terug te komen.

    `showTab()` schrijft `_activeTabName` weg via `_saveUiPrefs()`; bij het
    laden leest `_restoreUiPrefs()` hem terug en opent de opstartcode dat
    tabblad. Valt één van die drie schakels weg, dan landt de gebruiker na elke
    herberekening of herlaad weer op het dashboard en is hij zijn plek kwijt.
    """
    page = browser_page
    _wacht_tot_geladen(page)

    # Vooraf staat de app op het dashboard; anders zegt de test straks niets.
    assert page.evaluate("() => _activeTabName") == "dashboard"

    _open_tab(page, "inventory")
    opgeslagen = page.evaluate(
        "() => JSON.parse(localStorage.getItem('sop_ui_prefs_v1') || '{}').activeTab"
    )
    assert opgeslagen == "inventory", "showTab() legde het actieve tabblad niet vast"

    page.reload(wait_until="networkidle")
    _wacht_tot_geladen(page)

    expect(page.locator("#inventory-tab")).to_be_visible(timeout=60000)
    assert page.evaluate("() => _activeTabName") == "inventory"
    zichtbaar = page.evaluate(
        """() => Array.from(document.querySelectorAll('.tab-content'))
                      .filter(el => !el.classList.contains('hidden'))
                      .map(el => el.id)"""
    )
    assert zichtbaar == ["inventory-tab"]
    # En de knopmarkering loopt mee, anders wijst de balk een ander tabblad aan
    # dan er open staat.
    actief = page.evaluate(
        """() => (document.querySelector('button.tab-btn.active')
                          .getAttribute('onclick') || '')"""
    )
    assert "showTab('inventory'" in actief
    assert page.js_errors == []


def test_onbruikbare_tabvoorkeur_valt_terug_op_het_dashboard(browser_page):
    """Een tabnaam uit een oudere versie mag de app niet blokkeren.

    `showTab()` doet `document.getElementById(name + '-tab').classList` zonder
    null-check. Zonder de `_VALID_TABS`-controle bij het herstellen gooit een
    voorkeur van een hernoemd/verwijderd tabblad daar een TypeError, midden in
    de opstartcode — de pagina blijft dan leeg achter. Dit toetst de terugval.
    """
    page = browser_page
    _wacht_tot_geladen(page)

    page.evaluate(
        """() => localStorage.setItem(
            'sop_ui_prefs_v1',
            JSON.stringify({ activeTab: 'tabblad-dat-niet-bestaat' }))"""
    )
    page.reload(wait_until="networkidle")
    _wacht_tot_geladen(page)

    expect(page.locator("#dashboard-tab")).to_be_visible(timeout=60000)
    assert page.evaluate("() => _activeTabName") == "dashboard"
    # De opstartcode is daadwerkelijk doorgelopen: de sessiebalk is gevuld.
    page.wait_for_function("() => !!(state && state.periods && state.periods.length)",
                           timeout=60000)
    assert page.js_errors == []


def test_busy_overlay_is_weg_na_het_laden_en_telt_geneste_taken(browser_page):
    """De wachtlaag ligt over de hele pagina; blijft hij hangen, dan is de app
    dood voor de gebruiker (klikken komen niet meer aan).

    Twee dingen moeten kloppen. (1) Na het laden is hij weg én laat hij muis-
    invoer door. (2) `setBusy` telt diepte: twee gelijktijdige taken en één
    afronding mag de laag NIET weghalen, anders verdwijnt de overlay al bij de
    eerste van twee lopende herberekeningen en klikt de gebruiker in een tabel
    die nog aan het verversen is.
    """
    page = browser_page
    _wacht_tot_geladen(page)

    overlay = page.locator("#busyOverlay")
    expect(overlay).to_have_class("hidden", timeout=60000)
    assert page.evaluate(
        "() => getComputedStyle(document.getElementById('busyOverlay')).pointerEvents"
    ) == "none"
    assert page.evaluate("() => isBusy()") is False
    assert page.evaluate("() => document.body.classList.contains('ui-busy')") is False

    # Twee taken starten: de laag komt op en blokkeert de pagina.
    assert page.evaluate(
        """() => {
            setBusy(true, 'Taak A');
            setBusy(true, 'Taak B');
            return isBusy();
        }"""
    ) is True
    expect(overlay).to_have_class("show", timeout=10000)
    assert page.locator("#busyOverlayText").inner_text().strip() == "Taak B"
    assert page.evaluate("() => document.body.classList.contains('ui-busy')") is True

    # Afronden: de tussenmeting moet synchroon, want het verbergen loopt via
    # een timer van 140 ms en mag niet van testtiming afhangen.
    meting = page.evaluate(
        """() => {
            const o = document.getElementById('busyOverlay');
            setBusy(false);
            const naEen = { verborgen: o.classList.contains('hidden'), busy: isBusy() };
            setBusy(false);
            const naNul = isBusy();
            // Een extra afronding mag de teller niet negatief maken.
            setBusy(false);
            return { naEen, naNul, naExtra: isBusy() };
        }"""
    )
    assert meting["naEen"] == {"verborgen": False, "busy": True}, \
        "de overlay verdween al terwijl er nog een taak liep"
    assert meting["naNul"] is False
    assert meting["naExtra"] is False, "_busyDepth zakte onder nul"

    page.wait_for_function(
        """() => {
            const o = document.getElementById('busyOverlay');
            const s = getComputedStyle(o);
            return o.classList.contains('hidden')
                && s.display === 'none' && s.pointerEvents === 'none';
        }""",
        timeout=10000,
    )
    assert page.evaluate("() => document.body.classList.contains('ui-busy')") is False
    # En de pagina is weer bedienbaar.
    _open_tab(page, "planning")
    assert page.js_errors == []


def test_notify_toont_een_melding_en_ruimt_die_zelf_op(browser_page):
    """Toastmeldingen zijn de enige terugkoppeling bij opslaan, resetten en
    fouten. Blijft er één staan, dan dekt hij de knoppenbalk af; verschijnt hij
    niet, dan lijkt een mislukte actie geslaagd.

    Getoetst: verschijnen met de juiste kleurklasse, het niveau wisselen zonder
    de oude kleur te behouden, en vanzelf weer verdwijnen na de opgegeven tijd.
    """
    page = browser_page
    _wacht_tot_geladen(page)

    melding = page.locator("#appNotice")
    assert "show" not in (melding.get_attribute("class") or "")

    page.evaluate("() => notify('Opslaan gelukt', 'success', 8000)")
    expect(melding).to_have_class(re.compile(r"\bshow\b"))
    expect(melding).to_have_class(re.compile(r"\bnotice-success\b"))
    expect(melding).to_have_text("Opslaan gelukt")
    page.wait_for_function(
        "() => getComputedStyle(document.getElementById('appNotice')).opacity === '1'",
        timeout=10000,
    )

    # Niveauwissel: de vorige kleur moet weg, anders krijgt een fout een groene
    # rand en leest de gebruiker hem als bevestiging.
    page.evaluate("() => notify('Er ging iets mis', 'error', 600)")
    expect(melding).to_have_class(re.compile(r"\bnotice-error\b"))
    assert "notice-success" not in (melding.get_attribute("class") or "")
    expect(melding).to_have_text("Er ging iets mis")

    # En hij ruimt zichzelf op na de meegegeven 600 ms — inclusief de
    # uitfade-overgang, zodat er echt niets meer over de knoppenbalk ligt.
    page.wait_for_function(
        """() => {
            const n = document.getElementById('appNotice');
            return !n.classList.contains('show')
                && getComputedStyle(n).opacity === '0';
        }""",
        timeout=10000,
    )
    assert page.js_errors == []


def test_log_tabblad_vult_zich_met_getimede_regels(browser_page):
    """Het Log-tabblad is bij een klant het enige spoor van wat de app deed.

    Elke regel hoort een tijdstempel te krijgen en de tekst hoort de ECHTE
    aantallen te noemen die geladen zijn — een log dat "0 consolidation rows"
    meldt terwijl de tabel vol staat is erger dan geen log. Daarom wordt hier
    een leesactie uitgevoerd en het getal in de logregel vergeleken met de
    werkelijke inhoud van `state`.
    """
    page = browser_page
    _wacht_tot_geladen(page)
    _open_tab(page, "log")

    logbak = page.locator("#log")
    lengte_voor = page.evaluate("() => document.getElementById('log').textContent.length")

    page.evaluate("() => loadValueResults()")
    page.wait_for_function(
        "() => /Value planning loaded/.test(document.getElementById('log').textContent)",
        timeout=120000,
    )

    tekst = logbak.inner_text()
    assert len(tekst) > lengte_voor, "het log groeide niet mee met de actie"

    treffer = re.search(
        r"\[(\d{1,2}:\d{2}:\d{2}[^\]]*)\]\s*Value planning loaded: (\d+) consolidation rows, (\d+) total rows",
        tekst,
    )
    assert treffer, f"geen getimede logregel gevonden in:\n{tekst[-800:]}"

    werkelijk = page.evaluate(
        """() => ({
            consolidation: (state.consolidation || []).length,
            totaal: Object.values(state.valueResults || {})
                          .reduce((s, rows) => s + rows.length, 0),
        })"""
    )
    assert werkelijk["consolidation"] > 0, "geen consolidatieregels geladen"
    assert werkelijk["totaal"] > 0, "geen waarderegels geladen"
    assert int(treffer.group(2)) == werkelijk["consolidation"]
    assert int(treffer.group(3)) == werkelijk["totaal"]
    assert page.js_errors == []


def test_mom_tabblad_toont_data_of_een_nette_melding(browser_page):
    """MoM hangt volledig aan `/api/mom`. Is er niets te vergelijken, dan moet
    er staan WAAROM — een leeg tabblad met verborgen KPI's en geen tekst laat
    de gebruiker denken dat de vergelijking nul verschil vond.

    Beide takken worden hier afgedwongen: bij `available` moeten KPI's, grafiek
    en detailtabel tevoorschijn komen en het bannergetal gelijk zijn aan het
    aantal materialen uit de API; anders moeten die blokken juist verborgen
    blijven en de servermelding letterlijk in de banner staan.
    """
    page = browser_page
    base_url = page.server["base_url"]
    payload = _mom_payload(base_url)

    _open_mom(page)
    banner = page.locator("#momBannerText").inner_text().strip()

    if not payload.get("available"):
        assert banner == (payload.get("message") or "Run calculations first.")
        assert banner, "lege melding terwijl er geen vergelijking is"
        for blok in ("momKpis", "momCharts", "momTableWrap"):
            assert page.locator(f"#{blok}").evaluate(
                "el => el.classList.contains('hidden')"
            ), f"#{blok} bleef zichtbaar zonder data"
        assert page.js_errors == []
        return

    expect(page.locator("#momKpis")).to_be_visible()
    expect(page.locator("#momCharts")).to_be_visible()
    expect(page.locator("#momTableWrap")).to_be_visible()
    page.wait_for_function(
        "() => document.querySelectorAll('#momBody tr').length > 0", timeout=60000)

    perioden = payload["periods"]
    assert len(perioden) == 2
    assert perioden[0] in banner and perioden[-1] in banner, banner
    assert str(payload["material_count"]) in banner, banner

    aantal = int(page.locator("#momKpiMaterials").inner_text().strip().replace(".", ""))
    assert aantal == payload["material_count"]
    assert aantal > 0, "MoM meldt beschikbaar maar telt nul materialen"

    # De scatter is een zelfgebouwde SVG; leeg betekent hier stil kapot.
    assert page.locator("#momScatterWrap svg").count() == 1
    assert page.locator("#momScatterWrap svg circle").count() > 0
    assert page.locator("#momTopMovers tbody tr").count() > 0
    assert page.js_errors == []


def test_mom_kpis_en_detailrijen_kloppen_met_de_api(browser_page):
    """De MoM-cijfers worden in de browser herrekend uit de API-payload. Die
    hertelling is stille rekenlogica: 'voorraad omhoog' is `delta > 0.5`,
    'omlaag' `delta < -0.5`, en het gemiddelde loopt alleen over eindige
    delta-percentages. Een tekenfout of een NaN die meegemiddeld wordt levert
    een KPI op die er plausibel uitziet maar niet klopt.

    Ook de detailtabel wordt getoetst: elke rij moet `delta = to - from`
    aanhouden, en de rode/groene rijmarkering moet exact de rijen boven/onder
    de drempel raken.
    """
    page = browser_page
    base_url = page.server["base_url"]
    payload = _mom_payload(base_url)
    if not payload.get("available"):
        pytest.skip("Geen MoM-vergelijking beschikbaar op deze fixture")

    _open_mom(page)
    page.wait_for_function(
        "() => document.querySelectorAll('#momBody tr').length > 0", timeout=60000)

    summary = payload["summary"]
    omhoog = len([s for s in summary if s["delta"] > 0.5])
    omlaag = len([s for s in summary if s["delta"] < -0.5])
    pcts = [
        s["delta_pct"] for s in summary
        if s["delta_pct"] is not None and s["delta_pct"] == s["delta_pct"]
        and abs(s["delta_pct"]) != float("inf")
    ]
    gemiddelde = sum(pcts) / len(pcts) if pcts else 0.0

    assert int(page.locator("#momKpiUp").inner_text().strip()) == omhoog
    assert int(page.locator("#momKpiDown").inner_text().strip()) == omlaag
    getoond = float(
        page.locator("#momKpiAvgDelta").inner_text().strip().rstrip("%").replace(",", ".")
    )
    assert getoond == pytest.approx(gemiddelde, abs=0.06), (
        f"gemiddelde delta% getoond {getoond}, berekend {gemiddelde}"
    )
    assert omhoog + omlaag <= payload["material_count"]

    verwachte_rijen = sum(len(t["rows"]) for t in payload["transitions"])
    assert verwachte_rijen > 0
    assert page.locator("#momBody tr").count() == verwachte_rijen, \
        "de detailtabel liet rijen vallen bij het renderen"

    controle = page.evaluate(
        """() => {
            const fout = _momData.filter(
                r => Math.abs((r.to_inventory - r.from_inventory) - r.delta) > 0.011);
            const rijen = Array.from(document.querySelectorAll('#momBody tr'));
            const rood  = rijen.filter(tr => /255,\\s*199/.test(tr.getAttribute('style') || '')).length;
            const groen = rijen.filter(tr => /198,\\s*239/.test(tr.getAttribute('style') || '')).length;
            return {
                aantal: _momData.length,
                fout: fout.length,
                rood, groen,
                boven: _momData.filter(r => (r.delta || 0) > 0.5).length,
                onder: _momData.filter(r => (r.delta || 0) < -0.5).length,
            };
        }"""
    )
    assert controle["aantal"] == verwachte_rijen
    assert controle["fout"] == 0, "delta wijkt af van (to - from) in de detailtabel"
    assert controle["rood"] == controle["boven"]
    assert controle["groen"] == controle["onder"]
    assert controle["rood"] + controle["groen"] > 0, \
        "geen enkele rij gemarkeerd; de kleurregel doet niets"
    assert page.js_errors == []


def test_mom_aantal_maanden_stuurt_de_vergelijkingsperiode(browser_page):
    """"Compare start to month" kiest de doelperiode van de vergelijking.

    Wordt dat veld genegeerd, dan blijft het tabblad de standaard zesde maand
    tonen terwijl de gebruiker denkt naar maand 3 te kijken — een verkeerde
    voorraadconclusie zonder enige zichtbare aanwijzing. Getoetst tegen de
    API-uitkomst voor hetzelfde aantal maanden, niet tegen de invoer zelf.
    """
    page = browser_page
    base_url = page.server["base_url"]
    zes = _mom_payload(base_url, 6)
    drie = _mom_payload(base_url, 3)
    if not (zes.get("available") and drie.get("available")):
        pytest.skip("Geen MoM-vergelijking beschikbaar op deze fixture")
    if zes["periods"][-1] == drie["periods"][-1]:
        pytest.skip("Horizon te kort: maand 3 en 6 vallen samen")

    _open_mom(page)
    doel_zes = page.evaluate("() => _momData[0].to_period")
    assert doel_zes == zes["periods"][-1]

    page.fill("#momNumMonths", "3")
    page.locator("#mom-tab button", has_text="Refresh MoM").click()
    # `_momData` staat in modulescope, niet op `window` — bare referentie dus.
    page.wait_for_function(
        "(p) => _momData && _momData.length && _momData[0].to_period === p",
        arg=drie["periods"][-1],
        timeout=120000,
    )

    assert drie["periods"][-1] in page.locator("#momBannerText").inner_text()
    assert page.locator("#momScatterSubtitle").inner_text().strip() == \
        f"{drie['periods'][0]} vs {drie['periods'][-1]}"

    # De cijfers lopen echt mee: de KPI-tellingen volgen de nieuwe doelmaand.
    omhoog = len([s for s in drie["summary"] if s["delta"] > 0.5])
    assert int(page.locator("#momKpiUp").inner_text().strip()) == omhoog

    # Elke rij draagt de nieuwe doelperiode, niet een mengsel van beide runs.
    perioden_in_tabel = page.evaluate(
        "() => Array.from(new Set(_momData.map(r => r.to_period)))")
    assert perioden_in_tabel == [drie["periods"][-1]]
    assert page.js_errors == []
