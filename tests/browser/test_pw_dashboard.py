"""Dashboard-tab — browsertests.

Het dashboard is het enige scherm waar de uitkomsten van alle engines
(vraag, voorraad, capaciteit, FTE en de waardeconsolidatie) naast elkaar
staan. Precies daarom is het ook het scherm dat het stilst kapot gaat: een
tegel die "-" of "NaN" toont, een grafiek die op de vorige sessie blijft
hangen of een dirty-vlag die niet doorschakelt levert geen foutmelding op,
maar wel een klant die naar verkeerde cijfers kijkt.

Deze tests pinnen daarom vast:
  * de vijf KPI-tegels vullen zich en tonen exact wat /api/dashboard zegt;
  * de grafieken bevatten dezelfde reeksen als de API en echte pixels;
  * de "General Projected Overview"-tabel rekent de VBA-sommen/gemiddelden;
  * state.dashboardDirty stelt het hertekenen uit tot de tab zichtbaar is,
    en voorkomt daarna een nodeloze tweede fetch;
  * na een sessiewissel en na een herberekening (celedit) tekent het
    dashboard opnieuw met de cijfers van de NIEUWE toestand;
  * lege of ontbrekende data geeft placeholders, geen JS-fout.
"""

import json
import re

import pytest
import requests
from playwright.sync_api import expect

from tests.browser.test_charts import _assert_canvas_has_real_pixels
from tests.browser.test_edits import (
    _drain_edits,
    _edit_first_demand_cell_to,
    _prepare_clean_planning_page,
)


pytestmark = pytest.mark.browser


# Selector-inventaris (ui/templates/index.html):
# - button.tab-btn[onclick*="showTab('dashboard'"] : dashboardtabknop (regel 833)
# - #dashboard-tab                                  : tabpaneel (regel 845)
# - #kpi-mat/#kpi-util/#kpi-fte/#kpi-overstock/#kpi-demand : KPI-tegels
#   (regels 850-870), gevuld door renderKPIs() (regel 3843)
# - #kpiOverviewTable    : General Projected Overview (renderKPIOverviewTable)
# - .kpi-m-btn[data-m]   : 3M/6M/9M/12M-horizonknoppen (_kpiOverviewMonths)
# - #financialChart, #utilChart, #fteChart, #demandTrendChart, #roceChart,
#   #invTargetChart : Chart.js-canvassen die renderDashboard() (re)tekent
# - #invHeatmapWrap      : voorraadkwaliteit-heatmap, laatste DOM-stap van
#   renderInventoryHeatmap(); handig als bewijs dat de renderketen doorliep

KPI_IDS = ("kpi-mat", "kpi-util", "kpi-fte", "kpi-overstock", "kpi-demand")
PLACEHOLDERS = {"", "-", "—", "NaN", "NaN%", "undefined", "null"}
DASHBOARD_ROUTE = "**/api/dashboard"


# ---------------------------------------------------------------- helpers ---

def _dashboard_api(base_url: str) -> dict:
    """De serverwaarheid: los van de browser opgehaald."""
    response = requests.get(base_url + "/api/dashboard", timeout=180)
    response.raise_for_status()
    return response.json()


def _open_dashboard(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.locator("button.tab-btn[onclick*=\"showTab('dashboard'\"]").click()
    expect(page.locator("#dashboard-tab")).to_be_visible()
    page.wait_for_function(
        """() => window._dashboardData
                && Array.isArray(window._dashboardData.periods)
                && window._dashboardData.periods.length > 0""",
        timeout=120000,
    )


def _kpi_text(page, element_id: str) -> str:
    """textContent i.p.v. inner_text: de tegels moeten ook kloppen terwijl een
    andere tab zichtbaar is (na een edit hertekent het dashboard meteen)."""
    return page.evaluate(
        "(id) => (document.getElementById(id).textContent || '').trim()", element_id
    )


def _num(text: str) -> float:
    """toFixed-tekst ('45.3%', '12.7') → float."""
    cleaned = text.strip().replace(" ", "").replace("\xa0", "").replace(",", "")
    return float(cleaned.rstrip("%"))


def _int_text(text: str) -> int:
    """toLocaleString-tekst ('1,234,567' of '1.234.567') → int. Locale-vrij:
    maximumFractionDigits is 0, dus alleen cijfers en teken tellen."""
    digits = re.sub(r"[^\d-]", "", text)
    assert digits not in ("", "-"), f"geen getal in {text!r}"
    return int(digits)


def _fmtval(text: str):
    """fmtVal-tekst ('1.2M', '345.6K', '12') → (waarde, weergavetolerantie)."""
    stripped = text.strip().replace(" ", "").replace("\xa0", "")
    match = re.fullmatch(r"(-?)(\d+(?:\.\d+)?)([KM]?)", stripped)
    assert match, f"onverwachte fmtVal-tekst: {text!r}"
    sign = -1.0 if match.group(1) else 1.0
    value = float(match.group(2))
    suffix = match.group(3)
    if suffix == "M":
        return sign * value * 1e6, 0.05e6
    if suffix == "K":
        return sign * value * 1e3, 0.05e3
    return sign * value, (0.005 if value < 10 else 0.5)


def _eur(text: str) -> float:
    """'€ 1.234.567' (nl-NL, incl. smalle spatie) → float."""
    digits = re.sub(r"[^\d-]", "", text)
    assert digits not in ("", "-"), f"geen bedrag in {text!r}"
    return float(digits)


def _kpi_overview(page) -> dict:
    return page.evaluate(
        """() => {
            const header = [...document.querySelectorAll('#kpiOverviewTable thead th')]
                .map(th => th.textContent.trim()).slice(1);
            const rows = {};
            document.querySelectorAll('#kpiOverviewTable tbody tr').forEach(tr => {
                const cells = [...tr.children].map(td => td.textContent.trim());
                rows[cells[0]] = cells.slice(1);
            });
            return { header, rows };
        }"""
    )


def _install_dashboard_fetch_counter(page):
    """Telt /api/dashboard-fetches in de pagina zelf: deterministischer dan
    het afwachten van netwerk-events aan de Python-kant."""
    page.evaluate(
        """() => {
            if (window.__dashCountInstalled) { window.__dashFetches = 0; return; }
            window.__dashCountInstalled = true;
            window.__dashFetches = 0;
            const orig = window.fetch;
            window.fetch = function (...args) {
                const first = args[0];
                const url = typeof first === 'string' ? first : ((first && first.url) || '');
                if (String(url).includes('/api/dashboard')) window.__dashFetches++;
                return orig.apply(this, args);
            };
        }"""
    )


def _dash_fetches(page) -> int:
    return page.evaluate("() => window.__dashFetches")


def _switch_session_api(base_url: str, session_id: str) -> None:
    response = requests.post(
        base_url + "/api/sessions/switch", json={"session_id": session_id}, timeout=300
    )
    response.raise_for_status()
    assert response.json().get("success"), response.text


def _upload_and_calculate_session(base_url, fixture_path, name, planning_month) -> str:
    with fixture_path.open("rb") as workbook:
        upload = requests.post(
            base_url + "/api/upload",
            files={"file": (fixture_path.name, workbook)},
            data={
                "custom_name": name,
                "planning_month": planning_month,
                "months_actuals": "11",
                "months_forecast": "12",
            },
            timeout=300,
        )
    upload.raise_for_status()
    payload = upload.json()
    assert payload.get("success"), f"Upload mislukt: {payload}"

    calculate = requests.post(
        base_url + "/api/calculate",
        json={
            "planning_month": planning_month,
            "months_actuals": 11,
            "months_forecast": 12,
        },
        timeout=600,
    )
    calculate.raise_for_status()
    calc_payload = calculate.json()
    assert calc_payload.get("success"), f"Berekening mislukt: {calc_payload}"
    return payload["session_id"]


# ------------------------------------------------------------------ tests ---

def test_dashboard_opens_with_filled_kpis(browser_page):
    """De vijf KPI-tegels moeten na het openen echte getallen tonen.

    Valt renderKPIs() of de /api/dashboard-payload weg, dan blijven de tegels
    op hun markup-placeholder "-" staan of tonen ze NaN — zichtbaar noch
    hard falend. Deze test maakt dat wel hard.
    """
    page = browser_page
    _open_dashboard(page)

    texts = {kpi_id: _kpi_text(page, kpi_id) for kpi_id in KPI_IDS}
    for kpi_id, text in texts.items():
        assert text not in PLACEHOLDERS, f"{kpi_id} bleef leeg/placeholder: {text!r}"
        assert "NaN" not in text and "undefined" not in text, f"{kpi_id}: {text!r}"

    assert int(texts["kpi-mat"].replace(",", "")) > 0
    assert texts["kpi-util"].endswith("%")
    assert _num(texts["kpi-util"]) > 0
    assert _num(texts["kpi-fte"]) > 0
    assert _int_text(texts["kpi-demand"]) > 0
    overstock, _ = _fmtval(texts["kpi-overstock"])
    assert overstock >= 0

    # De doorgerekende horizon staat ook echt in de payload van het dashboard.
    assert page.evaluate("() => window._dashboardData.periods") == page.server[
        "expected_periods"
    ]
    assert page.js_errors == []


def test_kpi_tiles_match_api_dashboard(browser_page):
    """Elke tegel moet hetzelfde getal tonen als /api/dashboard teruggeeft.

    De tegels zijn samengesteld (FTE = laatste periode, vraag = som over alle
    perioden). Een verschuiving in die afleiding — of een tegel die op oude
    data blijft staan — is alleen zichtbaar door tegen de serverwaarheid te
    vergelijken, niet door "het staat er".
    """
    page = browser_page
    base_url = page.server["base_url"]
    api = _dashboard_api(base_url)
    kpis = api["kpis"]
    _open_dashboard(page)

    assert _kpi_text(page, "kpi-mat") == str(kpis["materials"])
    assert _num(_kpi_text(page, "kpi-util")) == pytest.approx(
        kpis["avg_utilization"], abs=0.05
    )
    assert _num(_kpi_text(page, "kpi-fte")) == pytest.approx(
        kpis["total_fte"], abs=0.05
    )
    overstock, tolerance = _fmtval(_kpi_text(page, "kpi-overstock"))
    assert overstock == pytest.approx(kpis["total_overstock"], abs=tolerance)

    expected_demand = sum(api["demand_trend"].values())
    assert _int_text(_kpi_text(page, "kpi-demand")) == pytest.approx(
        expected_demand, abs=1.0
    )
    assert page.js_errors == []


def test_dashboard_charts_carry_the_api_series(browser_page):
    """De grafieken moeten dezelfde reeksen tekenen als de API levert.

    "Graphs disagree with the table" is een bekende faalmodus: de tegels
    worden ververst maar een grafiek blijft op oude data staan, of de
    schaling (K/1000) sluipt weg. Daarom labels én datapunten vergelijken,
    plus een pixelcontrole zodat een leeg canvas niet als groen telt.
    """
    page = browser_page
    api = _dashboard_api(page.server["base_url"])
    periods = api["periods"]
    _open_dashboard(page)

    page.wait_for_function(
        """() => window.Chart && ['financialChart', 'utilChart', 'fteChart',
                'demandTrendChart', 'roceChart']
            .every(id => !!Chart.getChart(document.getElementById(id)))""",
        timeout=120000,
    )
    charts = page.evaluate(
        """() => {
            const grab = id => {
                const chart = Chart.getChart(document.getElementById(id));
                return {
                    labels: chart.data.labels,
                    datasets: chart.data.datasets.map(d => ({ label: d.label, data: d.data })),
                };
            };
            return {
                fin: grab('financialChart'),
                util: grab('utilChart'),
                fte: grab('fteChart'),
                trend: grab('demandTrendChart'),
            };
        }"""
    )

    # Vraagtrend: labels = perioden, punten = demand_trend.
    assert charts["trend"]["labels"] == periods
    assert charts["trend"]["datasets"][0]["data"] == pytest.approx(
        [api["demand_trend"][p] for p in periods], rel=1e-9
    )

    # Financiële grafiek: 'Starting stock' voorop, bedragen in duizenden.
    assert charts["fin"]["labels"] == ["Starting stock"] + periods
    turnover = next(d for d in charts["fin"]["datasets"] if d["label"] == "Turnover")
    for label, drawn in zip(charts["fin"]["labels"], turnover["data"]):
        raw = api["financials"]["TURNOVER"].get(label)
        if raw is None:
            assert drawn is None, f"{label}: onverwacht datapunt {drawn}"
        else:
            assert drawn == pytest.approx(raw / 1000.0, rel=1e-9)

    # Bezetting en FTE: één reeks per machine respectievelijk groep.
    assert len(charts["util"]["datasets"]) == len(api["utilization_by_machine"])
    first_machine = api["utilization_by_machine"][0]
    assert charts["util"]["datasets"][0]["data"] == pytest.approx(
        [first_machine["values"].get(p, 0) or 0 for p in periods], rel=1e-9
    )
    assert len(charts["fte"]["datasets"]) == len(api["fte_by_group"])
    first_group = api["fte_by_group"][0]
    assert charts["fte"]["datasets"][0]["data"] == pytest.approx(
        [first_group["values"].get(p, 0) or 0 for p in periods], rel=1e-9
    )

    for selector in ("#financialChart", "#demandTrendChart", "#utilChart"):
        _assert_canvas_has_real_pixels(page, selector)
    assert page.js_errors == []


def test_kpi_overview_table_reproduces_vba_aggregation(browser_page):
    """De overzichtstabel moet de VBA-aggregatie tonen, niet zomaar een som.

    Resultaatregels tellen op, balansregels middelen (voorraad inclusief
    beginvoorraad) en ROCE is EBIT-som gedeeld door gemiddeld geïnvesteerd
    kapitaal — géén gemiddelde van maand-ROCE's. Wie dat verwisselt krijgt
    getallen die er plausibel uitzien en toch fout zijn.
    """
    page = browser_page
    api = _dashboard_api(page.server["base_url"])
    financials = api["financials"]
    periods = api["periods"]
    _open_dashboard(page)
    page.wait_for_function(
        "() => document.querySelectorAll('#kpiOverviewTable tbody tr').length > 0",
        timeout=60000,
    )

    overview = _kpi_overview(page)
    assert overview["header"] == ["12M"], overview["header"]

    horizon = periods[:12]
    expected_turnover = sum(financials["TURNOVER"].get(p, 0) for p in horizon)
    assert _eur(overview["rows"]["Turnover"][0]) == pytest.approx(
        expected_turnover, abs=1.0
    )

    # Balansregel: gemiddelde inclusief beginvoorraad.
    inventory_points = ["Starting stock"] + horizon
    expected_inventory = sum(
        financials["INVENTORY VALUE"].get(p, 0) for p in inventory_points
    ) / len(inventory_points)
    assert _eur(overview["rows"]["Inventory Value"][0]) == pytest.approx(
        expected_inventory, abs=1.0
    )

    # ROCE: EBIT-som / gemiddeld kapitaal.
    ebit_sum = sum(financials["EBIT"].get(p, 0) for p in horizon)
    capital_avg = sum(
        financials["CAPITAL INVESTMENT"].get(p, 0) for p in horizon
    ) / len(horizon)
    expected_roce = 100.0 * ebit_sum / capital_avg
    shown_roce = float(overview["rows"]["ROCE"][0].rstrip("%"))
    assert shown_roce == pytest.approx(expected_roce, abs=0.02)

    # 3M erbij: extra kolom die over de eerste drie perioden sommeert.
    page.locator("#dashboard-tab .kpi-m-btn[data-m='3']").click()
    page.wait_for_function(
        """() => [...document.querySelectorAll('#kpiOverviewTable thead th')]
            .some(th => th.textContent.trim() === '3M')""",
        timeout=30000,
    )
    overview = _kpi_overview(page)
    assert overview["header"] == ["3M", "12M"], overview["header"]
    expected_3m = sum(financials["TURNOVER"].get(p, 0) for p in periods[:3])
    assert _eur(overview["rows"]["Turnover"][0]) == pytest.approx(expected_3m, abs=1.0)
    assert _eur(overview["rows"]["Turnover"][1]) == pytest.approx(
        expected_turnover, abs=1.0
    )
    assert page.js_errors == []


def test_dashboard_dirty_flag_defers_render_until_tab_opens(browser_page):
    """state.dashboardDirty moet het hertekenen uitstellen én ontdubbelen.

    Zonder de vlag haalt elke tabwissel /api/dashboard opnieuw op (traag, en
    het zwaarste endpoint van de app); mét een vlag die blijft hangen ziet de
    gebruiker na een herberekening nog de oude cijfers. Beide kanten worden
    hier vastgelegd: uitgesteld terwijl de tab verborgen is, precies één keer
    opgehaald bij het openen, en daarna niet nog eens.
    """
    page = browser_page
    _open_dashboard(page)
    _install_dashboard_fetch_counter(page)

    page.evaluate("() => showTab('planning')")
    expect(page.locator("#planning-tab")).to_be_visible()
    before = _dash_fetches(page)

    # Vraag om een dashboard-render terwijl de tab verborgen is: uitstellen.
    page.evaluate("() => _renderDashboardOrDefer()")
    assert page.evaluate("() => state.dashboardDirty") is True, \
        "verborgen dashboard werd niet als 'dirty' gemarkeerd"
    assert _dash_fetches(page) == before, \
        "dashboard werd opgehaald terwijl de tab niet zichtbaar was"

    # Tab openen: nu wél ophalen, en de vlag valt terug.
    with page.expect_request(
        lambda request: "/api/dashboard" in request.url, timeout=60000
    ):
        page.locator("button.tab-btn[onclick*=\"showTab('dashboard'\"]").click()
    page.wait_for_function("() => state.dashboardDirty === false", timeout=60000)
    after_open = _dash_fetches(page)
    assert after_open == before + 1, f"verwachtte één fetch, kreeg {after_open - before}"
    assert _kpi_text(page, "kpi-demand") not in PLACEHOLDERS

    # Niet-dirty tabwissel: geen tweede fetch. De extra round-trip hieronder is
    # de barrière — een render zou zijn fetch al hebben uitgestuurd.
    page.evaluate("() => showTab('planning')")
    page.evaluate("() => showTab('dashboard')")
    page.evaluate("() => fetch('/api/sessions').then(() => true)")
    assert _dash_fetches(page) == after_open, \
        "schone dashboardtab werd nodeloos opnieuw opgehaald"
    assert page.js_errors == []


def test_dashboard_follows_a_demand_edit(browser_page):
    """Na een celedit moet het dashboard de herberekende vraag tonen.

    Dit is de faalmodus "graphs disagree with the table": de planningstabel
    verwerkt de cascade wel, maar de dashboardtegel/-grafiek blijft op de
    cijfers van vóór de edit staan. De tegel moet mee bewegen én gelijk zijn
    aan wat de server na de cascade rapporteert.
    """
    page = browser_page
    base_url = page.server["base_url"]
    _drain_edits(base_url)
    try:
        _prepare_clean_planning_page(page, base_url)

        page.evaluate("() => showTab('dashboard')")
        _open_dashboard(page)
        before_api = _dashboard_api(base_url)
        before_demand = sum(before_api["demand_trend"].values())
        before_text = _kpi_text(page, "kpi-demand")
        assert _int_text(before_text) == pytest.approx(before_demand, abs=1.0)
        before_trend = page.evaluate(
            "() => Chart.getChart(document.getElementById('demandTrendChart')).data.datasets[0].data.slice()"
        )

        page.evaluate("() => showTab('planning')")
        expect(page.locator("#planning-tab")).to_be_visible()
        _edit_first_demand_cell_to(page, "999")

        # De edit-cascade hertekent het dashboard meteen (dashboardDirty).
        page.wait_for_function(
            "(old) => (document.getElementById('kpi-demand').textContent || '').trim() !== old",
            arg=before_text,
            timeout=120000,
        )
        after_api = _dashboard_api(base_url)
        after_demand = sum(after_api["demand_trend"].values())
        assert after_demand > before_demand, "edit verhoogde de totale vraag niet"
        assert _int_text(_kpi_text(page, "kpi-demand")) == pytest.approx(
            after_demand, abs=1.0
        )

        page.evaluate("() => showTab('dashboard')")
        expect(page.locator("#dashboard-tab")).to_be_visible()
        after_trend = page.evaluate(
            "() => Chart.getChart(document.getElementById('demandTrendChart')).data.datasets[0].data.slice()"
        )
        assert after_trend != before_trend, "vraagtrendgrafiek bleef op oude data staan"
        assert after_trend == pytest.approx(
            [after_api["demand_trend"][p] for p in after_api["periods"]], rel=1e-9
        )
        assert page.js_errors == []
    finally:
        _drain_edits(base_url)


def test_dashboard_redraws_after_session_switch(browser_page, golden_fixture_path):
    """Een sessiewissel moet het dashboard opnieuw opbouwen.

    "Switching instances shows wrong values" is de klassieke bug: de nieuwe
    sessie is actief, maar tegels en grafieken tonen nog de horizon en de
    cijfers van de vorige instantie. De tweede sessie heeft hier een andere
    planningsmaand, dus de perioden zijn bewijsbaar anders — blijven ze
    staan, dan is er niet hertekend.
    """
    page = browser_page
    base_url = page.server["base_url"]
    session_a = page.server["session_id"]
    session_b = None
    try:
        session_b = _upload_and_calculate_session(
            base_url, golden_fixture_path, "Dashboard wissel test", "2026-01"
        )
        _switch_session_api(base_url, session_a)
        page.reload(wait_until="networkidle")
        _open_dashboard(page)

        api_a = _dashboard_api(base_url)
        periods_a = page.evaluate("() => window._dashboardData.periods")
        assert periods_a == api_a["periods"]
        demand_a = _int_text(_kpi_text(page, "kpi-demand"))
        assert demand_a == pytest.approx(sum(api_a["demand_trend"].values()), abs=1.0)

        # A → B, met de dashboardtab zichtbaar: direct hertekenen.
        page.evaluate("(sid) => switchSession(sid)", session_b)
        page.wait_for_function(
            "(sid) => state.activeSessionId === sid", arg=session_b, timeout=600000
        )
        page.wait_for_function(
            """(old) => window._dashboardData
                && JSON.stringify(window._dashboardData.periods) !== JSON.stringify(old)""",
            arg=periods_a,
            timeout=600000,
        )
        api_b = _dashboard_api(base_url)
        assert api_b["periods"] != periods_a, "tweede sessie kreeg dezelfde horizon"
        assert page.evaluate("() => window._dashboardData.periods") == api_b["periods"]
        assert _int_text(_kpi_text(page, "kpi-demand")) == pytest.approx(
            sum(api_b["demand_trend"].values()), abs=1.0
        )
        assert page.evaluate(
            "() => Chart.getChart(document.getElementById('demandTrendChart')).data.labels"
        ) == api_b["periods"], "vraagtrendgrafiek hield de labels van sessie A"

        # En terug: het dashboard hoort weer sessie A te tonen.
        page.evaluate("(sid) => switchSession(sid)", session_a)
        page.wait_for_function(
            "(sid) => state.activeSessionId === sid", arg=session_a, timeout=600000
        )
        page.wait_for_function(
            """(old) => window._dashboardData
                && JSON.stringify(window._dashboardData.periods) === JSON.stringify(old)""",
            arg=periods_a,
            timeout=600000,
        )
        assert _int_text(_kpi_text(page, "kpi-demand")) == demand_a
        assert page.js_errors == []
    finally:
        try:
            _switch_session_api(base_url, session_a)
        except (requests.RequestException, AssertionError):
            pass
        if session_b:
            requests.delete(base_url + f"/api/sessions/{session_b}", timeout=120)


def test_dashboard_survives_empty_and_missing_data(browser_page):
    """Lege of ontbrekende dashboarddata mag geen JS-fout geven.

    Een sessie zonder berekening, een mislukte InventoryQualityEngine of een
    lege groepsselectie leveren payloads zonder reeksen. Loopt renderDashboard
    dan halverwege stuk, dan blijven de tegels op de cijfers van de VORIGE
    sessie staan — misleidender dan een leeg scherm. Daarom wordt hier ook
    gecontroleerd dat de renderketen tot de laatste stap doorloopt en dat de
    tegels expliciete placeholders tonen in plaats van NaN.
    """
    page = browser_page
    _open_dashboard(page)
    filled_demand = _kpi_text(page, "kpi-demand")

    def _serve(payload):
        handler = lambda route: route.fulfill(  # noqa: E731
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        )
        page.route(DASHBOARD_ROUTE, handler)
        page.evaluate("() => renderDashboard()")
        page.unroute(DASHBOARD_ROUTE, handler)

    # 1. Payload zonder ook maar één sleutel.
    _serve({})
    assert "unavailable" in page.evaluate(
        "() => document.getElementById('invHeatmapWrap').textContent"
    ), "renderketen liep vast vóór de heatmap"
    assert page.evaluate("() => window._invTargetChart.data.labels.length") == 0, \
        "laatste rendercall (voorraad vs. target) is niet uitgevoerd"
    assert page.evaluate(
        "() => Chart.getChart(document.getElementById('financialChart')) || null"
    ) is None, "financiële grafiek hield de oude reeksen vast"

    # 2. Lege containers: tegels tonen placeholders, geen NaN.
    _serve({
        "periods": [],
        "kpis": {},
        "utilization_by_machine": [],
        "fte_by_group": [],
        "financials": {},
        "inventory_quality": [],
        "top_10_overstocks": [],
        "demand_trend": {},
        "inventory_trend": {},
        "target_trend": {},
    })
    texts = {kpi_id: _kpi_text(page, kpi_id) for kpi_id in KPI_IDS}
    assert texts["kpi-mat"] == "-"
    assert texts["kpi-util"] == "-"
    assert texts["kpi-fte"] == "-"
    assert texts["kpi-overstock"] == "-"
    assert texts["kpi-demand"] == "0"
    assert all("NaN" not in text for text in texts.values()), texts

    # 3. Foutpayload (sessie zonder berekening): netjes afbreken.
    _serve({"error": "No calculations run"})
    assert page.evaluate("() => window._dashboardData.error") == "No calculations run"
    assert all(
        "NaN" not in _kpi_text(page, kpi_id) for kpi_id in KPI_IDS
    ), "foutpayload liet NaN achter in de tegels"

    # 4. Herstel: echte data komt ongeschonden terug.
    page.evaluate("() => renderDashboard()")
    page.wait_for_function(
        """(expected) => (document.getElementById('kpi-demand').textContent || '').trim()
            === expected""",
        arg=filled_demand,
        timeout=60000,
    )
    assert page.js_errors == []
