"""Fase 2.4 — financial deviation modal + drilldown, live server."""

from playwright.sync_api import expect


def test_financial_deviation_modal_and_drill(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.evaluate("() => window.showTab && window.showTab('dashboard')")

    page.evaluate("() => openFinancialDeviation()")
    modal = page.locator("#finDevModal")
    expect(modal).to_be_visible()

    # TURNOVER row is drillable (has a source line type).
    page.wait_for_function(
        "() => document.querySelectorAll('#finDevBody table tbody tr').length > 0",
        timeout=30000,
    )
    has_turnover = page.evaluate(
        """() => Array.from(document.querySelectorAll('#finDevBody tbody tr td'))
                   .some(td => /TURNOVER/.test(td.textContent))"""
    )
    assert has_turnover

    # Drill into TURNOVER -> contributors table appears.
    with page.expect_response(lambda r: "/api/financial_metrics/drill" in r.url and r.ok):
        page.evaluate("() => drillFinancialMetric('TURNOVER')")
    page.wait_for_function(
        "() => document.querySelectorAll('#finDrillHost table tbody tr').length > 0",
        timeout=30000,
    )

    page.keyboard.press("Escape")
    expect(modal).to_be_hidden()
    assert page.js_errors == []
