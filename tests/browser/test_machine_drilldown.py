"""Fase 2.2 — machine drilldown modal, driven against the live server."""

from playwright.sync_api import expect


def _open_capacity(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.evaluate("() => window.showTab && window.showTab('capacity')")


def test_machine_drilldown_shows_per_period_detail(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_capacity(page)

    # Load machine data explicitly (lexical binding, not window-scoped), then
    # open the drilldown for the first machine.
    info = page.evaluate(
        """async () => {
            await loadMachinesData();
            const m = _machinesData.machines[0];
            openMachineDrilldown(m.code);
            return { code: m.code, nPeriods: (_machinesData.periods || []).length,
                     hasOutput: !!m.output_by_period, hasCap: !!m.capacity_hours_by_period };
        }"""
    )
    assert info["hasOutput"] and info["hasCap"], "backend must expose output + capacity per period"

    modal = page.locator("#machineDrillModal")
    expect(modal).to_be_visible()
    expect(page.locator("#machineDrillTitle")).to_contain_text(info["code"])
    # Metric rows rendered (6 metrics) with a column per period.
    rows = page.locator("#machineDrillBody table tbody tr")
    expect(rows).to_have_count(6)

    page.keyboard.press("Escape")
    expect(modal).to_be_hidden()
    assert page.js_errors == []
