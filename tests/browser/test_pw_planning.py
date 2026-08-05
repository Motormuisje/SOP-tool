"""Browsertests voor het PLANNING-tabblad (de grote tabel).

Dekt gedrag dat NIET al in test_edits.py (celedit/undo/heatmapklasse op
'01. Demand forecast') of test_sort.py (sorteren op periodekolom, groeperen,
line-type-filter) zit:

- de kolomkop moet exact de periodes van de server tonen (kolomdrift is
  onzichtbaar in de UI maar verschuift elk getal een maand);
- zoeken/filteren (filterTable) inclusief de lege-doorsnede-uitweg;
- de sticky header tijdens scrollen;
- sorteren op de 'Start'-kolom (starting stock) en terug naar standaardvolgorde;
- de starting-stock-editpad (sentinelperiode 'starting_stock');
- undo EN redo, met exacte herstelcontrole op alle regels van één materiaal;
- afwijzen van niet-numerieke invoer zonder de cel of de server te vervuilen;
- de zichtbare cascade van '01. Demand forecast' naar '03. Total demand'.

Elke test controleert getallen/gedrag, niet alleen aanwezigheid van elementen.
"""

import re

import pytest
import requests
from playwright.sync_api import expect


pytestmark = pytest.mark.browser


HEAD_LABELS = ["Material", "Name", "Line Type", "Aux", "Aux 2", "Start"]

# Leest de autoritatieve servertoestand voor één materiaal: alle line types,
# alle periodes plus de starting stock. Klein genoeg om exact te vergelijken.
READ_MATERIAL_JS = """async (mat) => {
    const data = await (await fetch('/api/results')).json();
    const out = {};
    for (const lt of Object.keys(data.results || {})) {
        for (const row of data.results[lt]) {
            if (String(row.material_number) !== String(mat)) continue;
            out[lt + '||' + (row.aux_column || '')] = {
                start: Number(row.starting_stock || 0),
                values: row.values || {},
            };
        }
    }
    return out;
}"""

READ_CELL_JS = """async ([lt, mat, period]) => {
    const data = await (await fetch('/api/results')).json();
    const rows = (data.results || {})[lt] || [];
    const row = rows.find(r => String(r.material_number) === String(mat));
    if (!row) return null;
    return period === 'starting_stock'
        ? Number(row.starting_stock || 0)
        : Number((row.values || {})[period] || 0);
}"""


def _reset_server_edits(base_url: str) -> None:
    """Terug naar de schone baseline; de server is session-scoped gedeeld."""
    requests.post(base_url + "/api/reset_edits", timeout=300).raise_for_status()


def _open_planning(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.locator("button.tab-btn[onclick*=\"showTab('planning'\"]").first.click()
    expect(page.locator("#planning-tab")).to_be_visible()
    expect(page.locator("#planBody tr[data-material]").first).to_be_visible(timeout=60000)


def _enable_edit_mode(page):
    page.locator("#planning-tab .edit-mode-btn").click()
    expect(page.locator("body")).to_have_class(re.compile(r".*edit-mode.*"))


def _visible_row_count(page) -> int:
    return page.evaluate(
        """() => [...document.querySelectorAll('#planBody tr[data-material]')]
                    .filter(r => r.style.display !== 'none').length"""
    )


def _commit_cell(page, cell, text):
    """Klik de cel open, vul tekst en bevestig met Enter."""
    cell.click()
    expect(cell).to_have_attribute("contenteditable", "true")
    cell.fill(text)
    cell.press("Enter")


def test_period_columns_match_server_period_list(browser_page):
    """De kolomkop wordt client-side afgeleid uit de Line 01-waarden, niet uit
    de periodelijst van de server. Loopt die afleiding een maand uit de pas,
    dan staat elk getal onder de verkeerde maand zonder zichtbare fout."""
    page = browser_page
    _open_planning(page)

    headers = page.evaluate(
        "() => [...document.querySelectorAll('#planHead th')].map(th => th.textContent.trim())"
    )
    assert headers[: len(HEAD_LABELS)] == HEAD_LABELS
    assert headers[len(HEAD_LABELS):] == page.server["expected_periods"]

    # Elke datarij draagt precies dezelfde periodecellen (de starting-stock-cel
    # gebruikt een sentinelperiode en telt niet mee).
    row_periods = page.evaluate(
        """() => {
            const rows = [...document.querySelectorAll('#planBody tr[data-material]')].slice(0, 25);
            return rows.map(r => [...r.querySelectorAll('td[data-period]')]
                .map(c => c.dataset.period)
                .filter(p => p !== 'starting_stock'));
        }"""
    )
    assert len(row_periods) > 1
    for periods in row_periods:
        assert periods == page.server["expected_periods"]

    assert page.js_errors == []


def test_search_filters_rows_and_row_count_follows(browser_page):
    """filterTable() verbergt rijen op zoekterm en werkt de teller #rowCount bij.
    Zonder die koppeling ziet de gebruiker een subset maar leest hij het totaal —
    en trekt hij conclusies over 'alle' materialen op een gefilterde tabel."""
    page = browser_page
    _open_planning(page)

    total = page.evaluate("() => document.querySelectorAll('#planBody tr[data-material]').length")
    assert total > 5
    term = page.evaluate("() => document.querySelector('#planBody tr[data-material]').dataset.material")
    assert term

    page.fill("#matSearch", term)
    page.wait_for_function(
        """(term) => {
            const rows = [...document.querySelectorAll('#planBody tr[data-material]')];
            const vis = rows.filter(r => r.style.display !== 'none').length;
            const expected = rows.filter(r => (r.dataset.search || '').includes(term.toLowerCase())).length;
            return vis === expected
                && document.getElementById('rowCount').textContent === String(vis);
        }""",
        arg=term,
        timeout=30000,
    )

    report = page.evaluate(
        """(term) => {
            const t = term.toLowerCase();
            const rows = [...document.querySelectorAll('#planBody tr[data-material]')];
            const shown = rows.filter(r => r.style.display !== 'none');
            const hidden = rows.filter(r => r.style.display === 'none');
            return {
                total: rows.length,
                shown: shown.length,
                allShownMatch: shown.every(r => (r.dataset.search || '').includes(t)),
                anyHiddenMatch: hidden.some(r => (r.dataset.search || '').includes(t)),
                rowCount: Number(document.getElementById('rowCount').textContent),
            };
        }""",
        term,
    )
    assert 0 < report["shown"] < report["total"], report
    assert report["allShownMatch"] is True
    assert report["anyHiddenMatch"] is False, "een rij die matcht werd toch verborgen"
    assert report["rowCount"] == report["shown"]

    # Zoekterm wissen brengt alle rijen terug.
    page.fill("#matSearch", "")
    page.wait_for_function(
        """(total) => {
            const rows = [...document.querySelectorAll('#planBody tr[data-material]')];
            return rows.filter(r => r.style.display !== 'none').length === total
                && document.getElementById('rowCount').textContent === String(total);
        }""",
        arg=total,
        timeout=30000,
    )

    assert page.js_errors == []


def test_empty_filter_result_shows_hint_with_working_escape_hatch(browser_page):
    """Een filtercombinatie die alles wegfiltert moet zichzelf uitleggen en een
    uitweg bieden; een stil lege tabel was de 'ik zit vast'-meldingsbron."""
    page = browser_page
    _open_planning(page)
    total = page.evaluate("() => document.querySelectorAll('#planBody tr[data-material]').length")

    page.fill("#matSearch", "zzzz-bestaat-niet-zzzz")
    hint = page.locator("#planEmptyHint")
    expect(hint).to_be_visible(timeout=30000)
    page.wait_for_function(
        "() => document.getElementById('rowCount').textContent === '0'", timeout=30000
    )
    assert _visible_row_count(page) == 0

    hint.locator("button").click()

    page.wait_for_function(
        """(total) => {
            const rows = [...document.querySelectorAll('#planBody tr[data-material]')];
            return rows.filter(r => r.style.display !== 'none').length === total;
        }""",
        arg=total,
        timeout=30000,
    )
    expect(hint).to_be_hidden()
    assert page.input_value("#matSearch") == ""
    assert page.evaluate("() => document.getElementById('rowCount').textContent") == str(total)

    assert page.js_errors == []


def test_sticky_header_stays_pinned_while_body_scrolls(browser_page):
    """De periodekop moet tijdens het scrollen blijven staan; zonder sticky
    header leest de gebruiker halverwege de tabel getallen zonder maandkop."""
    page = browser_page
    _open_planning(page)

    before = page.evaluate(
        """() => {
            const box = document.getElementById('planTableScroll');
            return { scrollable: box.scrollHeight - box.clientHeight, scrollTop: box.scrollTop };
        }"""
    )
    assert before["scrollable"] > 400, "tabel is niet scrollbaar; test zegt niets"
    assert before["scrollTop"] == 0

    page.evaluate("() => { document.getElementById('planTableScroll').scrollTop = 600; }")
    page.wait_for_function(
        "() => document.getElementById('planTableScroll').scrollTop >= 400", timeout=30000
    )

    geom = page.evaluate(
        """() => {
            const box = document.getElementById('planTableScroll');
            const head = document.getElementById('planHead');
            const rows = [...document.querySelectorAll('#planBody tr[data-material]')]
                .filter(r => r.style.display !== 'none');
            const boxRect = box.getBoundingClientRect();
            const headRect = head.getBoundingClientRect();
            const firstRect = rows[0].getBoundingClientRect();
            return {
                boxTop: boxRect.top,
                headTop: headRect.top,
                headHeight: headRect.height,
                firstRowTop: firstRect.top,
                headText: [...head.querySelectorAll('th')].map(th => th.textContent.trim()).join('|'),
            };
        }"""
    )
    assert geom["headHeight"] > 0
    # De kop kleeft aan de bovenrand van de scrollcontainer...
    assert abs(geom["headTop"] - geom["boxTop"]) <= 2, geom
    # ...terwijl de eerste datarij er wél onder/boven weg is gescrold.
    assert geom["firstRowTop"] < geom["boxTop"] - 1, geom
    assert geom["headText"].startswith("|".join(HEAD_LABELS))

    assert page.js_errors == []


def test_sort_by_start_column_and_back_to_default_order(browser_page):
    """De 'Start'-kolom (starting stock) is de enige niet-periode sorteerkolom;
    hij leest item.starting_stock in plaats van values[periode]. Derde klik moet
    terug naar de standaardvolgorde op materiaalnummer."""
    page = browser_page
    _open_planning(page)

    caret = page.locator("#planHead th.th-sortable .sort-caret").first
    caret.click()
    expect(page.locator("#planHead th.th-sortable .sort-caret").first).to_have_class(
        re.compile(r"\bdesc\b")
    )

    order_js = """(dir) => {
        const rows = [...document.querySelectorAll('#planBody tr[data-material]')];
        const idx = {};
        Object.values(state.results).flat().forEach(it => {
            idx[`${it.line_type}||${it.material_number}||${it.aux_column || ''}`] =
                Math.abs(Number(it.starting_stock || 0));
        });
        const vals = rows.map(r =>
            idx[`${r.dataset.linetype}||${r.dataset.material}||${r.dataset.aux || ''}`] || 0);
        let sorted = true;
        for (let i = 1; i < vals.length; i++) {
            if (dir === -1 && vals[i] > vals[i - 1] + 1e-6) sorted = false;
            if (dir === 1 && vals[i] + 1e-6 < vals[i - 1]) sorted = false;
        }
        return { sorted, n: vals.length, nonzero: vals.filter(v => v > 0).length, top: vals[0] };
    }"""

    desc = page.evaluate(order_js, -1)
    assert desc["n"] > 1
    assert desc["nonzero"] > 0, "geen enkele rij heeft starting stock; sortering is betekenisloos"
    assert desc["top"] > 0, "grootste starting stock staat niet bovenaan"
    assert desc["sorted"] is True, "aflopende sortering op starting stock klopt niet"

    page.locator("#planHead th.th-sortable .sort-caret").first.click()
    expect(page.locator("#planHead th.th-sortable .sort-caret").first).to_have_class(
        re.compile(r"\basc\b")
    )
    asc = page.evaluate(order_js, 1)
    assert asc["sorted"] is True, "oplopende sortering op starting stock klopt niet"
    assert asc["n"] == desc["n"]

    # Derde klik: caret uit, terug naar de standaardvolgorde (materiaalnummer
    # oplopend, regels van hetzelfde materiaal bij elkaar).
    page.locator("#planHead th.th-sortable .sort-caret").first.click()
    expect(page.locator("#planHead th.th-sortable .sort-caret").first).not_to_have_class(
        re.compile(r"\bactive\b")
    )
    default_order = page.evaluate(
        """() => {
            const rows = [...document.querySelectorAll('#planBody tr[data-material]')];
            const mats = rows.map(r => r.dataset.material);
            let ascending = true;
            for (let i = 1; i < mats.length; i++) {
                if (String(mats[i]).localeCompare(String(mats[i - 1]), undefined, { numeric: true }) < 0) {
                    ascending = false;
                }
            }
            let contiguous = true; const seen = new Set(); let prev = null;
            for (const m of mats) {
                if (m !== prev) { if (seen.has(m)) contiguous = false; seen.add(m); prev = m; }
            }
            return { ascending, contiguous, n: mats.length };
        }"""
    )
    assert default_order["n"] == desc["n"]
    assert default_order["ascending"] is True, "standaardvolgorde niet op materiaalnummer"
    assert default_order["contiguous"] is True

    assert page.js_errors == []


def test_starting_stock_edit_marks_dirty_and_persists_number(browser_page):
    """De 'Start'-kolom van Line 04 gaat via de sentinelperiode
    'starting_stock' naar de server — een ander pad dan de periodecellen.
    Valt dat weg, dan lijkt de bewerking te lukken maar rekent de engine door
    met de oude beginvoorraad."""
    page = browser_page
    base_url = page.server["base_url"]
    _reset_server_edits(base_url)
    page.reload(wait_until="networkidle")
    _open_planning(page)
    _enable_edit_mode(page)

    cell = page.locator('#planBody td.editable-cell[data-edit-kind="starting-stock"]').first
    expect(cell).to_be_visible(timeout=60000)
    info = cell.evaluate(
        "c => ({ raw: Number(c.dataset.raw || '0'), lt: c.dataset.lt, mat: c.dataset.matnum })"
    )
    new_value = round(info["raw"] + 4321.0, 3)

    before = page.evaluate(READ_CELL_JS, [info["lt"], info["mat"], "starting_stock"])
    assert before is not None
    assert abs(before - info["raw"]) < 1e-3, (before, info["raw"])

    with page.expect_response(lambda r: "/api/update_volume" in r.url and r.ok):
        _commit_cell(page, cell, str(new_value))
    page.wait_for_load_state("networkidle")

    expect(page.locator("#editSummaryBar")).to_be_visible()
    expect(page.locator("#editSummaryCount")).to_contain_text("1")
    expect(cell).to_have_class(re.compile(r".*\bcell-increased\b.*"))

    after = page.evaluate(READ_CELL_JS, [info["lt"], info["mat"], "starting_stock"])
    assert abs(after - new_value) < 1e-3, (after, new_value)
    assert abs(float(cell.get_attribute("data-raw")) - new_value) < 1e-3

    assert page.js_errors == []
    _reset_server_edits(base_url)


def test_undo_and_redo_restore_the_material_block_exactly(browser_page):
    """Undo/redo moeten de HELE cascade van een materiaal exact terugzetten,
    niet alleen de bewerkte cel. Een undo die alleen de cel herstelt laat de
    afgeleide regels op de bewerkte waarde staan — cijfers die nergens meer
    bij horen."""
    page = browser_page
    base_url = page.server["base_url"]
    _reset_server_edits(base_url)
    page.reload(wait_until="networkidle")
    _open_planning(page)
    _enable_edit_mode(page)

    period = page.server["expected_periods"][-1]
    cell = page.locator(
        f'#planBody td.editable-cell[data-lt="01. Demand forecast"][data-period="{period}"]'
    ).first
    expect(cell).to_be_visible(timeout=60000)
    mat = cell.get_attribute("data-matnum")
    original_raw = float(cell.get_attribute("data-raw") or "0")
    new_value = round(original_raw + 777.0, 3)

    baseline = page.evaluate(READ_MATERIAL_JS, mat)
    assert baseline, f"geen serverrijen voor materiaal {mat}"

    with page.expect_response(lambda r: "/api/update_volume" in r.url and r.ok):
        _commit_cell(page, cell, str(new_value))
    page.wait_for_load_state("networkidle")

    edited = page.evaluate(READ_MATERIAL_JS, mat)
    assert edited != baseline, "edit veranderde niets aan de servertoestand"
    demand_keys = [k for k in edited if k.startswith("01. Demand forecast||")]
    assert len(demand_keys) == 1, demand_keys
    assert abs(edited[demand_keys[0]]["values"][period] - new_value) < 1e-3
    expect(page.locator("#editSummaryBar")).to_be_visible()

    with page.expect_response(lambda r: "/api/undo" in r.url and r.ok):
        page.locator("#undoBtn").click()
    page.wait_for_load_state("networkidle")

    assert page.evaluate(READ_MATERIAL_JS, mat) == baseline, "undo herstelde niet exact"
    expect(page.locator("#editSummaryBar")).not_to_be_visible()

    # Redo via de sneltoets: de knop zit in de balk die na undo verborgen is.
    with page.expect_response(lambda r: "/api/redo" in r.url and r.ok):
        page.keyboard.press("Control+y")
    page.wait_for_load_state("networkidle")

    assert page.evaluate(READ_MATERIAL_JS, mat) == edited, "redo herstelde niet exact"
    expect(page.locator("#editSummaryBar")).to_be_visible()

    assert page.js_errors == []
    _reset_server_edits(base_url)


def test_non_numeric_input_is_rejected_without_touching_cell_or_server(browser_page):
    """Niet-numerieke invoer mag niet committen: geen /api/update_volume, geen
    edit-teller en de cel toont weer de oorspronkelijke waarde. Zou dit
    doorlopen, dan belandt NaN in de cascade en zijn alle afgeleide regels weg."""
    page = browser_page
    base_url = page.server["base_url"]
    _reset_server_edits(base_url)
    page.reload(wait_until="networkidle")
    _open_planning(page)
    _enable_edit_mode(page)

    period = page.server["expected_periods"][-1]
    cell = page.locator(
        f'#planBody td.editable-cell[data-lt="01. Demand forecast"][data-period="{period}"]'
    ).first
    expect(cell).to_be_visible(timeout=60000)
    mat = cell.get_attribute("data-matnum")
    original_raw = float(cell.get_attribute("data-raw") or "0")
    original_text = cell.inner_text().strip()
    before = page.evaluate(READ_CELL_JS, ["01. Demand forecast", mat, period])
    assert abs(before - original_raw) < 1e-3

    posted = []
    page.on("request", lambda req: posted.append(req.url))

    _commit_cell(page, cell, "niet-een-getal")
    page.wait_for_load_state("networkidle")

    assert [u for u in posted if "/api/update_volume" in u] == [], posted
    expect(cell).not_to_have_attribute("contenteditable", "true")
    expect(cell).to_have_class(re.compile(r"^(?!.*cell-(increased|decreased|edited)).*$"))
    expect(page.locator("#editSummaryBar")).not_to_be_visible()
    assert cell.inner_text().strip() == original_text
    assert abs(float(cell.get_attribute("data-raw") or "0") - original_raw) < 1e-3

    after = page.evaluate(READ_CELL_JS, ["01. Demand forecast", mat, period])
    assert abs(after - before) < 1e-3, (before, after)

    assert page.js_errors == []


def test_demand_edit_cascades_visibly_to_total_demand_row(browser_page):
    """Line 01 -> Line 03 is de eerste stap van de BOM-cascade. De afhankelijke
    cel moet niet alleen op de server meebewegen maar dat ook TONEN
    (cell-cascade-up + 'was'-annotatie); anders zegt de tabel iets anders dan
    de engine en merkt niemand een gebroken cascade op."""
    page = browser_page
    base_url = page.server["base_url"]
    _reset_server_edits(base_url)
    page.reload(wait_until="networkidle")
    _open_planning(page)
    _enable_edit_mode(page)

    period = page.server["expected_periods"][-1]
    target = page.evaluate(
        """(period) => {
            const totals = new Set(
                (state.results['03. Total demand'] || []).map(r => String(r.material_number)));
            const cells = [...document.querySelectorAll(
                `#planBody td.editable-cell[data-lt="01. Demand forecast"][data-period="${period}"]`)];
            for (const c of cells) {
                if (totals.has(String(c.dataset.matnum))) return c.dataset.matnum;
            }
            return null;
        }""",
        period,
    )
    assert target, "geen materiaal met zowel Line 01 als Line 03 in deze fixture"

    demand_cell = page.locator(
        f'#planBody td.editable-cell[data-lt="01. Demand forecast"]'
        f'[data-matnum="{target}"][data-period="{period}"]'
    ).first
    total_cell = page.locator(
        f'#planBody td[data-lt="03. Total demand"]'
        f'[data-mat="{target}"][data-period="{period}"]'
    ).first
    expect(demand_cell).to_be_visible(timeout=60000)
    expect(total_cell).to_be_attached()

    demand_before = float(demand_cell.get_attribute("data-raw") or "0")
    total_before = page.evaluate(READ_CELL_JS, ["03. Total demand", target, period])
    delta = 5000.0

    with page.expect_response(lambda r: "/api/update_volume" in r.url and r.ok):
        _commit_cell(page, demand_cell, str(round(demand_before + delta, 3)))
    page.wait_for_load_state("networkidle")

    total_after = page.evaluate(READ_CELL_JS, ["03. Total demand", target, period])
    assert total_after is not None and total_before is not None
    assert abs((total_after - total_before) - delta) < 1e-2, (total_before, total_after)

    # Zichtbaar in de tabel: cascadeklasse, bijgewerkte data-raw en 'was'-badge.
    expect(total_cell).to_have_class(re.compile(r".*\bcell-cascade-up\b.*"))
    assert abs(float(total_cell.get_attribute("data-raw") or "0") - total_after) < 1e-2
    expect(total_cell.locator(".cell-casc-was")).to_be_attached()

    assert page.js_errors == []
    _reset_server_edits(base_url)
