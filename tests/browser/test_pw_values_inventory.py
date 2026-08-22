"""VALUES PLANNING en INVENTORY — browsertests op een live server.

Beide tabbladen zijn puur presentatie bovenop een API-antwoord: er zit geen
tweede rekenlaag tussen. Precies daarom is een fout hier stil. Als de
values-tabel rijen laat vallen, als een KPI-tegel een som toont waar een
gemiddelde hoort, of als de inventarisstatus anders wordt ingedeeld dan de
server hem berekende, ziet de klant een verkeerd getal zonder foutmelding.
Deze tests vergelijken dus wat er in de DOM staat met wat
`/api/value_results`, `/api/inventory` en `/api/results` teruggeven, en
controleren dat een aux-bewerking helemaal doorwerkt tot in de consolidatie.
"""

import re

import pytest
import requests
from playwright.sync_api import expect


pytestmark = pytest.mark.browser


VALUES_TAB_BTN = "button.tab-btn[onclick*=\"showTab('values'\"]"
INVENTORY_TAB_BTN = "button.tab-btn[onclick*=\"showTab('inventory'\"]"

# Labels zoals renderConsolidation() ze tekent, gekoppeld aan het
# material_number waaronder de rij in /api/value_results staat.
CONSOL_LABEL_BY_MATERIAL = {
    "ZZZZZZ_TURNOVER": "Turnover",
    "ZZZZZZ_RAW MATERIAL COST": "Raw Material Cost",
    "ZZZZZZ_MACHINE COST": "Machine Cost",
    "ZZZZZZ_DIRECT FTE COST": "Direct FTE Cost",
    "ZZZZZZ_INDIRECT FTE COST": "Indirect FTE Cost",
    "ZZZZZZ_OVERHEAD COST": "Overhead Cost",
    "ZZZZZZ_COST OF GOODS": "Cost of Goods",
    "ZZZZZZ_GROSS MARGIN": "Gross Margin",
    "ZZZZZZ_SG&A COST": "SG&A Cost",
    "ZZZZZZ_EBITDA": "EBITDA",
    "ZZZZZZ_D&A COST": "D&A Cost",
    "ZZZZZZ_EBIT": "EBIT",
    "ZZZZZZ_FIXED ASSETS NET BOOK VALUE": "Fixed Assets NBV",
    "ZZZZZZ_INVENTORY VALUE": "Inventory Value",
    "ZZZZZZ_RECEIVABLES": "Receivables",
    "ZZZZZZ_PAYABLES": "Payables",
    "ZZZZZZ_WORKING CAPITAL REQUIREMENTS": "Working Capital Req.",
    "ZZZZZZ_CAPITAL INVESTMENT": "Capital Investment",
    "ZZZZZZ_OPERATIONAL CASHFLOW": "Operational Cashflow",
    "ZZZZZZ_ROCE": "ROCE",
}

# Line types waarvoor de UI de Aux-kolom bewerkbaar maakt (VALUE_AUX_EDITABLE).
VALUE_AUX_EDITABLE = (
    "01. Demand forecast",
    "03. Total demand",
    "04. Inventory",
    "06. Purchase receipt",
    "07. Capacity utilization",
    "12. FTE requirements",
)


# --------------------------------------------------------------------------
# Hulpjes
# --------------------------------------------------------------------------

def _parse_compact(text):
    """Ontleed een fmt()/fmtVal()-weergave ("1.2K", "-3.4M", "12", "5.1%").

    Geeft (waarde, eenheid) terug; de eenheid is de schaal waarop is afgerond
    en bepaalt dus de toegestane afwijking.
    """
    t = (text or "").strip().replace("%", "").replace("−", "-")
    unit = 1.0
    if t.endswith("M"):
        unit, t = 1e6, t[:-1]
    elif t.endswith("K"):
        unit, t = 1e3, t[:-1]
    return float(t) * unit, unit


def _assert_compact_equals(text, expected, what):
    """Vergelijk een afgeronde weergave met de exacte waarde uit de API."""
    actual, unit = _parse_compact(text)
    # fmt/fmtVal ronden op één decimaal binnen de schaal (of op hele eenheden
    # onder 1000); 0.51 * schaal dekt die afronding en niets meer.
    tolerance = max(0.51 * unit, 1e-6 * abs(expected))
    assert abs(actual - expected) <= tolerance, (
        f"{what}: scherm toont {text!r} (= {actual}), API zegt {expected}"
    )


def _open_values(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.locator(VALUES_TAB_BTN).click()
    expect(page.locator("#values-tab")).to_be_visible()
    page.wait_for_selector("#vpBody tr[data-material]", timeout=60000)


def _open_inventory(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    with page.expect_response(
        lambda r: r.url.endswith("/api/inventory") and r.ok, timeout=120000
    ):
        page.locator(INVENTORY_TAB_BTN).click()
    expect(page.locator("#inventory-tab")).to_be_visible()
    page.wait_for_function(
        "() => document.querySelectorAll('#invBody tr td:nth-child(3)').length > 0",
        timeout=60000,
    )


def _value_results(base_url):
    response = requests.get(base_url + "/api/value_results", timeout=180)
    response.raise_for_status()
    payload = response.json()
    assert "error" not in payload, payload
    return payload


def _consolidation_by_material(payload):
    return {row["material_number"]: row["values"] for row in payload["consolidation"]}


def _read_consolidation_table(page):
    """Lees het gerenderde P&L-blok terug: label -> {periode: exacte waarde}.

    De cellen dragen data-fin-full (volledige precisie), zodat de vergelijking
    met de API niet op de afgeronde weergave hoeft te steunen.
    """
    return page.evaluate(
        """() => {
            const out = {};
            document.querySelectorAll('#consolDiv tr.consol-row').forEach(tr => {
                const label = tr.querySelector('td').textContent.trim();
                const cells = {};
                tr.querySelectorAll('td[data-fin-period]').forEach(td => {
                    cells[td.dataset.finPeriod] = parseFloat(td.dataset.finFull);
                });
                out[label] = cells;
            });
            return out;
        }"""
    )


def _editable_candidates(payload, wanted=2):
    """Rijen die de UI als bewerkbare Aux-cel rendert, met volume > 0."""
    found = []
    for line_type in VALUE_AUX_EDITABLE:
        for row in payload["results"].get(line_type, []):
            material = str(row.get("material_number") or "")
            if material.startswith("ZZZZZZ_"):
                continue
            aux = row.get("aux_column")
            if aux is None:
                continue
            try:
                aux = float(aux)
            except (TypeError, ValueError):
                continue
            if aux <= 0:
                continue
            if sum(abs(float(v)) for v in row["values"].values()) <= 0:
                continue
            found.append({"line_type": line_type, "material": material, "aux": aux,
                          "values": dict(row["values"])})
            break  # hoogstens één kandidaat per line type: spreidt de test
    return found[:wanted]


def _search_material(page, material):
    page.fill("#vpMatSearch", str(material))
    page.wait_for_function(
        """(mat) => {
            const rows = [...document.querySelectorAll('#vpBody tr[data-material]')]
                .filter(r => r.style.display !== 'none');
            return rows.length > 0 && rows.every(
                r => r.dataset.material.startsWith('ZZZZZZ_')
                     || r.dataset.material === mat);
        }""",
        arg=str(material),
        timeout=30000,
    )


def _edit_aux_via_ui(page, line_type, material, new_value):
    """Bewerk één Aux-cel zoals een gebruiker: zoeken, klikken, typen, Enter."""
    _search_material(page, material)
    cell = page.locator(
        f'#vpBody tr[data-linetype="{line_type}"][data-material="{material}"]'
        ' td.editable-cell[data-edit-kind="value-aux"]'
    ).first
    expect(cell).to_be_visible(timeout=30000)
    cell.click()
    expect(cell).to_have_attribute("contenteditable", "true")
    cell.fill(f"{new_value:.6f}")
    with page.expect_response(
        lambda r: "/api/update_value_aux" in r.url and r.ok, timeout=180000
    ):
        cell.press("Enter")
    page.wait_for_function(
        "(key) => Boolean(state.valueAuxEdits && state.valueAuxEdits[key])",
        arg=f"{line_type}||{material}",
        timeout=180000,
    )


def _reset_value_edits(base_url):
    # Een voorganger kan net van sessie gewisseld zijn; de engine warmt dan
    # nog op en het endpoint zegt 400 'No calculations run'. Kort wachten is
    # eerlijker dan omvallen op andermans timing.
    import time
    deadline = time.monotonic() + 90
    while True:
        response = requests.post(
            base_url + "/api/reset_value_planning_edits", timeout=300)
        if response.status_code != 400 or time.monotonic() > deadline:
            break
        time.sleep(0.5)
    response.raise_for_status()
    assert response.json().get("success") is True


# --------------------------------------------------------------------------
# VALUES PLANNING
# --------------------------------------------------------------------------

def test_values_table_renders_every_row_and_period_column(browser_page):
    """De values-tabel wordt in één keer opgebouwd uit state.valueResults. Valt
    daar een line type of een periodekolom uit, dan mist de gebruiker rijen
    zonder dat er iets misgaat — de rijteller onder de tabel zou het dan nog
    steeds "kloppend" melden. Daarom: DOM-telling, zichtbare rijteller en API
    moeten alledrie hetzelfde zeggen."""
    page = browser_page
    base_url = page.server["base_url"]
    _reset_value_edits(base_url)
    page.reload(wait_until="networkidle")
    _open_values(page)

    payload = _value_results(base_url)
    expected_rows = sum(len(rows) for rows in payload["results"].values())
    assert expected_rows > 0

    rendered = page.locator("#vpBody tr[data-material]").count()
    assert rendered == expected_rows, (
        f"tabel rendert {rendered} rijen, API levert er {expected_rows}")
    assert page.locator("#vpRowCount").inner_text().strip() == str(expected_rows)

    headers = [t.strip() for t in page.locator("#vpHead th").all_text_contents()]
    assert headers[:6] == ["Material", "Name", "Line Type", "Aux Column",
                           "Aux 2 Column", "Starting Stock"]
    assert headers[6:] == payload["periods"], headers

    # Elk line type uit de API moet ook echt rijen in de tabel hebben.
    rendered_line_types = set(page.evaluate(
        """() => [...new Set([...document.querySelectorAll('#vpBody tr[data-linetype]')]
                 .map(r => r.dataset.linetype))]"""))
    assert rendered_line_types == set(payload["results"].keys())
    assert page.js_errors == []


def test_consolidation_block_shows_every_pl_row_with_api_numbers(browser_page):
    """Het P&L-blok is het cijfer waar de klant op stuurt. Een verschoven label
    of een rij die stil wegvalt geeft een geloofwaardig maar fout beeld. Toetst
    alle 20 regels op naam én bedrag tegen /api/value_results, plus de twee
    optelrelaties die de tabel zelf toont (marge en EBITDA)."""
    page = browser_page
    base_url = page.server["base_url"]
    _reset_value_edits(base_url)
    page.reload(wait_until="networkidle")
    _open_values(page)

    payload = _value_results(base_url)
    api_rows = _consolidation_by_material(payload)
    periods = payload["periods"]
    assert len(api_rows) >= 20, api_rows.keys()

    rendered = _read_consolidation_table(page)
    assert len(rendered) == len(payload["consolidation"]), (
        f"{len(rendered)} gerenderde consolidatieregels tegen "
        f"{len(payload['consolidation'])} uit de API")

    for material, label in CONSOL_LABEL_BY_MATERIAL.items():
        assert material in api_rows, f"{material} ontbreekt in de API"
        assert label in rendered, f'consolidatieregel "{label}" staat niet in de tabel'
        for period in periods:
            expected = float(api_rows[material].get(period, 0.0) or 0.0)
            if material == "ZZZZZZ_ROCE":
                expected *= 100.0  # ROCE wordt als percentage getekend
            shown = rendered[label].get(period)
            assert shown is not None, f"{label} mist kolom {period}"
            assert abs(shown - expected) <= max(0.001, 1e-6 * abs(expected)), (
                f"{label} {period}: tabel {shown}, API {expected}")

    # Interne consistentie van het getoonde blok (VBA-consolidatie).
    for period in periods:
        margin = rendered["Turnover"][period] - rendered["Cost of Goods"][period]
        assert abs(rendered["Gross Margin"][period] - margin) <= 0.01, period
        ebitda = rendered["Gross Margin"][period] - rendered["SG&A Cost"][period]
        assert abs(rendered["EBITDA"][period] - ebitda) <= 0.01, period
    assert page.js_errors == []


def test_value_cells_match_api_value_results(browser_page):
    """De maandcellen dragen data-raw (de ruwe waarde waarop copy/paste,
    sortering en de deltaberekening steunen). Loopt die uit de pas met de API,
    dan exporteert de gebruiker andere getallen dan hij ziet."""
    page = browser_page
    base_url = page.server["base_url"]
    _reset_value_edits(base_url)
    page.reload(wait_until="networkidle")
    _open_values(page)

    payload = _value_results(base_url)
    periods = payload["periods"]

    # Neem per line type de rij met het grootste absolute volume: die valt op
    # als er iets misgaat en is nooit een triviale nulrij.
    samples = []
    for line_type, rows in payload["results"].items():
        best = None
        for row in rows:
            total = sum(abs(float(v)) for v in row["values"].values())
            if total > 0 and (best is None or total > best[0]):
                best = (total, row)
        if best is not None:
            samples.append((line_type, best[1]))
    assert len(samples) >= 5, [s[0] for s in samples]

    checked = 0
    for line_type, row in samples:
        material = str(row["material_number"])
        selector = (f'#vpBody tr[data-linetype="{line_type}"]'
                    f'[data-material="{material}"]')
        if page.locator(selector).count() != 1:
            continue  # zelfde materiaal meerdere keren in dit line type
        cells = page.locator(selector).first.evaluate(
            """tr => {
                const out = {};
                tr.querySelectorAll('td[data-period]').forEach(td => {
                    out[td.dataset.period] = Number(td.dataset.raw);
                });
                return out;
            }"""
        )
        assert set(cells.keys()) == set(periods), (line_type, material)
        for period in periods:
            expected = float(row["values"].get(period, 0.0) or 0.0)
            assert abs(cells[period] - expected) <= max(1e-6, 1e-9 * abs(expected)), (
                f"{line_type} / {material} / {period}: "
                f"tabel {cells[period]}, API {expected}")
        checked += 1

    assert checked >= 5, f"slechts {checked} rijen konden vergeleken worden"
    assert page.js_errors == []


def test_value_kpi_tiles_average_the_consolidation_rows(browser_page):
    """De vier tegels tonen MAANDGEMIDDELDEN. Een som in plaats van een
    gemiddelde is over een jaarhorizon een factor twaalf te hoog en toch
    plausibel — precies het soort fout dat pas bij de klant opvalt."""
    page = browser_page
    base_url = page.server["base_url"]
    _reset_value_edits(base_url)
    page.reload(wait_until="networkidle")
    _open_values(page)

    payload = _value_results(base_url)
    api_rows = _consolidation_by_material(payload)
    periods = payload["periods"]
    assert len(periods) > 1

    def average(material):
        values = [float(api_rows[material].get(p, 0.0) or 0.0) for p in periods
                  if p in api_rows[material]]
        return sum(values) / len(values) if values else 0.0

    for element_id, material in (("vp-turnover", "ZZZZZZ_TURNOVER"),
                                 ("vp-ebitda", "ZZZZZZ_EBITDA"),
                                 ("vp-ebit", "ZZZZZZ_EBIT")):
        text = page.locator(f"#{element_id}").inner_text().strip()
        assert text and text != "-" and "NaN" not in text, f"{element_id}: {text!r}"
        _assert_compact_equals(text, average(material), element_id)

    roce_text = page.locator("#vp-roce").inner_text().strip()
    assert roce_text.endswith("%"), roce_text
    expected_roce = average("ZZZZZZ_ROCE") * 100.0
    assert abs(float(roce_text[:-1]) - expected_roce) <= 0.06, (
        f"vp-roce toont {roce_text}, verwacht {expected_roce:.1f}%")
    assert page.js_errors == []


def test_aux_edit_cascades_to_row_consolidation_and_kpi(browser_page):
    """Een Aux-bewerking is een prijs: rijwaarde = volume x prijs, en de
    omzetregel is de som van de Line 01-waarderijen. Verdubbelt de prijs, dan
    moet de rij exact verdubbelen en de omzet exact met de oude rijwaarde
    stijgen. Blijft de consolidatie of de KPI-tegel staan, dan spreken tabel en
    grafiek elkaar tegen zonder dat er iets faalt."""
    page = browser_page
    base_url = page.server["base_url"]
    _reset_value_edits(base_url)
    page.reload(wait_until="networkidle")
    _open_values(page)

    payload = _value_results(base_url)
    candidates = [c for c in _editable_candidates(payload, wanted=6)
                  if c["line_type"] == "01. Demand forecast"]
    if not candidates:
        pytest.skip("geen bewerkbare Line 01-prijsrij met volume in deze fixture")
    target = candidates[0]
    material, line_type = target["material"], target["line_type"]
    periods = payload["periods"]

    before_consol = _read_consolidation_table(page)
    before_turnover = page.locator("#vp-turnover").inner_text().strip()

    try:
        page.locator("#values-tab .edit-mode-btn").click()
        expect(page.locator("body")).to_have_class(re.compile(r".*\bedit-mode\b.*"))

        _edit_aux_via_ui(page, line_type, material, target["aux"] * 2.0)

        # 1. De rij zelf verdubbelt in de tabel.
        cells = page.locator(
            f'#vpBody tr[data-linetype="{line_type}"][data-material="{material}"]'
        ).first.evaluate(
            """tr => {
                const out = {};
                tr.querySelectorAll('td[data-period]').forEach(td => {
                    out[td.dataset.period] = Number(td.dataset.raw);
                });
                return out;
            }"""
        )
        for period in periods:
            expected = float(target["values"].get(period, 0.0) or 0.0) * 2.0
            assert abs(cells[period] - expected) <= max(1e-6, 1e-6 * abs(expected)), (
                f"{period}: rij toont {cells[period]}, verwacht {expected}")

        # 2. De omzetregel stijgt met precies de oude rijwaarde.
        after_consol = _read_consolidation_table(page)
        moved = 0
        for period in periods:
            delta = (after_consol["Turnover"][period]
                     - before_consol["Turnover"][period])
            expected_delta = float(target["values"].get(period, 0.0) or 0.0)
            assert abs(delta - expected_delta) <= max(0.01, 1e-6 * abs(expected_delta)), (
                f"omzet {period}: delta {delta}, verwacht {expected_delta}")
            if abs(expected_delta) > 0:
                moved += 1
        assert moved > 0, "de gekozen rij had in geen enkele periode volume"

        # 3. De KPI-tegel volgt de nieuwe consolidatie.
        after_turnover = page.locator("#vp-turnover").inner_text().strip()
        assert after_turnover != before_turnover, (
            f"omzet-KPI bleef op {before_turnover} staan na de prijsbewerking")
        new_avg = sum(after_consol["Turnover"][p] for p in periods) / len(periods)
        _assert_compact_equals(after_turnover, new_avg, "vp-turnover na bewerking")

        # 4. De server is het echt eens: de override staat in value_results.
        server_row = next(
            r for r in _value_results(base_url)["results"][line_type]
            if str(r["material_number"]) == material)
        assert abs(float(server_row["aux_column"]) - target["aux"] * 2.0) <= 1e-6
        assert page.js_errors == []
    finally:
        _reset_value_edits(base_url)


def test_values_tab_badge_counts_aux_edits_and_clears_on_reset(browser_page):
    """Het badge-getal op het tabblad is het enige signaal dat er nog
    ongereviewde prijswijzigingen in de sessie zitten wanneer je op een ander
    tabblad staat. Telt hij verkeerd of blijft hij hangen na een reset, dan
    exporteert iemand een scenario waarvan hij denkt dat het schoon is."""
    page = browser_page
    base_url = page.server["base_url"]
    _reset_value_edits(base_url)
    page.reload(wait_until="networkidle")
    _open_values(page)

    payload = _value_results(base_url)
    candidates = _editable_candidates(payload, wanted=2)
    if len(candidates) < 2:
        pytest.skip("minder dan twee bewerkbare Aux-rijen in deze fixture")

    badge = page.locator("#valuesTabBadge")
    expect(badge).to_be_hidden()

    try:
        page.locator("#values-tab .edit-mode-btn").click()
        expect(page.locator("body")).to_have_class(re.compile(r".*\bedit-mode\b.*"))

        for index, candidate in enumerate(candidates, start=1):
            _edit_aux_via_ui(page, candidate["line_type"], candidate["material"],
                             candidate["aux"] * 1.5)
            expect(badge).to_be_visible()
            expect(badge).to_have_text(str(index))
            assert page.evaluate(
                "() => Object.keys(state.valueAuxEdits || {}).length") == index

        # De server draagt beide prijzen ook echt: het badge-getal is geen
        # puur client-side telling van iets dat nooit is opgeslagen.
        server_side = _value_results(base_url)
        for candidate in candidates:
            row = next(r for r in server_side["results"][candidate["line_type"]]
                       if str(r["material_number"]) == candidate["material"])
            assert abs(float(row["aux_column"]) - candidate["aux"] * 1.5) <= 1e-6

        # Reset via de knop in de UI (met bevestigingsdialoog).
        page.once("dialog", lambda dialog: dialog.accept())
        with page.expect_response(
            lambda r: "/api/reset_value_planning_edits" in r.url and r.ok,
            timeout=300000,
        ):
            page.evaluate("() => resetValuePlanningEdits()")
        page.wait_for_function(
            "() => Object.keys(state.valueAuxEdits || {}).length === 0",
            timeout=300000)

        expect(badge).to_be_hidden()
        # En de waarden zijn echt terug op de uitgangswaarde.
        restored = _value_results(base_url)
        for candidate in candidates:
            row = next(r for r in restored["results"][candidate["line_type"]]
                       if str(r["material_number"]) == candidate["material"])
            assert abs(float(row["aux_column"]) - candidate["aux"]) <= 1e-6
        assert page.js_errors == []
    finally:
        _reset_value_edits(base_url)


# --------------------------------------------------------------------------
# INVENTORY
# --------------------------------------------------------------------------

def test_inventory_kpi_tiles_add_up_to_the_table_rows(browser_page):
    """Healthy/Low/Overstock is een volledige indeling: elk materiaal in de
    tabel valt in precies één tegel. Telt het niet op, dan zijn er materialen
    stil uit de statusindeling gevallen en onderschat de gebruiker zijn
    voorraadrisico."""
    page = browser_page
    base_url = page.server["base_url"]
    _open_inventory(page)

    api = requests.get(base_url + "/api/inventory", timeout=180).json()
    assert "error" not in api, api

    tiles = {
        "healthy": int(page.locator("#inv-ok").inner_text().strip()),
        "low": int(page.locator("#inv-low").inner_text().strip()),
        "high": int(page.locator("#inv-high").inner_text().strip()),
    }
    for key, value in tiles.items():
        assert value == api["summary"][key], (key, value, api["summary"])

    rows = page.locator("#invBody tr").count()
    assert rows == len(api["data"]) > 0
    assert tiles["healthy"] + tiles["low"] + tiles["high"] == rows, (tiles, rows)

    # De tegels tellen exact wat er in de statuskolom staat.
    rendered_status = page.evaluate(
        """() => {
            const counts = {};
            document.querySelectorAll('#invBody tr').forEach(tr => {
                const td = tr.querySelectorAll('td')[2];
                if (!td) return;
                const s = td.textContent.trim();
                counts[s] = (counts[s] || 0) + 1;
            });
            return counts;
        }""")
    assert rendered_status.get("OK", 0) == tiles["healthy"]
    assert rendered_status.get("LOW", 0) == tiles["low"]
    assert rendered_status.get("HIGH", 0) == tiles["high"]
    assert page.js_errors == []


def test_inventory_table_renders_every_material_with_periods(browser_page):
    """De tabel is de enige plek waar de voorraadstand per maand te zien is.
    Een verschoven kolom of een ontbrekend materiaal maakt de statuskolom
    onverklaarbaar; daarom wordt hier op materiaal, kolomkoppen én bedragen
    getoetst."""
    page = browser_page
    base_url = page.server["base_url"]
    _open_inventory(page)

    api = requests.get(base_url + "/api/inventory", timeout=180).json()
    periods = api["periods"]
    assert periods

    headers = [t.strip() for t in page.locator("#invHead th").all_text_contents()]
    assert headers == ["Material", "Name", "Status"] + periods, headers

    rendered = page.evaluate(
        """() => [...document.querySelectorAll('#invBody tr')].map(tr => {
            const tds = [...tr.querySelectorAll('td')];
            return {
                material: tds[0].textContent.trim(),
                status: tds[2] ? tds[2].textContent.trim() : null,
                cls: tds[2] ? tds[2].className : '',
                cells: tds.slice(3).map(td => td.textContent.trim()),
            };
        })""")
    assert len(rendered) == len(api["data"])

    colour_by_status = {"LOW": "text-red-400", "HIGH": "text-yellow-400",
                        "OK": "text-green-400"}
    for shown, expected in zip(rendered, api["data"]):
        assert shown["material"] == str(expected["material_number"])
        assert shown["status"] == expected["status"]
        assert colour_by_status[expected["status"]] in shown["cls"], shown
        assert len(shown["cells"]) == len(periods), shown

    # Bedragen van de eerste rij met echte voorraad tegen de API.
    checked = False
    for shown, expected in zip(rendered, api["data"]):
        if sum(abs(float(v)) for v in expected["values"].values()) <= 0:
            continue
        for index, period in enumerate(periods):
            _assert_compact_equals(
                shown["cells"][index],
                float(expected["values"].get(period, 0.0) or 0.0),
                f"{shown['material']} {period}")
        checked = True
        break
    assert checked, "geen enkel materiaal met voorraad in de tabel"
    assert page.js_errors == []


def test_inventory_status_follows_stock_versus_target_rule(browser_page):
    """De statusindeling is de rekenregel van dit tabblad: LOW bij lege of
    halve voorraad ten opzichte van de minimum-doelvoorraad, HIGH boven het
    dubbele. Hier wordt hij onafhankelijk nagerekend uit Line 04 en Line 05 van
    /api/results, zodat een stille wijziging in de drempels of in het
    gemiddelde over de horizon zichtbaar wordt in plaats van dat de tabel
    zichzelf bevestigt."""
    page = browser_page
    base_url = page.server["base_url"]
    _open_inventory(page)

    api = requests.get(base_url + "/api/inventory", timeout=180).json()
    results = requests.get(base_url + "/api/results", timeout=300).json()
    periods = api["periods"]
    inventory_rows = results["results"]["04. Inventory"]
    target_rows = results["results"]["05. Minimum target stock"]
    target_lookup = {str(r["material_number"]): r["values"] for r in target_rows}

    expected_status = []
    counts = {"OK": 0, "LOW": 0, "HIGH": 0}
    for row in inventory_rows:
        target = target_lookup.get(str(row["material_number"]), {})
        avg_inv = sum(float(row["values"].get(p, 0) or 0) for p in periods) / len(periods)
        avg_tgt = (sum(float(target.get(p, 0) or 0) for p in periods) / len(periods)
                   if target else 0.0)
        if avg_inv <= 0:
            status = "LOW"
        elif avg_tgt > 0 and avg_inv < avg_tgt * 0.5:
            status = "LOW"
        elif avg_tgt > 0 and avg_inv > avg_tgt * 2:
            status = "HIGH"
        else:
            status = "OK"
        expected_status.append((str(row["material_number"]), status))
        counts[status] += 1

    assert len(expected_status) == len(api["data"])
    api_status = [(str(r["material_number"]), r["status"]) for r in api["data"]]
    mismatches = [(a, b) for a, b in zip(api_status, expected_status) if a != b]
    assert not mismatches, mismatches[:5]

    # En het scherm toont diezelfde indeling.
    shown = page.evaluate(
        """() => [...document.querySelectorAll('#invBody tr')].map(tr => {
            const tds = tr.querySelectorAll('td');
            return [tds[0].textContent.trim(), tds[2].textContent.trim()];
        })""")
    assert [tuple(pair) for pair in shown] == expected_status
    assert int(page.locator("#inv-ok").inner_text().strip()) == counts["OK"]
    assert int(page.locator("#inv-low").inner_text().strip()) == counts["LOW"]
    assert int(page.locator("#inv-high").inner_text().strip()) == counts["HIGH"]
    assert page.js_errors == []
