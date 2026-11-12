"""Front-end fixes from the 2026-11 re-check of the bug register.

Run on the shared server: none of these tests changes server state.
"""

from playwright.sync_api import expect


def test_log_shows_markup_as_text(browser_page):
    """BUGS.md H12. Log lines carry workbook and user strings (material
    numbers, file and scenario names, server errors); they must never be
    parsed as markup."""
    page = browser_page

    result = page.evaluate(
        """() => {
            log('<b id="logMarkupProbe">vet</b> & <img src=x onerror="window.__logProbeRan = true">');
            return {
                parsed: !!document.getElementById('logMarkupProbe'),
                ran: !!window.__logProbeRan,
                text: document.getElementById('log').textContent,
            };
        }""")

    assert result["parsed"] is False
    assert result["ran"] is False
    assert '<b id="logMarkupProbe">vet</b> & <img' in result["text"]
    assert page.js_errors == []


def test_ctrl_z_while_typing_is_left_to_the_field(browser_page):
    """BUGS.md M25. Ctrl+Z / Ctrl+Y in a text field are that field's own
    undo; they used to revert the last plan edit on the server instead."""
    page = browser_page
    page.evaluate(
        """() => {
            window.__shortcutCalls = [];
            window.undoEdit = () => window.__shortcutCalls.push('undo');
            window.redoEdit = () => window.__shortcutCalls.push('redo');
            window.undoMachineEdit = () => window.__shortcutCalls.push('machine-undo');
            window.redoMachineEdit = () => window.__shortcutCalls.push('machine-redo');
            const probe = document.createElement('input');
            probe.id = 'shortcutProbe';
            document.body.appendChild(probe);
        }""")

    page.focus("#shortcutProbe")
    page.keyboard.type("abc")
    page.keyboard.press("Control+z")
    page.keyboard.press("Control+y")
    assert page.evaluate("() => window.__shortcutCalls") == []

    page.evaluate("() => document.getElementById('shortcutProbe').blur()")
    page.keyboard.press("Control+z")
    page.keyboard.press("Control+y")
    calls = page.evaluate("() => window.__shortcutCalls")
    assert len(calls) == 2 and "undo" in calls[0] and "redo" in calls[1], calls
    assert page.js_errors == []


def test_upload_no_longer_offers_xls(browser_page):
    """BUGS.md L21. `.xls` was accepted by the drop zone and the file
    pickers, then refused at upload with a contradicting message."""
    page = browser_page

    accepts = page.evaluate(
        "() => [...document.querySelectorAll('input[type=file]')].map(i => i.accept)")

    assert accepts, "geen bestandsvelden gevonden"
    for accept in accepts:
        assert ".xls" not in [part.strip() for part in accept.split(",")], accepts
    expect(page.locator("#multiAutoFileInput")).to_have_attribute("accept", ".xlsx,.xlsm")
