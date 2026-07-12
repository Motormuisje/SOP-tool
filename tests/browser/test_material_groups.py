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


def test_dropdown_alle_groepen_escapes_active_group(browser_page):
    """Regressie (gemeld): groep actief → dropdown terug naar 'Alle groepen'
    liet de tabel gescoopt achter ('vast in de groepsweergave'). Nu stuurt de
    dropdown de activatie zolang een groep actief is, en toont hij de actieve
    groep in plaats van misleidend 'Alle groepen'. Gedreven via de ECHTE
    select (select_option), niet programmatisch — dat was het testgat."""
    page = browser_page
    base_url = page.server["base_url"]
    page.reload(wait_until="networkidle")
    gid = None
    try:
        _open_planning(page)
        total_rows = page.evaluate(
            "() => [...document.querySelectorAll('#planBody tr[data-material]')]"
            ".filter(r => r.style.display !== 'none').length")

        results = requests.get(base_url + "/api/results", timeout=120).json()["results"]
        mats = [str(r["material_number"]) for r in results["03. Total demand"][:2]]
        gid = requests.post(base_url + "/api/material_groups", json={
            "name": "Dropdown escape", "materials": mats}, timeout=60).json()["group"]["id"]
        page.evaluate("() => loadMaterialGroups()")
        page.wait_for_function("() => (state.materialGroups || []).length > 0",
                               timeout=15000)

        # Activeer via de dropdown? Nee — via het menu, zoals de gebruiker.
        page.evaluate("(g) => activateMaterialGroup(g)", gid)
        expect(page.locator("#activeGroupBanner")).to_be_visible(timeout=60000)
        page.evaluate("() => window.showTab('planning')")
        page.wait_for_function(
            """(n) => [...document.querySelectorAll('#planBody tr[data-material]')]
                .filter(r => r.style.display !== 'none').length < n""",
            arg=total_rows, timeout=15000)

        # De dropdown toont de ACTIEVE groep, niet 'Alle groepen'.
        assert page.locator("#matGroupSelect").input_value() == gid
        label = page.evaluate(
            "() => document.querySelector('#matGroupSelect option:checked').textContent")
        assert "actief" in label

        # ECHTE select: terug naar 'Alle groepen' → deactiveert alles.
        page.select_option("#matGroupSelect", "")
        expect(page.locator("#activeGroupBanner")).to_be_hidden(timeout=60000)
        page.wait_for_function(
            """(n) => [...document.querySelectorAll('#planBody tr[data-material]')]
                .filter(r => r.style.display !== 'none').length === n""",
            arg=total_rows, timeout=60000)
        assert "scoped" not in requests.get(base_url + "/api/dashboard",
                                            timeout=120).json()

        # En andersom: groep kiezen in de dropdown zonder actieve groep is
        # een tabelfilter; daarna 'Alle groepen' herstelt (pure flow).
        page.select_option("#matGroupSelect", gid)
        page.wait_for_function(
            """(n) => [...document.querySelectorAll('#planBody tr[data-material]')]
                .filter(r => r.style.display !== 'none').length < n""",
            arg=total_rows, timeout=15000)
        page.select_option("#matGroupSelect", "")
        page.wait_for_function(
            """(n) => [...document.querySelectorAll('#planBody tr[data-material]')]
                .filter(r => r.style.display !== 'none').length === n""",
            arg=total_rows, timeout=15000)
        assert page.js_errors == []
    finally:
        try:
            requests.post(base_url + "/api/material_groups/deactivate", timeout=60)
        except requests.RequestException:
            pass
        _delete_all_groups(base_url)


def test_empty_filter_state_shows_hint_with_reset(browser_page):
    """Klasse-fix: elke filtercombinatie die alles wegfiltert moet zichzelf
    uitleggen en een uitweg bieden (voorheen: lege tabel zonder verklaring)."""
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_planning(page)
    total = page.evaluate(
        "() => [...document.querySelectorAll('#planBody tr[data-material]')]"
        ".filter(r => r.style.display !== 'none').length")

    page.evaluate(
        "() => { document.getElementById('matSearch').value = 'XXNIETBESTAANDXX'; filterTable(); }")
    page.wait_for_selector("#planEmptyHint", state="visible", timeout=10000)
    hint = page.evaluate("() => document.getElementById('planEmptyHint').textContent")
    assert "Geen rijen zichtbaar" in hint and "Herstel filters" in hint

    page.click("#planEmptyHint button")
    page.wait_for_function(
        """(n) => [...document.querySelectorAll('#planBody tr[data-material]')]
            .filter(r => r.style.display !== 'none').length === n""",
        arg=total, timeout=10000)
    assert not page.locator("#planEmptyHint").is_visible()
    assert page.evaluate("() => document.getElementById('matSearch').value") == ""
    assert page.js_errors == []


def test_analysis_scope_cleared_on_session_switch(browser_page):
    """Klasse-fix: de 'Toon in planningstabel'-scope verwees na een
    sessiewissel naar materialen van de vorige sessie (lege tabel)."""
    page = browser_page
    base_url = page.server["base_url"]
    sid_orig = page.server["session_id"]
    sid_b = None
    page.reload(wait_until="networkidle")
    try:
        _open_planning(page)
        snap = requests.post(base_url + "/api/sessions/snapshot",
                             json={"name": "Scope wissel test"}, timeout=120)
        sid_b = snap.json()["session"]["id"]

        page.evaluate(
            """() => {
                const r = document.querySelector('#planBody tr[data-material]');
                _editedMaterialScope = new Set([r.dataset.material]);
                _vpMaterialScope = new Set([r.dataset.material]);
                filterTable();
            }""")
        page.evaluate("(sid) => switchSession(sid)", sid_b)
        page.wait_for_function("(sid) => state.activeSessionId === sid",
                               arg=sid_b, timeout=180000)
        cleared = page.evaluate(
            "() => _editedMaterialScope === null && _vpMaterialScope === null")
        assert cleared, "analyse-/VP-scope had gewist moeten zijn na sessiewissel"
        page.evaluate("(sid) => switchSession(sid)", sid_orig)
        page.wait_for_function("(sid) => state.activeSessionId === sid",
                               arg=sid_orig, timeout=180000)
        assert page.js_errors == []
    finally:
        try:
            requests.post(base_url + "/api/sessions/switch",
                          json={"session_id": sid_orig}, timeout=300)
            if sid_b:
                requests.delete(base_url + f"/api/sessions/{sid_b}", timeout=60)
        except requests.RequestException:
            pass


def test_analysis_works_under_active_group(browser_page):
    """Klasse-fix: onder een actieve groep toont de financiële grafiek
    gescoopte labels (Groepsomzet, Bijdragemarge) — de analyse moet die
    kennen én de productbijdragen tot de groep beperken; de volumetrend
    moet reconciliëren met de gescoopte reeks. Ook: filter-undo mag het
    losse groepsfilter niet terugbrengen bovenop de actieve groep."""
    page = browser_page
    base_url = page.server["base_url"]
    page.reload(wait_until="networkidle")
    gid = None
    try:
        _open_planning(page)
        results = requests.get(base_url + "/api/results", timeout=120).json()["results"]
        mats = [str(r["material_number"])
                for r in results.get("03. Total demand", [])
                if sum(r["values"].values()) > 0][:3]
        gid = requests.post(base_url + "/api/material_groups", json={
            "name": "Analyse scope", "materials": mats}, timeout=60).json()["group"]["id"]
        page.evaluate("() => loadMaterialGroups()")
        page.wait_for_function("() => (state.materialGroups || []).length > 0",
                               timeout=15000)
        # Snapshot met groepsfilter in de historie, daarna activeren.
        page.select_option("#matGroupSelect", gid)
        page.evaluate("() => pushFilterHistory()")
        page.evaluate("(g) => activateMaterialGroup(g)", gid)
        expect(page.locator("#activeGroupBanner")).to_be_visible(timeout=60000)

        # B-guard: undo mag het losse filter niet herstellen bij actieve groep.
        page.evaluate("() => undoFilterState()")
        assert page.evaluate("() => _materialGroupFilterId") is None

        page.evaluate("() => window.showTab('dashboard')")
        page.wait_for_function(
            "() => window._dashboardData && window._dashboardData.scoped",
            timeout=60000)

        # Financiële grafiek: gescoopte labels zijn analyseerbaar.
        page.evaluate(
            "() => openChartZoomForCanvas(document.getElementById('financialChart'), 'fin')")
        page.evaluate("() => openChartAnalysis()")
        page.wait_for_function("() => !!window._lastChartAnalysis", timeout=30000)
        page.evaluate(
            """() => {
                const ds = _zoomChart.data.datasets.findIndex(d => d.label === 'Groepsomzet');
                return _analysisApplySelection(ds, 1, 2);
            }""")
        page.wait_for_function(
            "() => window._lastChartAnalysis && window._lastChartAnalysis.iA === 1",
            timeout=30000)
        check = page.evaluate(
            """(mats) => {
                const a = window._lastChartAnalysis;
                return {
                    head: document.getElementById('chartAnalysisHeadline').textContent,
                    inGroup: a.rows.filter(r => r.material)
                        .every(r => mats.includes(String(r.material))),
                    reconciles: Math.abs(a.contributorSum - a.totalDelta)
                        <= Math.max(1, 0.01 * Math.abs(a.totalDelta)),
                };
            }""", mats)
        assert "Omzet" in check["head"] or "Geen noemenswaardige" in check["head"]
        assert check["inGroup"], "bijdragen buiten de actieve groep in de analyse"
        assert check["reconciles"], check

        # Volumetrend: bijdragen ⊆ groep en som sluit aan op de gescoopte reeks.
        page.evaluate("() => closeChartZoom()")
        page.evaluate(
            "() => openChartZoomForCanvas(document.getElementById('demandTrendChart'), 'trend')")
        page.evaluate("() => openChartAnalysis()")
        page.wait_for_function("() => !!window._lastChartAnalysis", timeout=30000)
        check = page.evaluate(
            """(mats) => {
                const a = window._lastChartAnalysis;
                return {
                    inGroup: a.rows.filter(r => r.material)
                        .every(r => mats.includes(String(r.material))),
                    reconciles: Math.abs(a.contributorSum - a.totalDelta)
                        <= Math.max(1, 0.01 * Math.abs(a.totalDelta)),
                };
            }""", mats)
        assert check["inGroup"] and check["reconciles"], check
        page.evaluate("() => closeChartZoom()")
        assert page.js_errors == []
    finally:
        try:
            requests.post(base_url + "/api/material_groups/deactivate", timeout=60)
        except requests.RequestException:
            pass
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
