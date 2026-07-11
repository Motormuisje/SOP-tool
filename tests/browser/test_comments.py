"""Fase 2.1 — comment popover flow, driven against the live server."""

from playwright.sync_api import expect


def _open_planning(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.evaluate("() => window.showTab && window.showTab('planning')")
    expect(page.locator("#planning-tab")).to_be_visible()


def test_add_comment_marks_cell_and_persists(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_planning(page)
    expect(page.locator('#planBody td[data-period]').first).to_be_visible(timeout=60000)

    # Seed a comment user so the popover flow does not prompt.
    page.evaluate("() => localStorage.setItem('sop_comment_user', 'tester')")

    # Open the popover programmatically for the first demand-forecast cell.
    anchor = page.evaluate(
        """() => {
            const tr = document.querySelector('#planBody tr[data-linetype="01. Demand forecast"][data-material]');
            if (!tr) return null;
            const cell = tr.querySelector('td[data-period]');
            openCommentPopover({ scope: tr.dataset.linetype, target: tr.dataset.material,
                                 period: cell.dataset.period, cell });
            return { mat: tr.dataset.material, period: cell.dataset.period };
        }"""
    )
    assert anchor is not None
    expect(page.locator("#commentPopover")).to_be_visible()

    page.fill("#commentPopoverText", "Afstemmen met sales")
    with page.expect_response(lambda r: r.url.endswith("/api/comments") and r.request.method == "POST" and r.ok):
        page.click("#commentPopover button:has-text('Opslaan')")

    # Marker appears and the comment is in state + server.
    has_marker = page.evaluate(
        """(a) => {
            const tr = document.querySelector(`#planBody tr[data-material="${a.mat}"][data-linetype="01. Demand forecast"]`);
            const cell = tr && tr.querySelector(`td[data-period="${a.period}"]`);
            return cell ? cell.classList.contains('has-comment') : false;
        }""",
        anchor,
    )
    assert has_marker

    server_comments = page.evaluate("async () => (await (await fetch('/api/comments')).json()).comments")
    key = f"01. Demand forecast||{anchor['mat']}||{anchor['period']}"
    assert key in server_comments
    assert server_comments[key]["text"] == "Afstemmen met sales"
    assert server_comments[key]["user"] == "tester"

    # Delete it again.
    page.evaluate(
        """(a) => { const tr = document.querySelector(`#planBody tr[data-material="${a.mat}"][data-linetype="01. Demand forecast"]`);
                     const cell = tr.querySelector(`td[data-period="${a.period}"]`);
                     openCommentPopover({ scope: '01. Demand forecast', target: a.mat, period: a.period, cell }); }""",
        anchor,
    )
    with page.expect_response(lambda r: "/api/comments/delete" in r.url and r.ok):
        page.click("#commentPopover button:has-text('Verwijderen')")
    remaining = page.evaluate("async () => (await (await fetch('/api/comments')).json()).comments")
    assert key not in remaining
