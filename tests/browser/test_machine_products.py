"""'Toon producten' per machine — expandable sub-row on the machines tab.

The volumes-only DATA contract is covered deterministically by the backend
test (tests/test_routes_machine_products.py). This browser test covers the
frontend wiring: the toggle inserts a sub-table with volume-only headers.
"""

import requests
from playwright.sync_api import expect


def _open_capacity(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.evaluate("() => window.showTab && window.showTab('capacity')")


def test_toggle_machine_products_shows_volumes(browser_page):
    page = browser_page
    # Reset to the clean baseline (browser tests share one session-scoped
    # server, so prior tests may have edited volumes/OEE).
    try:
        requests.post(page.server["base_url"] + "/api/reset_edits", timeout=60)
    except requests.RequestException:
        pass
    page.reload(wait_until="networkidle")
    _open_capacity(page)

    code = page.evaluate(
        """async () => {
            await loadMachinesData();
            if (typeof renderOeeTable === 'function') renderOeeTable();
            document.querySelectorAll('[id$="-arrow"]').forEach(a =>
                toggleOeeGroup(a.id.replace('-arrow', '')));
            const m = (_machinesData.machines || []).find(x => x.throughput_effective > 0);
            return m ? m.code : null;
        }"""
    )
    assert code, "no producing machine in fixture"

    # Toggle the products row. A concurrent machine re-render (async fallout of
    # a prior test on the shared server) can wipe the freshly-inserted row
    # mid-fetch, so poll: re-toggle until the sub-table is present and stable.
    page.wait_for_function(
        """(code) => {
            const btn = document.querySelector(`#oeeTableBody button[data-products-btn="${code}"]`);
            if (!btn) return false;
            let row = document.querySelector(`tr[data-products-for="${code}"]`);
            if (!row) { toggleMachineProducts(code, btn); return false; }
            const table = row.querySelector('table');
            return !!(table && table.querySelector('tbody tr'));
        }""",
        arg=code,
        timeout=30000,
    )

    info = page.evaluate(
        """(code) => {
            const row = document.querySelector(`tr[data-products-for="${code}"]`);
            const table = row.querySelector('table');
            return {
                bodyRows: table.querySelectorAll('tbody tr').length,
                headers: Array.from(table.querySelectorAll('thead th')).map(th => th.textContent),
            };
        }""",
        code,
    )
    assert info["bodyRows"] >= 1, info
    assert info["headers"][:3] == ["Materiaal", "Naam", "Totaal"], info
    joined = " ".join(info["headers"])
    for lt_marker in ("Demand forecast", "Production plan", "Utilization"):
        assert lt_marker not in joined, info
    assert page.js_errors == []
