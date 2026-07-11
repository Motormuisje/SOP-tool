"""Bulk range selection through the REAL mousedown/mouseover/mouseup handlers,
horizontal (row) and vertical (column). Uses dispatched MouseEvents rather
than synthesized pointer motion so the test exercises the handler chain
deterministically in headless."""

from playwright.sync_api import expect


def _open_planning(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.evaluate("() => window.showTab && window.showTab('planning')")
    expect(page.locator("#planning-tab")).to_be_visible()


_DRAG_JS = """(sel) => {
    _storedSelections = []; _renderStoredSelections();
    const rows = Array.from(document.querySelectorAll('#planBody tr[data-linetype="01. Demand forecast"]'));
    const anchor = document.querySelector(sel.anchor);
    const focus = document.querySelector(sel.focus);
    if (!anchor || !focus) return { ok: false };
    const fire = (el, type) => el.dispatchEvent(new MouseEvent(type, { bubbles: true, button: 0, cancelable: true }));
    fire(anchor, 'mousedown');
    const dragging = document.body.classList.contains('range-selecting');
    fire(focus, 'mouseover');
    document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    const found = _getSelectedEditableCells();
    return {
        ok: true,
        draggingClassDuringDrag: dragging,
        classCleared: !document.body.classList.contains('range-selecting'),
        selections: _storedSelections.length,
        cells: found.length,
        lineTypes: [...new Set(found.map(f => f.line_type))],
        barVisible: document.getElementById('bulkEditBar').style.display !== 'none',
    };
}"""


def test_horizontal_row_drag_selects_period_cells(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_planning(page)
    page.wait_for_selector('#planBody tr[data-linetype="01. Demand forecast"] td.editable-cell[data-period]', timeout=60000)

    prep = page.evaluate(
        """() => {
            const row = document.querySelector('#planBody tr[data-linetype="01. Demand forecast"]');
            const cells = Array.from(row.querySelectorAll('td.editable-cell[data-period]'));
            if (cells.length < 3) return false;
            cells[0].setAttribute('data-drag-a', '1');
            cells[2].setAttribute('data-drag-b', '1');
            return true;
        }"""
    )
    assert prep, "need a demand row with 3 editable period cells"
    res = page.evaluate(_DRAG_JS, {"anchor": '[data-drag-a="1"]', "focus": '[data-drag-b="1"]'})
    # A row of demand cells: at least 3 editable cells, all L01, bar shown.
    assert res["ok"], res
    assert res["draggingClassDuringDrag"], res
    assert res["classCleared"], res
    assert res["cells"] >= 3, res
    assert res["lineTypes"] == ["01. Demand forecast"], res
    assert res["barVisible"], res


def test_vertical_column_drag_still_selects(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_planning(page)
    page.wait_for_selector('#planBody tr[data-linetype="01. Demand forecast"] td.editable-cell[data-period]', timeout=60000)

    # Anchor = first demand row's first period cell; focus = a lower demand
    # row's cell in the same period column.
    prep = page.evaluate(
        """() => {
            const rows = Array.from(document.querySelectorAll('#planBody tr[data-linetype="01. Demand forecast"]'));
            if (rows.length < 3) return null;
            const a = rows[0].querySelector('td.editable-cell[data-period]');
            const period = a.dataset.period;
            const b = rows[2].querySelector(`td.editable-cell[data-period="${period}"]`);
            a.setAttribute('data-drag-a', '1'); if (b) b.setAttribute('data-drag-b', '1');
            return !!b;
        }"""
    )
    assert prep, "need 3 demand rows sharing a period column"
    res = page.evaluate(_DRAG_JS, {"anchor": '[data-drag-a="1"]', "focus": '[data-drag-b="1"]'})
    assert res["cells"] >= 3, res
    assert res["barVisible"], res
