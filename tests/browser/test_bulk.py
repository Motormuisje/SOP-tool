"""Fase 1.2 — bulk edit UI wiring, driven against the live server.

Selection is stored programmatically (drag emulation is flaky headless), then
the real applyBulkEdit() path posts to /api/update_volume_bulk. This exercises
_getSelectedEditableCells + applyBulkEdit + grouped undo end to end.
"""

import requests
from playwright.sync_api import expect


def _drain(base_url):
    # Reset to the clean baseline first (the browser tests share one
    # session-scoped server, so prior tests may have left edits), then drain
    # any remaining volume undo history.
    try:
        requests.post(base_url + "/api/reset_edits", timeout=60)
    except requests.RequestException:
        pass
    for _ in range(50):
        r = requests.post(base_url + "/api/undo", timeout=10)
        if not r.ok or not r.json().get("success"):
            break


def _open_planning(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.evaluate("() => window.showTab && window.showTab('planning')")
    expect(page.locator("#planning-tab")).to_be_visible()


def test_bulk_selection_excludes_percent_scale_lines(browser_page):
    """F1 regression: L09/L10 cells carry percent-scaled data-raw while the
    server stores fractions; bulk must never include them."""
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_planning(page)
    expect(page.locator('#planBody td[data-period]').first).to_be_visible(timeout=60000)

    info = page.evaluate(
        """() => {
            const rows = Array.from(document.querySelectorAll('#planBody tr'));
            const l9 = rows.findIndex(r => r.dataset.linetype === '09. Available capacity');
            if (l9 < 0) return { skipped: true };
            // Select the whole L9 row plus one row above and below it.
            const sel = {
                sheet: 'planning',
                rowMin: Math.max(0, l9 - 1), rowMax: Math.min(rows.length - 1, l9 + 1),
                colMin: 0, colMax: rows[l9].cells.length - 1,
            };
            _storedSelections = [sel];
            const found = _getSelectedEditableCells();
            return {
                skipped: false,
                total: found.length,
                l9count: found.filter(f => f.line_type === '09. Available capacity'
                                        || f.line_type === '10. Utilization rate').length,
            };
        }"""
    )
    if info.get("skipped"):
        import pytest
        pytest.skip("no L09 row rendered in this fixture")
    assert info["l9count"] == 0, info


def test_bulk_edit_applies_delta_to_selection_and_group_undo(browser_page):
    page = browser_page
    _drain(page.server["base_url"])
    page.reload(wait_until="networkidle")
    _open_planning(page)
    expect(page.locator('#planBody td.editable-cell[data-lt="01. Demand forecast"][data-period]').first).to_be_visible(timeout=60000)

    # Select 3 adjacent period cells within ONE demand-forecast row, so the
    # rectangular selection contains exactly those 3 L01 cells (no intervening
    # line-type rows, no lot-size rounding).
    info = page.evaluate(
        """() => {
            const rows = Array.from(document.querySelectorAll('#planBody tr'));
            let rowIdx = -1, cells = null;
            for (let i = 0; i < rows.length; i++) {
                if (rows[i].dataset.linetype === '01. Demand forecast') {
                    const cs = Array.from(rows[i].querySelectorAll('td.editable-cell[data-period]'));
                    if (cs.length >= 3) { rowIdx = i; cells = cs.slice(0, 3); break; }
                }
            }
            if (rowIdx < 0) return null;
            const colIdxs = cells.map(c => c.cellIndex);
            const sel = {
                sheet: 'planning',
                rowMin: rowIdx, rowMax: rowIdx,
                colMin: Math.min(...colIdxs), colMax: Math.max(...colIdxs),
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
    assert info is not None, "no demand row with 3 editable period cells"
    assert info["count"] == 3, info["count"]

    expect(page.locator("#bulkEditBar")).to_be_visible()

    # Read authoritative values from the server (client state refresh is
    # coupled to chart rendering, which is unavailable in this test env).
    read_js = """async (keys) => {
        const data = await (await fetch('/api/results')).json();
        const out = {};
        for (const lt of Object.keys(data.results)) {
            for (const row of data.results[lt]) {
                for (const p of Object.keys(row.values || {})) {
                    out[`${lt}||${row.material_number}||${p}`] = row.values[p];
                }
            }
        }
        return keys.map(k => out[k]);
    }"""

    page.fill("#bulkVal", "250")
    page.select_option("#bulkOp", "delta")
    with page.expect_response(lambda r: "/api/update_volume_bulk" in r.url and r.ok):
        page.click("#bulkEditBar button")
    page.wait_for_load_state("networkidle")

    after = page.evaluate(read_js, info["keys"])
    for before, now in zip(info["raws"], after):
        assert abs(now - (before + 250.0)) < 1e-3, (before, now)

    # Grouped undo reverts all three in one step (one #undoBtn click).
    with page.expect_response(lambda r: "/api/undo" in r.url and r.ok):
        page.click("#undoBtn")
    page.wait_for_load_state("networkidle")
    reverted = page.evaluate(read_js, info["keys"])
    for before, now in zip(info["raws"], reverted):
        assert abs(now - before) < 1e-3, (before, now)

    _drain(page.server["base_url"])
