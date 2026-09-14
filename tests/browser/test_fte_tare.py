"""Wijzigingslog en tarra in het waardepaneel van de werkbank.

Elke bewerking laat een regel na met haar effect op FTE en loonkosten (en
EBITDA/EBIT als de waardeketen beschikbaar is), over de hele horizon; het
totaal is altijd huidige stand − tarra. "Tarra" zet het nulpunt en leegt de
lijst. Bereikwissels zijn geen bewerking.
"""

from playwright.sync_api import expect


def _open_workbench(page):
    page.reload(wait_until="networkidle")
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    with page.expect_response(lambda r: "/api/fte" in r.url and r.ok):
        page.evaluate("() => window.showTab && window.showTab('fte')")
    page.wait_for_function(
        "() => document.querySelectorAll('#fteWbBody tr').length > 0", timeout=30000)


def _reset_norms(page):
    if page.evaluate("() => Object.keys(_fteState.overrides).length"):
        with page.expect_response(lambda r: "/api/fte/norm_overrides" in r.url and r.ok):
            page.evaluate("() => revertFteNorms()")
        page.wait_for_function("() => Object.keys(_fteState.overrides).length === 0", timeout=15000)


def _log(page):
    return page.evaluate(
        """() => ({ entries: _fteLog.entries.map(e => ({ label: e.label, dFte: e.after.fte - e.before.fte })),
                   rows: document.querySelectorAll('#fteValueDelta tr[data-fte-log-entry]').length,
                   total: document.querySelector('#fteValueDelta tr[data-fte-log-total]')?.textContent.trim(),
                   tare: _fteLog.tare && _fteLog.tare.fte,
                   now: _fteSnapshot().fte })""")


def test_edits_are_logged_with_their_effect_and_tare_resets(browser_page):
    page = browser_page
    _open_workbench(page)
    _reset_norms(page)
    page.evaluate("() => fteTare()")
    page.wait_for_function("() => _fteLog.entries.length === 0 && !!_fteLog.tare", timeout=5000)
    assert "Nog geen bewerkingen" in page.locator("#fteValueDelta").inner_text()

    # Een normwijziging in de tabel → één regel met etiket en FTE-effect.
    target = page.evaluate(
        """() => { const input = document.querySelector('#fteWbBody input[data-fte-key]');
                   const row = input.closest('tr');
                   return { value: input.value, rowId: row.dataset.fteRow, key: input.dataset.fteKey }; }""")
    base_total = page.evaluate("() => _fteSnapshot().fte")
    doubled = str(float(target["value"].replace(",", ".")) * 2).replace(".", ",")
    with page.expect_response(lambda r: "/api/fte/norm_overrides" in r.url and r.ok):
        page.evaluate(
            """([val]) => { const input = document.querySelector('#fteWbBody input[data-fte-key]');
                          input.value = val; input.dispatchEvent(new Event('change', { bubbles: true })); }""", [doubled])
    page.wait_for_function("() => _fteLog.entries.length === 1", timeout=15000)
    log = _log(page)
    assert log["entries"][0]["label"].startswith("Norm "), log
    assert log["rows"] == 1
    assert log["entries"][0]["dFte"] == page.evaluate("() => _fteSnapshot().fte") - base_total
    assert log["now"] - log["tare"] == log["entries"][0]["dFte"]

    # Bereik wisselen is geen bewerking.
    page.evaluate("() => setFteRange('next3')")
    page.wait_for_timeout(300)
    assert page.evaluate("() => _fteLog.entries.length") == 1
    page.evaluate("() => setFteRange('all')")

    # Terugzetten → tweede regel; totaal sinds tarra ≈ 0.
    with page.expect_response(lambda r: "/api/fte/norm_overrides" in r.url and r.ok):
        page.evaluate("() => revertFteNorms()")
    page.wait_for_function("() => _fteLog.entries.length === 2", timeout=15000)
    log = _log(page)
    assert log["entries"][1]["label"] == "Wat-als normen teruggezet"
    assert abs(log["now"] - log["tare"]) < 1e-6
    assert "≈ 0" in log["total"]

    # Tarra: nulpunt opnieuw, lijst leeg; het nulpunt overleeft een herlaad.
    page.click("#fteValueDelta button:has-text('Tarra')")
    page.wait_for_function("() => _fteLog.entries.length === 0", timeout=5000)
    tare_at = page.evaluate("() => _fteLog.tare.at")
    _open_workbench(page)
    assert page.evaluate("() => _fteLog.tare.at") == tare_at
    assert page.evaluate("() => _fteLog.entries.length") == 0
    assert page.js_errors == []


def test_log_shows_at_most_five_entries_but_totals_them_all(browser_page):
    page = browser_page
    _open_workbench(page)
    _reset_norms(page)
    page.evaluate("() => fteTare()")
    page.wait_for_function("() => _fteLog.entries.length === 0", timeout=5000)
    base = page.evaluate("() => document.querySelector('#fteWbBody input[data-fte-key]').value").replace(",", ".")
    for i in range(6):
        val = str(float(base) + 0.5 * (i + 1)).replace(".", ",")
        with page.expect_response(lambda r: "/api/fte/norm_overrides" in r.url and r.ok):
            page.evaluate(
                """([val]) => { const input = document.querySelector('#fteWbBody input[data-fte-key]');
                              input.value = val; input.dispatchEvent(new Event('change', { bubbles: true })); }""", [val])
        page.wait_for_function("(n) => _fteLog.entries.length === n", arg=i + 1, timeout=15000)
    log = _log(page)
    assert log["rows"] == 5, log
    assert "(6 bewerkingen)" in log["total"], log["total"]
    assert abs(sum(e["dFte"] for e in log["entries"]) - (log["now"] - log["tare"])) < 1e-6
    _reset_norms(page)
    page.evaluate("() => fteTare()")
    assert page.js_errors == []
