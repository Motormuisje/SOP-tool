"""'Toon producten' per machine — expandable sub-row on the machines tab."""

import requests
from playwright.sync_api import expect


def _open_capacity(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.evaluate("() => window.showTab && window.showTab('capacity')")


def test_toggle_machine_products_shows_volumes(browser_page):
    page = browser_page
    # Reset to the clean baseline (the browser tests share one session-scoped
    # server, so prior tests may have edited volumes/OEE).
    try:
        requests.post(page.server["base_url"] + "/api/reset_edits", timeout=60)
    except requests.RequestException:
        pass
    page.reload(wait_until="networkidle")
    _open_capacity(page)

    # Load + render the machines table, expand every group so machine rows and
    # their "Producten" buttons are visible, and pick a producing machine.
    code = page.evaluate(
        """async () => {
            await loadMachinesData();
            if (typeof renderOeeTable === 'function') renderOeeTable();
            document.querySelectorAll('[id$="-arrow"]').forEach(a => {
                const key = a.id.replace('-arrow', '');
                if (typeof toggleOeeGroup === 'function') toggleOeeGroup(key);
            });
            const m = (_machinesData.machines || []).find(x => x.throughput_effective > 0);
            return m ? m.code : null;
        }"""
    )
    assert code, "no producing machine in fixture"

    opened = page.evaluate(
        """async (code) => {
            // Find the real Producten button in the machine's row.
            const rows = Array.from(document.querySelectorAll('#oeeTableBody tr'));
            let btn = null;
            for (const r of rows) {
                if (!r.innerHTML.includes(code)) continue;
                const b = Array.from(r.querySelectorAll('button')).find(x => /Producten/.test(x.textContent));
                if (b) { btn = b; break; }
            }
            if (!btn) return { ok: false, reason: 'no button' };
            await toggleMachineProducts(code, btn);
            const row = document.querySelector(`tr[data-products-for="${code}"]`);
            if (!row) return { ok: false, reason: 'no detail row' };
            const table = row.querySelector('table');
            return {
                ok: true,
                bodyRows: table ? table.querySelectorAll('tbody tr').length : 0,
                headers: table ? Array.from(table.querySelectorAll('thead th')).map(th => th.textContent) : [],
            };
        }""",
        code,
    )
    assert opened["ok"], opened
    assert opened["bodyRows"] >= 1, opened
    # Volumes only: Material / Naam / Totaal / periods — no line-type columns.
    assert opened["headers"][:3] == ["Materiaal", "Naam", "Totaal"], opened
    joined = " ".join(opened["headers"])
    for lt_marker in ("Demand forecast", "Production plan", "Utilization"):
        assert lt_marker not in joined, opened
    assert page.js_errors == []
