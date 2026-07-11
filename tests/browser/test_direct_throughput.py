"""Fase 2.3 — direct effective-throughput control (via OEE inversion)."""

from playwright.sync_api import expect


def _open_capacity(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.evaluate("() => window.showTab && window.showTab('capacity')")


def test_direct_throughput_scales_oee_and_moves_effective(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_capacity(page)

    # Find a machine with non-zero effective throughput so scaling is defined.
    setup = page.evaluate(
        """async () => {
            await loadMachinesData();
            const m = (_machinesData.machines || []).find(x => x.throughput_effective > 0);
            if (!m) return null;
            openMachineDrilldown(m.code);
            return { code: m.code, oee: m.oee, eff: m.throughput_effective };
        }"""
    )
    assert setup is not None, "no machine with positive effective throughput"

    # Target 50% higher throughput -> OEE should scale ~1.5x (clamped at 2.0).
    target = round(setup["eff"] * 1.5, 4)
    page.fill("#drillThroughputInput", str(target))
    page.click("#machineDrillBody button:has-text('Toepassen')")

    # Wait until the reloaded machine data reflects the raised OEE.
    page.wait_for_function(
        """(code) => {
            const m = (_machinesData && _machinesData.machines || []).find(x => String(x.code) === String(code));
            return m && m.oee > 0.75;
        }""",
        arg=setup["code"],
        timeout=30000,
    )
    after = page.evaluate(
        """(code) => {
            const m = (_machinesData.machines || []).find(x => String(x.code) === String(code));
            return m ? { oee: m.oee, eff: m.throughput_effective } : null;
        }""",
        setup["code"],
    )
    # Backend caps OEE at 1.5; the frontend clamp is 2.0. Expected reflects both.
    expected_oee = min(1.5, setup["oee"] * 1.5)
    # OEE moved proportionally (allow rounding + clamp).
    assert abs(after["oee"] - expected_oee) < max(0.02, expected_oee * 0.05), (
        f"setup={setup} after={after} expected_oee={expected_oee}")
    # Effective throughput moved upward toward the target.
    assert after["eff"] > setup["eff"], f"setup={setup} after={after}"
    assert page.js_errors == []
