import re

from playwright.sync_api import expect


# Verifies the "sort by size" feature added to the Planning and Values Planning
# tables (clickable column carets in ui/templates/index.html):
# - Planning sorts whole material blocks by the largest absolute value among the
#   block's rows in the clicked column (material rows stay grouped together).
# - Values Planning sorts all rows by the clicked column value, with consolidated
#   ZZZZZZ_ rows pinned to the bottom.
# - The caret cycles descending -> ascending -> off, and the existing column-pin
#   click on the rest of the header keeps working (no JS errors).


def _open_tab(page, name):
    page.locator(f"button.tab-btn[onclick*=\"showTab('{name}'\"]").first.click()
    expect(page.locator(f"#{name}-tab")).to_be_visible()


def _planning_rows(page):
    return page.locator("#planBody tr[data-material][data-linetype]")


def test_planning_loose_sort_is_default(browser_page):
    # Default (no "Groepeer materiaal"): rows sort independently by column value,
    # like the Values Planning table.
    page = browser_page
    period = page.server["expected_periods"][0]
    _open_tab(page, "planning")
    expect(_planning_rows(page).nth(0)).to_be_visible(timeout=60000)
    assert page.evaluate("document.getElementById('planGroupSort').checked") is False

    page.locator("#planHead th.th-sortable .sort-caret").nth(1).click()

    ok = page.evaluate(
        """(col) => {
            const rows = [...document.querySelectorAll('#planBody tr[data-material]')];
            const cellVal = r => {
                const lt = r.dataset.linetype, mat = r.dataset.material, aux = r.dataset.aux || '';
                const it = Object.values(state.results).flat().find(
                    x => String(x.line_type) === lt && String(x.material_number) === mat && String(x.aux_column || '') === aux);
                return it ? Math.abs(Number((it.values && it.values[col]) || 0)) : 0;
            };
            const vals = rows.map(cellVal);
            let sorted = true;
            for (let i = 1; i < vals.length; i++) if (vals[i] > vals[i-1] + 1e-6) sorted = false;
            return { sorted, n: vals.length };
        }""",
        period,
    )
    assert ok["n"] > 1
    assert ok["sorted"] is True, "loose sort rows not in descending value order"
    assert page.js_errors == []


def test_planning_grouped_sort_orders_material_blocks(browser_page):
    page = browser_page
    period = page.server["expected_periods"][0]
    _open_tab(page, "planning")
    expect(_planning_rows(page).nth(0)).to_be_visible(timeout=60000)

    # Enable the "Groepeer materiaal" option.
    page.evaluate(
        "() => { const cb = document.getElementById('planGroupSort'); cb.checked = true; _togglePlanGroupSort(cb); }"
    )

    # Caret order in the header: [Start, period0, period1, ...]; click period0.
    page.locator("#planHead th.th-sortable .sort-caret").nth(1).click()

    caret = page.locator("#planHead th.th-sortable .sort-caret").nth(1)
    expect(caret).to_have_class(re.compile(r"\bdesc\b"))

    report = page.evaluate(
        """(col) => {
            const rows = [...document.querySelectorAll('#planBody tr[data-material]')];
            const order = []; const seen = new Set();
            for (const r of rows) { const m = r.dataset.material; if (!seen.has(m)) { seen.add(m); order.push(m); } }
            const groups = {};
            Object.values(state.results).flat().forEach(it => {
                const m = String(it.material_number);
                const v = Math.abs(Number((it.values && it.values[col]) || 0));
                groups[m] = Math.max(groups[m] || 0, v);
            });
            const metrics = order.map(m => groups[m] || 0);
            let ok = true;
            for (let i = 1; i < metrics.length; i++) if (metrics[i] > metrics[i-1] + 1e-6) ok = false;
            // material rows must remain contiguous (blocks not split)
            let contiguous = true; const blockSeen = new Set(); let prev = null;
            for (const r of rows) { const m = r.dataset.material;
                if (m !== prev) { if (blockSeen.has(m)) contiguous = false; blockSeen.add(m); prev = m; } }
            return { ok, contiguous, n: metrics.length };
        }""",
        period,
    )
    assert report["n"] > 1
    assert report["contiguous"] is True
    assert report["ok"] is True, "material blocks not in descending metric order"

    # Second click -> ascending.
    caret.click()
    expect(caret).to_have_class(re.compile(r"\basc\b"))
    asc = page.evaluate(
        """(col) => {
            const rows = [...document.querySelectorAll('#planBody tr[data-material]')];
            const order = []; const seen = new Set();
            for (const r of rows) { const m = r.dataset.material; if (!seen.has(m)) { seen.add(m); order.push(m); } }
            const groups = {};
            Object.values(state.results).flat().forEach(it => {
                const m = String(it.material_number);
                const v = Math.abs(Number((it.values && it.values[col]) || 0));
                groups[m] = Math.max(groups[m] || 0, v);
            });
            const metrics = order.map(m => groups[m] || 0);
            let ok = true;
            for (let i = 1; i < metrics.length; i++) if (metrics[i] + 1e-6 < metrics[i-1]) ok = false;
            return ok;
        }""",
        period,
    )
    assert asc is True, "ascending sort not in non-decreasing metric order"

    # Third click -> back to default (caret no longer active).
    caret.click()
    expect(caret).not_to_have_class(re.compile(r"\bactive\b"))
    assert page.js_errors == []


def test_planning_sort_respects_line_type_filter(browser_page):
    # The intended workflow: filter to a single line type, then sort by a column.
    # The block ranking must then use only that line type's values (not the
    # material's largest line, which would otherwise be inventory/Line 04).
    page = browser_page
    period = page.server["expected_periods"][0]
    lt = "01. Demand forecast"
    _open_tab(page, "planning")
    expect(_planning_rows(page).nth(0)).to_be_visible(timeout=60000)

    # Select only the demand line type via the line-type filter.
    page.evaluate(
        """(lt) => {
            document.querySelectorAll('.lt-cb-ltDropdown').forEach(cb => { cb.checked = (cb.value === lt); });
            onLtCbChange('ltDropdown', 'ltFilterLabel', 'plan');
        }""",
        lt,
    )
    # Sort descending by the first period column.
    page.locator("#planHead th.th-sortable .sort-caret").nth(1).click()

    ok = page.evaluate(
        """([col, lt]) => {
            const rows = [...document.querySelectorAll('#planBody tr[data-material]')]
                .filter(r => r.style.display !== 'none' && r.dataset.linetype === lt);
            const lookup = {};
            Object.values(state.results).flat().forEach(it => {
                if (String(it.line_type) === lt) lookup[String(it.material_number)] = Math.abs(Number((it.values && it.values[col]) || 0));
            });
            const vals = rows.map(r => lookup[r.dataset.material] || 0);
            let sorted = true;
            for (let i = 1; i < vals.length; i++) if (vals[i] > vals[i-1] + 1e-6) sorted = false;
            return { sorted, n: vals.length };
        }""",
        [period, lt],
    )
    assert ok["n"] > 1
    assert ok["sorted"] is True, "demand rows not sorted by demand value under line-type filter"
    assert page.js_errors == []


def test_values_planning_sort_keeps_consolidated_rows_at_bottom(browser_page):
    page = browser_page
    period = page.server["expected_periods"][0]
    _open_tab(page, "values")
    expect(page.locator("#vpBody tr[data-material]").nth(0)).to_be_visible(timeout=60000)

    page.locator("#vpHead th.th-sortable .sort-caret").nth(1).click()

    report = page.evaluate(
        """(col) => {
            const rows = [...document.querySelectorAll('#vpBody tr[data-material]')];
            const isConsol = r => (r.dataset.material || '').startsWith('ZZZZZZ_');
            // consolidated rows must form a contiguous block at the very bottom
            let firstConsol = rows.findIndex(isConsol);
            let consolAtBottom = true;
            if (firstConsol !== -1) {
                for (let i = firstConsol; i < rows.length; i++) if (!isConsol(rows[i])) consolAtBottom = false;
            }
            // non-consolidated rows sorted descending by |value in col|
            const vals = rows.filter(r => !isConsol(r)).map(r => {
                const lt = r.dataset.linetype, mat = r.dataset.material;
                const it = Object.values(state.valueResults).flat().find(
                    x => String(x.line_type) === lt && String(x.material_number) === mat);
                return it ? Math.abs(Number((it.values && it.values[col]) || 0)) : 0;
            });
            let sorted = true;
            for (let i = 1; i < vals.length; i++) if (vals[i] > vals[i-1] + 1e-6) sorted = false;
            return { consolAtBottom, sorted, n: vals.length };
        }""",
        period,
    )
    assert report["n"] > 1
    assert report["consolAtBottom"] is True
    assert report["sorted"] is True, "VP rows not in descending value order"
    assert page.js_errors == []
