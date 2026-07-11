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


def test_direct_throughput_records_delta_summary(browser_page):
    """The throughput change must appear in the machine delta summary panel."""
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_capacity(page)

    setup = page.evaluate(
        """async () => {
            await loadMachinesData();
            const m = (_machinesData.machines || []).find(x => x.throughput_effective > 0);
            if (!m) return null;
            openMachineDrilldown(m.code);
            return { code: m.code, eff: m.throughput_effective };
        }"""
    )
    assert setup is not None

    page.fill("#drillThroughputInput", str(round(setup["eff"] * 1.2, 4)))
    with page.expect_response(lambda r: "/api/machines/update" in r.url and r.ok):
        page.click("#machineDrillBody button:has-text('Toepassen')")
    page.wait_for_load_state("networkidle")
    page.wait_for_function("() => state.machineDeltaSummary !== null", timeout=15000)

    # A machine delta summary was built for this session.
    dbg = page.evaluate(
        """(code) => {
            const s = state.machineDeltaSummary;
            return {
                isNull: !s,
                directCount: s ? (s.directChanges || []).length : 0,
                includesCode: s ? JSON.stringify(s).includes(code) : false,
            };
        }""",
        setup["code"],
    )
    assert not dbg["isNull"], dbg
    assert dbg["includesCode"], dbg


def test_inline_effective_throughput_edit_scales_oee(browser_page):
    """The 'Doorzet (eff)' cell is editable directly in the machines table and
    routes through the same OEE inversion."""
    import requests
    try:
        requests.post(browser_page.server["base_url"] + "/api/reset_edits", timeout=60)
    except requests.RequestException:
        pass
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_capacity(page)

    setup = page.evaluate(
        """async () => {
            await loadMachinesData();
            if (typeof renderOeeTable === 'function') renderOeeTable();
            document.querySelectorAll('[id$="-arrow"]').forEach(a =>
                toggleOeeGroup(a.id.replace('-arrow','')));
            const m = (_machinesData.machines || []).find(x => x.throughput_effective > 0);
            if (!m) return null;
            // Enable machine edit mode so cells are editable.
            if (!_machineEditMode) toggleMachineEditMode();
            return { code: m.code, oee: m.oee, eff: m.throughput_effective };
        }"""
    )
    assert setup is not None

    target = round(setup["eff"] * 1.25, 4)
    # Drive the throughput cell's commit directly (activation sets _orig).
    with page.expect_response(lambda r: "/api/machines/update" in r.url and r.ok):
        page.evaluate(
            """(args) => {
                const td = document.querySelector(
                    `#oeeTableBody td.mach-edit[data-field="throughput_eff"][data-mc="${args.code}"]`);
                td.dataset._orig = td.dataset.editValue;
                td.textContent = String(args.t);
                saveMachineEdit(td);
            }""",
            {"t": target, "code": setup["code"]},
        )
    page.wait_for_load_state("networkidle")
    expected_oee = min(1.5, setup["oee"] * 1.25)
    page.wait_for_function(
        """(a) => {
            const m = (_machinesData && _machinesData.machines || []).find(x => String(x.code) === String(a.code));
            return m && Math.abs(m.oee - a.exp) < 0.02;
        }""",
        arg={"code": setup["code"], "exp": expected_oee},
        timeout=15000,
    )

    after = page.evaluate(
        """(code) => {
            const m = (_machinesData.machines || []).find(x => String(x.code) === String(code));
            return m ? { oee: m.oee, eff: m.throughput_effective } : null;
        }""",
        setup["code"],
    )
    assert abs(after["oee"] - expected_oee) < max(0.02, expected_oee * 0.05), (setup, after)
    assert after["eff"] > setup["eff"], (setup, after)
    assert page.js_errors == []


def test_direct_throughput_above_ceiling_warns_not_errors(browser_page):
    """A target requiring OEE > 1.5 must warn with the max achievable target,
    not fire a request that 400s."""
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_capacity(page)

    setup = page.evaluate(
        """async () => {
            await loadMachinesData();
            const m = (_machinesData.machines || []).find(x => x.throughput_effective > 0);
            if (!m) return null;
            openMachineDrilldown(m.code);
            return { code: m.code, eff: m.throughput_effective, oee: m.oee };
        }"""
    )
    assert setup is not None

    # Target far above the OEE=1.5 ceiling.
    huge = round(setup["eff"] * (2.0 / setup["oee"]) + 100, 2)
    fired = {"n": 0}
    page.on("request", lambda r: fired.__setitem__("n", fired["n"] + 1)
            if "/api/machines/update" in r.url else None)
    page.fill("#drillThroughputInput", str(huge))
    page.click("#machineDrillBody button:has-text('Toepassen')")
    page.wait_for_timeout(500)
    assert fired["n"] == 0, "must not POST an unreachable target"
    assert page.js_errors == []
