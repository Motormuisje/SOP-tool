"""Fase 1.2 — bulk edit UI wiring, driven against the live server.

Selection is stored programmatically (drag emulation is flaky headless), then
the real applyBulkEdit() path posts to /api/update_volume_bulk. This exercises
_getSelectedEditableCells + applyBulkEdit + grouped undo end to end.
"""

import requests
from playwright.sync_api import expect


def _drain(base_url):
    for _ in range(50):
        r = requests.post(base_url + "/api/undo", timeout=10)
        if not r.ok or not r.json().get("success"):
            break


def _open_planning(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.evaluate("() => window.showTab && window.showTab('planning')")
    expect(page.locator("#planning-tab")).to_be_visible()


def test_bulk_edit_applies_delta_to_selection_and_group_undo(browser_page):
    page = browser_page
    _drain(page.server["base_url"])
    page.reload(wait_until="networkidle")
    _open_planning(page)
    expect(page.locator('#planBody td.editable-cell[data-lt="01. Demand forecast"][data-period]').first).to_be_visible(timeout=60000)

    # Pick 3 demand-forecast cells in one column, store a selection covering
    # them, and read their pre-edit raw values.
    info = page.evaluate(
        """() => {
            const cells = Array.from(document.querySelectorAll(
                '#planBody td.editable-cell[data-lt="01. Demand forecast"][data-period]'));
            // group by column, take a column with >=3 cells
            const byCol = {};
            for (const c of cells) { (byCol[c.cellIndex] = byCol[c.cellIndex] || []).push(c); }
            let col = null;
            for (const k of Object.keys(byCol)) { if (byCol[k].length >= 3) { col = k; break; } }
            if (col === null) return null;
            const chosen = byCol[col].slice(0, 3);
            const rows = Array.from(document.querySelectorAll('#planBody tr'));
            const rowIdx = chosen.map(c => rows.indexOf(c.closest('tr')));
            const sel = {
                sheet: 'planning',
                rowMin: Math.min(...rowIdx), rowMax: Math.max(...rowIdx),
                colMin: Number(col), colMax: Number(col),
            };
            _storedSelections = [sel];
            _renderStoredSelections();
            const found = _getSelectedEditableCells();
            return {
                count: found.length,
                raws: found.map(f => f.raw),
                keys: found.map(f => `${f.line_type}||${f.material_number}||${f.period}`),
            };
        }"""
    )
    assert info is not None, "no column with 3 demand cells"
    assert info["count"] >= 3

    expect(page.locator("#bulkEditBar")).to_be_visible()

    page.fill("#bulkVal", "250")
    page.select_option("#bulkOp", "delta")
    with page.expect_response(lambda r: "/api/update_volume_bulk" in r.url and r.ok):
        page.click("#bulkEditBar button")
    page.wait_for_load_state("networkidle")

    # Verify each selected cell increased by 250 in the engine results.
    after = page.evaluate(
        """(keys) => {
            const out = {};
            for (const lt of Object.keys(state.results)) {
                for (const row of state.results[lt]) {
                    for (const p of Object.keys(row.values || {})) {
                        const k = `${lt}||${row.material_number}||${p}`;
                        out[k] = row.values[p];
                    }
                }
            }
            return keys.map(k => out[k]);
        }""",
        info["keys"],
    )
    for before, now in zip(info["raws"], after):
        assert abs((now) - (before + 250.0)) < 1e-3

    # Grouped undo reverts all three in one step.
    with page.expect_response(lambda r: "/api/undo" in r.url and r.ok):
        page.click("#undoBtn")
    page.wait_for_load_state("networkidle")
    reverted = page.evaluate(
        """(keys) => {
            const out = {};
            for (const lt of Object.keys(state.results)) {
                for (const row of state.results[lt]) {
                    for (const p of Object.keys(row.values || {})) {
                        const k = `${lt}||${row.material_number}||${p}`;
                        out[k] = row.values[p];
                    }
                }
            }
            return keys.map(k => out[k]);
        }""",
        info["keys"],
    )
    for before, now in zip(info["raws"], reverted):
        assert abs(now - before) < 1e-3

    _drain(page.server["base_url"])
