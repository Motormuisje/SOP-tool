"""Materiaalgroepen — browser tests.

Dekt (1) de regressie van de gemelde bug (materiaal-scope gewist door
updateEditBadge/filtergeschiedenis), (2) groep bewaren vanuit de
grafiek-analyse + tabelfilter dat combineert met linetypes, en (3) de
actieve groep die dashboard, values en machines scoopt met banner.
"""

import requests
from playwright.sync_api import expect


def _open_planning(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.evaluate("() => window.showTab && window.showTab('planning')")
    page.wait_for_selector("#planBody tr[data-material]", timeout=60000)


def test_material_scope_survives_badge_refresh_and_lt_filter(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_planning(page)

    mat = page.evaluate(
        """() => {
            const r = document.querySelector('#planBody tr[data-material]');
            pushFilterHistory();
            _editedMaterialScope = new Set([r.dataset.material]);
            filterTable();
            return r.dataset.material;
        }"""
    )
    page.wait_for_function(
        """(mat) => {
            const vis = [...document.querySelectorAll('#planBody tr[data-material]')]
                .filter(r => r.style.display !== 'none');
            return vis.length > 0 && vis.every(r => r.dataset.material === mat);
        }""",
        arg=mat,
        timeout=15000,
    )

    # 1. Badge-refresh met 0 edits mag de scope NIET meer wissen.
    page.evaluate("() => updateEditBadge()")
    assert page.evaluate("() => _editedMaterialScope !== null"), \
        "updateEditBadge() wiste de materiaal-scope (regressie)"

    # 2. Linetype-filter togglen: scope blijft en combineert (AND).
    page.evaluate(
        """() => {
            const cb = document.querySelector('#ltDropdown input[type="checkbox"]');
            if (cb) { cb.click(); }
        }"""
    )
    page.wait_for_timeout(300)  # RAF-filter
    check = page.evaluate(
        """(mat) => {
            const vis = [...document.querySelectorAll('#planBody tr[data-material]')]
                .filter(r => r.style.display !== 'none');
            return {
                scoped: _editedMaterialScope !== null,
                allMatch: vis.every(r => r.dataset.material === mat),
            };
        }""",
        mat,
    )
    assert check["scoped"], "linetype-filter wiste de materiaal-scope"
    assert check["allMatch"], "rijen buiten de scope werden zichtbaar"

    # 3. Filtergeschiedenis "←": de eerste undo draait de LT-wijziging terug
    #    (scope hoort dan nog actief te zijn — hij zit nu in de snapshot);
    #    de tweede undo gaat terug naar vóór de scope.
    page.evaluate("() => undoFilterState()")
    page.wait_for_timeout(300)
    assert page.evaluate("() => _editedMaterialScope !== null"), \
        "eerste undo (LT-wijziging) had de scope moeten behouden"
    page.evaluate("() => undoFilterState()")
    page.wait_for_timeout(300)
    restored = page.evaluate(
        """() => {
            const vis = [...document.querySelectorAll('#planBody tr[data-material]')]
                .filter(r => r.style.display !== 'none');
            const mats = new Set(vis.map(r => r.dataset.material));
            return { scoped: _editedMaterialScope !== null, mats: mats.size };
        }"""
    )
    assert not restored["scoped"], "tweede undo herstelde de scope-loze snapshot niet"
    assert restored["mats"] > 1, "tabel bleef gefilterd na filter-undo"

    # Cleanup voor de gedeelde server: linetype-filter terugzetten.
    page.evaluate(
        """() => {
            _editedMaterialScope = null;
            const all = document.querySelector('#ltDropdown input[type="checkbox"]');
            if (all && !all.checked) all.click();
            filterTable();
        }"""
    )
    assert page.js_errors == []


def _delete_all_groups(base_url):
    body = requests.get(base_url + "/api/material_groups", timeout=60).json()
    for group in body.get("groups", []):
        requests.delete(base_url + f"/api/material_groups/{group['id']}", timeout=60)


def test_save_group_from_analysis_and_filter_with_linetypes(browser_page):
    """'Bewaar als groep' vanuit de analyse → dropdown filtert de tabel én
    blijft werken in combinatie met het linetype-filter (de gemelde bug)."""
    page = browser_page
    base_url = page.server["base_url"]
    page.reload(wait_until="networkidle")
    try:
        # Analyse openen op de omzetreeks en een groep bewaren.
        expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
        page.evaluate("() => window.showTab && window.showTab('dashboard')")
        page.wait_for_function(
            "() => typeof Chart !== 'undefined' && !!Chart.getChart(document.getElementById('financialChart'))",
            timeout=60000)
        page.evaluate(
            "() => openChartZoomForCanvas(document.getElementById('financialChart'), 'fin')")
        page.evaluate("() => openChartAnalysis()")
        page.wait_for_function(
            "() => window._lastChartAnalysis && window._lastChartAnalysis.rows.some(r => r.material)",
            timeout=30000)
        page.evaluate(
            """() => {
                window.prompt = () => 'Browsertest groep';
                return _analysisSaveAsGroup();
            }"""
        )
        page.wait_for_function(
            "() => (state.materialGroups || []).some(g => g.name === 'Browsertest groep')",
            timeout=30000)
        page.evaluate("() => closeChartZoom()")

        # Dropdown zichtbaar op de planningstab; filter op de groep.
        page.evaluate("() => window.showTab('planning')")
        page.wait_for_selector("#planBody tr[data-material]", timeout=30000)
        info = page.evaluate(
            """() => {
                const g = state.materialGroups.find(x => x.name === 'Browsertest groep');
                _setMaterialGroupFilter(g.id);
                return { mats: g.materials, visible: null };
            }"""
        )
        page.wait_for_function(
            """(mats) => {
                const vis = [...document.querySelectorAll('#planBody tr[data-material]')]
                    .filter(r => r.style.display !== 'none');
                return vis.length > 0 && vis.every(r => mats.includes(r.dataset.material));
            }""",
            arg=info["mats"],
            timeout=15000,
        )
        assert not page.locator("#matGroupSelect").evaluate(
            "el => el.classList.contains('hidden')")

        # Linetype-filter erbovenop: groepsfilter blijft (de oorspronkelijke bug).
        page.evaluate(
            """() => {
                const cb = document.querySelector('#ltDropdown input[type="checkbox"]');
                if (cb) cb.click();
            }"""
        )
        page.wait_for_timeout(300)
        check = page.evaluate(
            """(mats) => {
                const vis = [...document.querySelectorAll('#planBody tr[data-material]')]
                    .filter(r => r.style.display !== 'none');
                return {
                    stillFiltered: _materialGroupFilterId !== null,
                    allInGroup: vis.every(r => mats.includes(r.dataset.material)),
                };
            }""",
            info["mats"],
        )
        assert check["stillFiltered"], "linetype-filter wiste het groepsfilter"
        assert check["allInGroup"]
        assert page.js_errors == []
    finally:
        page.evaluate(
            """() => {
                _setMaterialGroupFilter(null, { skipFilter: true });
                const all = document.querySelector('#ltDropdown input[type="checkbox"]');
                if (all && !all.checked) all.click();
                filterTable();
            }"""
        )
        _delete_all_groups(base_url)


def test_activate_group_scopes_dashboard_values_machines(browser_page):
    """'Maak actief': banner overal zichtbaar, dashboard toont alleen de
    groepsbijdrage, values tonen de bijdragemarge, machines-tab toont het
    groepsaandeel met bewerkblokkade; deactiveren herstelt alles."""
    page = browser_page
    base_url = page.server["base_url"]
    page.reload(wait_until="networkidle")
    gid = None
    try:
        expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
        page.evaluate("() => window.showTab && window.showTab('dashboard')")
        page.wait_for_function(
            "() => window._dashboardData && window._dashboardData.demand_trend",
            timeout=60000)
        full_total = page.evaluate(
            "() => Object.values(window._dashboardData.demand_trend).reduce((s,v)=>s+v,0)")

        # Groep van 3 vraagmaterialen via de API.
        results = requests.get(base_url + "/api/results", timeout=120).json()["results"]
        mats = []
        for row in results.get("03. Total demand", []):
            if sum(row["values"].values()) > 0:
                mats.append(str(row["material_number"]))
            if len(mats) == 3:
                break
        resp = requests.post(base_url + "/api/material_groups", json={
            "name": "Scope test", "materials": mats}, timeout=60)
        gid = resp.json()["group"]["id"]

        page.evaluate("() => loadMaterialGroups()")
        page.wait_for_function("() => (state.materialGroups || []).length > 0",
                               timeout=15000)
        page.evaluate("(g) => activateMaterialGroup(g)", gid)
        expect(page.locator("#activeGroupBanner")).to_be_visible(timeout=60000)
        assert "Scope test" in page.locator("#activeGroupName").text_content()

        # Dashboard: gescoopte vraag < volledige vraag, KPI's/notities.
        page.wait_for_function(
            "() => window._dashboardData && window._dashboardData.scoped",
            timeout=60000)
        scoped_total = page.evaluate(
            "() => Object.values(window._dashboardData.demand_trend).reduce((s,v)=>s+v,0)")
        assert 0 < scoped_total < full_total
        assert page.locator("#kpi-fte").text_content().strip() == "—"

        # Values: bijdragemarge zichtbaar in de gescoopte consolidatie.
        page.wait_for_function("() => !!state.scopedConsolidation", timeout=30000)
        page.evaluate("() => window.showTab('values')")
        page.wait_for_function(
            "() => document.getElementById('consolDiv').textContent.includes('Bijdragemarge')",
            timeout=30000)

        # Machines: scoped-notitie + bewerken geblokkeerd.
        page.evaluate("() => window.showTab('capacity')")
        page.wait_for_function(
            "() => _machinesData && _machinesData.scoped", timeout=60000)
        page.wait_for_selector("#machinesScopedNote", timeout=15000)
        page.evaluate("() => toggleMachineEditMode()")
        assert not page.evaluate("() => _machineEditMode"), \
            "bewerkmodus moet geblokkeerd zijn bij actieve groep"

        # Deactiveren: banner weg, server ongescoopt.
        page.click("#activeGroupBanner button")
        expect(page.locator("#activeGroupBanner")).to_be_hidden(timeout=60000)
        dashboard = requests.get(base_url + "/api/dashboard", timeout=120).json()
        assert "scoped" not in dashboard
        assert page.js_errors == []
    finally:
        try:
            requests.post(base_url + "/api/material_groups/deactivate", timeout=60)
        except requests.RequestException:
            pass
        _delete_all_groups(base_url)
