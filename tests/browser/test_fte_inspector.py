"""Werkbank-inspecteur: één paneel naast de tabel (docs/plan-werkbank-inspecteur.md).

Draait op een EIGEN server met de masterdata van het golden werkboek in de
store (zonder store geeft /api/master_data/* een 400 en kan het paneel geen
tarief of combinatie schrijven). De F2-CF-datasets zijn daarin leeg: geen
normen, tarieven of combinaties — de toestand waarin een klant de werkbank
voor het eerst opent. Wat een test in de masterdata of de sessie zet, ruimt
hij zelf op.
"""

import pytest
import requests
from playwright.sync_api import expect

TIMEOUT = 180


def _ensure_store(server, golden_fixture_path):
    status = requests.get(server["base_url"] + "/api/master_data", timeout=TIMEOUT).json()
    if status.get("exists"):
        return
    with golden_fixture_path.open("rb") as workbook:
        response = requests.post(
            server["base_url"] + "/api/master_data/import",
            files={"file": (golden_fixture_path.name, workbook)},
            data={"confirm": "true"}, timeout=600)
    assert response.ok and response.json().get("success"), response.text


@pytest.fixture
def inspector_page(page, own_server, golden_fixture_path):
    """Zelfde contract als browser_page (js_errors, .server), maar op de eigen
    server van deze module en met een gevulde masterstore."""
    _ensure_store(own_server, golden_fixture_path)
    js_errors = []

    def collect(message):
        if message.type == "error" and not message.text.startswith("Failed to load resource:"):
            js_errors.append(message.text)

    page.on("console", collect)
    response = page.goto(own_server["base_url"], wait_until="networkidle")
    assert response is not None and response.ok
    page.js_errors = js_errors
    page.server = own_server
    return page


def _open_workbench(page):
    page.reload(wait_until="networkidle")
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    with page.expect_response(lambda r: "/api/fte" in r.url and r.ok):
        page.evaluate("() => window.showTab && window.showTab('fte')")
    page.wait_for_function(
        "() => document.querySelectorAll('#fteWbBody tr').length > 0", timeout=30000)
    # De doorzetkolom leest de machinedata van de Machines-tab.
    page.wait_for_function("() => !!_machinesData", timeout=30000)


def _dock_open(page):
    return page.evaluate("() => document.getElementById('fteDock').classList.contains('open')")


def _visible_columns(page):
    return page.evaluate(
        "() => [...document.querySelectorAll('#fteWbHead th')].filter(t => t.offsetParent !== null).length")


def _row_hours(page, key):
    return page.evaluate("(k) => _fteAgg(_fteLineByRowId('machine:' + k).hours)", key)


def _first_machine_with_hours(page):
    """Een machine met uren, doorzet en een ONGEWIJZIGDE OEE (een eerdere
    test kan er een hebben laten staan; 'terug naar origineel' zou dan naar
    de baseline gaan en niet naar onze uitgangswaarde)."""
    return page.evaluate(
        """() => {
            const l = _fteState.data.lines.find(x => x.category === 'machine' && _fteAgg(x.hours) > 0
                && (() => { const m = _fteMachineInfo(x.key);
                            return m && m.throughput_effective > 0 && m.oee <= 1.2
                                   && !(m.edit_meta && m.edit_meta.oee); })());
            return l ? { key: String(l.key), group: String(l.machine_group || '') } : null;
        }""")


def _open_machine_panel(page, key, group):
    if group:
        page.evaluate("(g) => { if (!_fteState.openGroups.has(g)) toggleFteGroup(g); }", group)
    page.click(f"#fteWbBody tr[data-fte-row='machine:{key}'] td:nth-child(4)")
    page.wait_for_function(
        "(k) => document.getElementById('fteDock').classList.contains('open') && _fteInspector.rowId === 'machine:' + k",
        arg=key, timeout=15000)
    page.wait_for_selector("#fteInsTpInput", timeout=15000)


def test_row_click_opens_the_panel_and_esc_closes_it(inspector_page):
    """Elke regel is de ingang: klikken opent het paneel met de vier secties,
    de tabel wordt compact (Bron en Beschikbaar wijken), Esc herstelt alles."""
    page = inspector_page
    _open_workbench(page)
    assert not _dock_open(page)
    assert _visible_columns(page) == 9

    row = page.locator("#fteWbBody tr[data-fte-row^='group:']").first
    row_id = row.evaluate("r => r.dataset.fteRow")
    row.locator("td").nth(3).click()
    page.wait_for_function(
        "() => document.getElementById('fteDock').classList.contains('open')"
        " && document.getElementById('fteDockBody').children.length > 0", timeout=15000)
    state = page.evaluate(
        """() => ({
            kicker: document.getElementById('fteDockKicker').textContent,
            title: document.getElementById('fteDockTitle').textContent,
            sections: [...document.querySelectorAll('#fteDockBody section')].map(s => s.id),
            padded: parseFloat(document.getElementById('fteWbSplit').style.paddingRight || '0') > 0,
            active: document.querySelector('#fteWbBody tr.fte-row-active')?.dataset.fteRow,
        })""")
    assert state["kicker"] == "Machinegroep"
    assert state["title"] == page.evaluate("(id) => _fteLineByRowId(id).label", row_id)
    assert state["sections"] == ["fteIns-norm", "fteIns-rate", "fteIns-throughput", "fteIns-combos"]
    assert state["padded"] is True
    assert state["active"] == row_id
    assert _visible_columns(page) == 7

    page.keyboard.press("Escape")
    page.wait_for_function(
        "() => !document.getElementById('fteDock').classList.contains('open')", timeout=5000)
    assert _visible_columns(page) == 9
    assert page.evaluate("() => document.getElementById('fteWbSplit').style.paddingRight") == ""
    assert page.evaluate("() => document.querySelectorAll('#fteWbBody tr.fte-row-active').length") == 0
    assert page.js_errors == []


def test_machine_panel_shows_the_throughput_the_planning_uses(inspector_page):
    """Rij en paneel tonen dezelfde effectieve doorzet als de Machines-tab,
    de OEE staat erbij als rekenfactor, de routingnorm per product is
    leeswaarde, en MES/PEER komen nergens meer voor."""
    page = inspector_page
    _open_workbench(page)
    target = _first_machine_with_hours(page)
    assert target, "geen machine met uren en doorzet in de sessie"
    _open_machine_panel(page, target["key"], target["group"])

    report = page.evaluate(
        """(k) => {
            const m = _fteMachineInfo(k);
            const eff = _fteEffScope(m);
            const cell = document.querySelector(`#fteWbBody tr[data-fte-row='machine:${k}'] td:nth-child(9)`).textContent.trim();
            const section = document.getElementById('fteIns-throughput').textContent;
            const l07 = (state.results['07. Capacity utilization'] || [])
                .filter(r => r.product_type !== 'Machine Group' && String(r.aux_column || '') === k).length;
            const expectedRows = l07 === 0 ? 1 : Math.min(l07, 12) + (l07 > 12 ? 1 : 0);
            return { input: document.getElementById('fteInsTpInput').value, expected: _fteInputNum(eff, 1),
                     cell, cellExpected: _fmtNlNum(eff, 1),
                     oeeInSection: section.includes('rekenfactor (OEE) ' + _fmtNlNum(m.oee * 100, 1) + ' %'),
                     routingRows: document.querySelectorAll('#fteIns-throughput tbody tr').length, expectedRows,
                     mesPeer: /\\b(MES|PEER)\\b/.test(document.getElementById('fteDockBody').textContent) };
        }""", target["key"])
    assert report["input"] == report["expected"]
    assert report["cell"] == report["cellExpected"]
    assert report["oeeInSection"] is True, report
    assert report["routingRows"] == report["expectedRows"], report
    assert report["mesPeer"] is False
    page.keyboard.press("Escape")
    assert page.js_errors == []


def test_throughput_apply_scales_the_oee_and_reset_restores_it(inspector_page):
    """Doorzet aanpassen gebruikt het Machines-mechanisme: +20 % doorzet =
    OEE × 1,2 via /api/machines/update, dus de planning rekent mee (minder
    uren op de rij). 'Terug naar origineel' herstelt OEE én uren."""
    page = inspector_page
    _open_workbench(page)
    target = _first_machine_with_hours(page)
    assert target, "geen machine met uren, doorzet en ongewijzigde OEE"
    key = target["key"]
    _open_machine_panel(page, key, target["group"])

    base = page.evaluate(
        "(k) => { const m = _fteMachineInfo(k); return { oee: m.oee, eff: _fteEffScope(m) }; }", key)
    base_hours = _row_hours(page, key)
    goal = round(base["eff"] * 1.2, 1)
    page.fill("#fteInsTpInput", str(goal).replace(".", ","))
    with page.expect_response(lambda r: "/api/machines/update" in r.url and r.ok):
        page.press("#fteInsTpInput", "Enter")
    # Wachten op de toestand, niet op het netwerk: na de update volgen nog
    # /api/machines en /api/fte voordat rij en paneel de nieuwe stand tonen.
    page.wait_for_function(
        "([k, prev]) => _fteAgg(_fteLineByRowId('machine:' + k).hours) < prev - 0.5",
        arg=[key, base_hours], timeout=30000)
    page.wait_for_selector("#fteIns-throughput .fte-link", timeout=15000)
    after = page.evaluate(
        """(k) => { const m = _fteMachineInfo(k);
                    return { oee: m.oee, eff: _fteEffScope(m),
                             rowAmber: !!document.querySelector(`#fteWbBody tr[data-fte-row='machine:${k}'] td:nth-child(9) .text-amber-300`) }; }""",
        key)
    assert after["oee"] == pytest.approx(base["oee"] * 1.2, rel=0.02)
    assert after["eff"] == pytest.approx(goal, rel=0.02)
    assert after["rowAmber"] is True
    server = requests.get(page.server["base_url"] + "/api/machines", timeout=TIMEOUT).json()
    machine = next(x for x in server["machines"] if str(x["code"]) == key)
    assert machine["oee"] == pytest.approx(after["oee"], abs=0.001)

    with page.expect_response(lambda r: "/api/machines/update" in r.url and r.ok):
        page.click("#fteIns-throughput .fte-link")
    page.wait_for_function(
        "([k, base]) => Math.abs(_fteAgg(_fteLineByRowId('machine:' + k).hours) - base) < 0.5",
        arg=[key, base_hours], timeout=30000)
    restored = page.evaluate(
        "(k) => { const m = _fteMachineInfo(k); return { oee: m.oee, edited: !!(m.edit_meta && m.edit_meta.oee) }; }", key)
    assert restored["oee"] == pytest.approx(base["oee"], abs=0.001)
    assert restored["edited"] is False
    page.keyboard.press("Escape")
    assert page.js_errors == []


def test_rate_saved_from_the_panel_refreshes_the_workbench(inspector_page):
    """Een stille € 0 wordt in het paneel een tarief: opslaan gaat langs de
    bestaande PATCH en de werkbank rekent meteen met het nieuwe tarief."""
    page = inspector_page
    _open_workbench(page)
    base_url = page.server["base_url"]
    before = requests.get(base_url + "/api/master_data/labor_rates", timeout=TIMEOUT).json()
    target = page.evaluate(
        """() => { const l = _fteState.data.lines.find(x => x.category !== 'machine' && !x.combination_id
                       && _fteAgg(x.fte, 'avg') > 0.005 && _fteAgg(x.cost) === 0);
                   return l ? { rowId: `${l.category}:${l.key}`, fg: l.function_group || 'default' } : null; }""")
    if target is None:
        pytest.skip("alle regels hebben al een tarief")

    page.click(f"#fteWbBody tr[data-fte-row='{target['rowId']}'] td:nth-child(4)")
    page.wait_for_selector("#fteIns-rate input.fte-in", timeout=15000)
    page.fill("#fteIns-rate input.fte-in", "60000")
    with page.expect_response(lambda r: "/api/master_data/labor_rates" in r.url
                              and r.request.method == "PATCH" and r.ok):
        page.click("#fteIns-rate .fte-btn-primary")
    page.wait_for_function("(id) => _fteAgg(_fteLineByRowId(id).cost) > 0", arg=target["rowId"], timeout=30000)

    saved = requests.get(base_url + "/api/master_data/labor_rates", timeout=TIMEOUT).json()
    assert saved["value"][target["fg"]]["cost_per_fte_per_year"] == 60000
    numbers = page.evaluate(
        """(id) => { const l = _fteLineByRowId(id);
                     return { cost: _fteAgg(l.cost), fte: _fteAgg(l.fte, 'avg'), periods: _ftePeriodsInScope().length }; }""",
        target["rowId"])
    assert numbers["cost"] == pytest.approx(numbers["fte"] * 60000 / 12 * numbers["periods"], rel=0.02)
    assert "geen tarief" not in page.locator(f"#fteWbBody tr[data-fte-row='{target['rowId']}']").inner_text()
    page.keyboard.press("Escape")

    # Opruimen: de server terug naar de stand van vóór deze test.
    reset = requests.patch(base_url + "/api/master_data/labor_rates",
                           json={"value": before.get("value") or {}, "base_version": saved["version"]},
                           timeout=TIMEOUT)
    assert reset.ok, reset.text
    assert requests.post(base_url + "/api/fte/refresh", timeout=TIMEOUT).ok
    assert page.js_errors == []


def test_combine_creates_activates_and_deletes_a_combination(inspector_page):
    """Combineren vanuit de tabel: kiesmodus, twee machines, bandbreedte-hint
    op 'operators samen', aanmaken en aanzetten (masterdata + sessie), de
    combinatierij zonder benutting, uitzetten, verwijderen."""
    page = inspector_page
    page.on("dialog", lambda d: d.accept())
    _open_workbench(page)
    base_url = page.server["base_url"]
    pair = page.evaluate(
        """() => _fteState.data.lines.filter(l => l.category === 'machine' && _fteAgg(l.hours) > 0
                     && !_fteActiveComboOf(l.key)).slice(0, 2).map(l => String(l.key))""")
    assert len(pair) == 2, "twee vrije machines met uren nodig"

    page.click("#fteCombineBtn")
    page.wait_for_function("() => _fteCombine.active && _fteDrawerMode === 'combine'", timeout=10000)
    assert page.evaluate(
        "() => document.querySelectorAll('#fteWbBody tr[data-fte-row^=\"machine:\"] input[type=checkbox]').length") > 0
    for code in pair:
        page.click(f"#fteWbBody tr[data-fte-row='machine:{code}'] td:nth-child(4)")
        page.wait_for_function("(c) => _fteCombine.selected.has(c)", arg=code, timeout=10000)
    page.wait_for_function("() => document.querySelectorAll('#fteDockBody .fte-chip').length === 2", timeout=10000)

    band = page.locator("#fteCombOpsHint").inner_text()
    assert "los:" in band and "gedeeld: 1" in band, band
    assert page.input_value("#fteCombOpsInput") == "1"
    page.fill("#fteCombOpsInput", "5")
    page.wait_for_function(
        "() => document.getElementById('fteCombOpsInput').classList.contains('fte-warn')", timeout=5000)
    assert "meer dan los bemannen" in page.locator("#fteCombOpsHint").inner_text()
    page.fill("#fteCombOpsInput", "1")
    page.wait_for_function(
        "() => !document.getElementById('fteCombOpsInput').classList.contains('fte-warn')", timeout=5000)
    page.fill("#fteDockBody input.w-48", "Testcombinatie")
    page.evaluate("() => { _fteCombineForm().nameTouched = true; }")

    with page.expect_response(lambda r: "/api/fte/combinations" in r.url and r.ok):
        page.click("#fteDockBody button:has-text('Aanmaken en aanzetten')")
    page.wait_for_function(
        "() => _fteState.active.length === 1 && _fteDrawerMode === 'inspector'", timeout=30000)
    combo_id = page.evaluate("() => _fteState.active[0]")
    assert combo_id.startswith("COMBI_TESTCOMBINATIE")
    stored = requests.get(base_url + "/api/master_data/machine_combinations", timeout=TIMEOUT).json()["value"]
    assert stored[combo_id]["machine_codes"] == pair
    assert stored[combo_id]["operators"] == 1
    page.wait_for_selector(f"#fteWbBody tr[data-fte-row='group:{combo_id}']", timeout=15000)
    view = page.evaluate(
        """(id) => { const r = document.querySelector(`#fteWbBody tr[data-fte-row='group:${id}']`);
                     return { util: r.querySelector('td:nth-child(6)').textContent.trim(),
                              kicker: document.getElementById('fteDockKicker').textContent,
                              btn: document.getElementById('fteCombineBtn').textContent,
                              combining: _fteCombine.active,
                              hint: document.getElementById('fteDockBody').textContent.includes('gedeeld: 1') }; }""",
        combo_id)
    assert view["util"] == "—"
    assert view["kicker"].startswith("Machinecombinatie") and "aan" in view["kicker"]
    assert view["btn"] == "Combineren" and view["combining"] is False
    assert view["hint"] is True
    # De formule uit de ontwerpnotitie: FTE = operators × MAX(uren leden) / (FTE-uren per jaar / 12),
    # gemiddeld over het bereik (doorzetverlies 0, dus factor 1).
    formula = page.evaluate(
        """(id) => { const combo = _fteComboById(id); const line = _fteLineByRowId('group:' + id);
                    const scope = _ftePeriodsInScope(); const monthly = _fteState.data.fte_hours_per_year / 12;
                    const maxHours = scope.map(p => Math.max(...combo.machine_codes.map(c => Number(((_fteLineByRowId('machine:' + c) || {}).hours || {})[p] || 0))));
                    const expected = maxHours.reduce((s, h) => s + h * combo.operators / monthly, 0) / scope.length;
                    return { expected, actual: _fteAgg(line.fte, 'avg') }; }""",
        combo_id)
    assert formula["actual"] == pytest.approx(formula["expected"], rel=0.01), formula

    # Uitzetten via het paneel: de rij verdwijnt, het paneel blijft en zegt 'uit'.
    with page.expect_response(lambda r: "/api/fte/combinations" in r.url and r.ok):
        page.click("#fteIns-combo input[type=checkbox]")
    page.wait_for_function("() => _fteState.active.length === 0", timeout=30000)
    page.wait_for_function(
        "(id) => !document.querySelector(`#fteWbBody tr[data-fte-row='group:${id}']`)", arg=combo_id, timeout=15000)
    assert "uit in deze sessie" in page.locator("#fteDockKicker").inner_text().lower()

    # Verwijderen ruimt de masterdata op en sluit het paneel.
    with page.expect_response(lambda r: "/api/master_data/machine_combinations" in r.url
                              and r.request.method == "PATCH" and r.ok):
        page.click("#fteIns-combo button:has-text('Verwijderen')")
    page.wait_for_function(
        "() => !document.getElementById('fteDock').classList.contains('open')", timeout=15000)
    assert requests.get(base_url + "/api/master_data/machine_combinations", timeout=TIMEOUT).json()["value"] == {}
    assert page.js_errors == []


def test_installation_parameters_open_in_the_panel_and_return_to_config(inspector_page):
    """'doel x %' onder 'Bij bezettingsdoel' opent het masterdata-formulier
    fte ín het paneel; sluiten zet de editor terug op het Config-tab."""
    page = inspector_page
    _open_workbench(page)
    link = page.locator("#fteKpiStaffedSub .fte-kpi-link")
    expect(link).to_be_attached()
    assert link.inner_text().startswith("doel ")

    with page.expect_response(lambda r: r.url.endswith("/api/master_data/fte") and r.ok):
        link.click()
    page.wait_for_function(
        "() => _fteDrawerMode === 'master' && document.getElementById('masterDatasetInline').closest('#fteDock') !== null",
        timeout=15000)
    assert page.evaluate(
        "() => document.querySelectorAll('#fteDockBody tr[data-master-field], #fteDockBody tr[data-master-param], #fteDockBody tr[data-master-shift]').length") > 0

    page.keyboard.press("Escape")
    page.wait_for_function("() => _fteDrawerMode === null", timeout=5000)
    assert page.evaluate(
        "() => document.getElementById('masterDatasetInline').closest('#cfgsec-tabellen') !== null")
    assert page.js_errors == []


# ═══════════════════════════════════════════════════════════════════════════
# Regressietests na de onafhankelijke audit van 2026-09-14 (F1–F7). Elk van
# deze tests speelt het foutpad na zoals de auditor het reproduceerde.
# ═══════════════════════════════════════════════════════════════════════════

def _capture_notes(page):
    """notify() onderscheppen: de tests beoordelen WAT de gebruiker te horen krijgt."""
    page.evaluate(
        """() => { window.__notes = []; const orig = window.notify;
                  window.notify = (m, t, d) => { window.__notes.push({ m: String(m), t: String(t || '') }); return orig ? orig(m, t, d) : undefined; }; }""")


def _notes(page):
    return page.evaluate("() => window.__notes || []")


def _first_silent_zero_row(page):
    return page.evaluate(
        """() => { const l = _fteState.data.lines.find(_fteIsSilentZero);
                   return l ? { rowId: `${l.category}:${l.key}`, fg: l.function_group || 'default' } : null; }""")


def _put_combo(base_url, combo_id, machines, fg):
    cur = requests.get(base_url + "/api/master_data/machine_combinations", timeout=TIMEOUT).json()
    value = dict(cur.get("value") or {})
    value[combo_id] = {"combination_id": combo_id, "name": combo_id, "machine_codes": machines, "operators": 1,
                       "throughput_factor": 1.0, "throughput_factor_by_machine": {}, "function_group": fg,
                       "description": "audit", "is_active": True}
    r = requests.patch(base_url + "/api/master_data/machine_combinations",
                       json={"value": value, "base_version": cur["version"]}, timeout=TIMEOUT)
    assert r.ok, r.text
    assert requests.post(base_url + "/api/fte/refresh", timeout=TIMEOUT).ok


def _drop_combo(base_url, combo_id):
    requests.post(base_url + "/api/fte/combinations", json={"active_combinations": []}, timeout=TIMEOUT)
    cur = requests.get(base_url + "/api/master_data/machine_combinations", timeout=TIMEOUT).json()
    value = dict(cur.get("value") or {})
    value.pop(combo_id, None)
    requests.patch(base_url + "/api/master_data/machine_combinations",
                   json={"value": value, "base_version": cur["version"]}, timeout=TIMEOUT)


def _set_rates(base_url, value):
    cur = requests.get(base_url + "/api/master_data/labor_rates", timeout=TIMEOUT).json()
    r = requests.patch(base_url + "/api/master_data/labor_rates",
                       json={"value": value, "base_version": cur["version"]}, timeout=TIMEOUT)
    assert r.ok, r.text
    assert requests.post(base_url + "/api/fte/refresh", timeout=TIMEOUT).ok
    return r.json()


def test_f1_rate_save_refuses_to_overwrite_a_newer_change(inspector_page):
    """Audit F1: het tariefformulier stoelt op de stand bij het openen. Wijzigt
    een ander intussen hetzelfde tarief, dan mag opslaan dat niet stil
    overschrijven: eerst de nieuwe stand tonen, het concept blijft staan."""
    page = inspector_page
    _open_workbench(page)
    base_url = page.server["base_url"]
    before = requests.get(base_url + "/api/master_data/labor_rates", timeout=TIMEOUT).json()
    target = _first_silent_zero_row(page)
    if target is None:
        pytest.skip("geen regel zonder tarief")
    try:
        page.click(f"#fteWbBody tr[data-fte-row='{target['rowId']}'] td:nth-child(4)")
        page.wait_for_selector("#fteIns-rate input.fte-in", timeout=15000)
        shown_version = page.evaluate("() => _fteInspector.labor.version")

        # Een tweede editor zet intussen € 80.000.
        other = dict(before.get("value") or {})
        other[target["fg"]] = {"function_group": target["fg"], "cost_per_fte_per_year": 80000}
        _set_rates(base_url, other)

        _capture_notes(page)
        patches = []
        page.on("request", lambda req: patches.append(req.url)
                if req.method == "PATCH" and "/api/master_data/labor_rates" in req.url else None)
        page.fill("#fteIns-rate input.fte-in", "60000")
        page.click("#fteIns-rate .fte-btn-primary")
        page.wait_for_function("() => (window.__notes || []).some(n => n.m.includes('intussen door iemand anders'))", timeout=15000)
        assert patches == [], "een verouderd formulier mag niet PATCHen"
        stored = requests.get(base_url + "/api/master_data/labor_rates", timeout=TIMEOUT).json()
        assert stored["value"][target["fg"]]["cost_per_fte_per_year"] == 80000
        assert page.evaluate("() => _fteInspector.labor.version") > shown_version
        assert "80.000" in page.locator("#fteIns-rate").inner_text()
        assert page.input_value("#fteIns-rate input.fte-in") == "60000", "het concept moet blijven staan"

        # Nu is de getoonde stand actueel: opnieuw opslaan slaagt.
        with page.expect_response(lambda r: "/api/master_data/labor_rates" in r.url
                                  and r.request.method == "PATCH" and r.ok):
            page.click("#fteIns-rate .fte-btn-primary")
        page.wait_for_function(
            "(fg) => _fteInspector.labor.value[fg] && _fteInspector.labor.value[fg].cost_per_fte_per_year === 60000",
            arg=target["fg"], timeout=15000)
        page.keyboard.press("Escape")
        assert page.js_errors == []
    finally:
        _set_rates(base_url, before.get("value") or {})


def test_f2_machines_api_failure_does_not_loop(inspector_page):
    """Audit F2: faalt /api/machines, dan één poging en een stabiele
    fouttoestand met 'Opnieuw proberen' — geen herhaallus."""
    page = inspector_page
    calls = []
    page.on("request", lambda req: calls.append(req.url) if req.url.rstrip("/").endswith("/api/machines") else None)
    page.route("**/api/machines", lambda route: route.fulfill(status=500, content_type="application/json", body='{"error":"audit"}'))
    try:
        page.reload(wait_until="networkidle")
        expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
        with page.expect_response(lambda r: "/api/fte" in r.url and r.ok):
            page.evaluate("() => window.showTab && window.showTab('fte')")
        page.wait_for_function("() => document.querySelectorAll('#fteWbBody tr').length > 0", timeout=30000)
        page.wait_for_function("() => _fteMachinesFailed === true", timeout=15000)
        page.wait_for_timeout(2000)
        assert len(calls) <= 3, f"{len(calls)} machineverzoeken: herhaallus"
        assert page.evaluate("() => _machinesData") is None

        target = page.evaluate(
            """() => { const l = _fteState.data.lines.find(x => x.category === 'machine' && _fteAgg(x.hours) > 0);
                       return l ? { key: String(l.key), group: String(l.machine_group || '') } : null; }""")
        assert target
        if target["group"]:
            page.evaluate("(g) => { if (!_fteState.openGroups.has(g)) toggleFteGroup(g); }", target["group"])
        cell = page.locator(f"#fteWbBody tr[data-fte-row='machine:{target['key']}'] td:nth-child(9)").inner_text().strip()
        assert cell == "—"
        page.click(f"#fteWbBody tr[data-fte-row='machine:{target['key']}'] td:nth-child(4)")
        page.wait_for_selector("#fteIns-throughput button:has-text('Opnieuw proberen')", timeout=15000)
        assert len(calls) <= 3
    finally:
        page.unroute("**/api/machines")

    # Herstel: expliciet opnieuw proberen laadt de machinedata alsnog.
    page.click("#fteIns-throughput button:has-text('Opnieuw proberen')")
    page.wait_for_selector("#fteInsTpInput", timeout=30000)
    assert page.evaluate("() => _fteMachinesFailed") is False
    page.keyboard.press("Escape")
    assert page.js_errors == []


def test_f3_failed_activation_is_reported_honestly(inspector_page):
    """Audit F3: slaagt de masterdata maar faalt het aanzetten, dan zegt de
    melding precies dat — nooit 'aangemaakt en aangezet'. Het paneel toont
    de combinatie als 'uit' met het vinkje als herstelweg."""
    page = inspector_page
    page.on("dialog", lambda d: d.accept())
    _open_workbench(page)
    base_url = page.server["base_url"]
    pair = page.evaluate(
        """() => _fteState.data.lines.filter(l => l.category === 'machine' && _fteAgg(l.hours) > 0
                     && !_fteActiveComboOf(l.key)).slice(0, 2).map(l => String(l.key))""")
    assert len(pair) == 2
    page.route("**/api/fte/combinations", lambda route: route.fulfill(
        status=500, content_type="application/json", body='{"error":"audit: activatie geweigerd"}'))
    combo_id = None
    try:
        page.click("#fteCombineBtn")
        page.wait_for_function("() => _fteCombine.active", timeout=10000)
        for code in pair:
            page.click(f"#fteWbBody tr[data-fte-row='machine:{code}'] td:nth-child(4)")
            page.wait_for_function("(c) => _fteCombine.selected.has(c)", arg=code, timeout=10000)
        page.fill("#fteDockBody input.w-48", "Audit F3")
        page.evaluate("() => { _fteCombineForm().nameTouched = true; }")
        _capture_notes(page)
        page.click("#fteDockBody button:has-text('Aanmaken en aanzetten')")
        page.wait_for_function("() => _fteDrawerMode === 'inspector' && _fteInspector.rowId", timeout=30000)
        combo_id = page.evaluate("() => _fteInspector.rowId.slice('group:'.length)")
        notes = [n["m"] for n in _notes(page)]
        assert not any("aangemaakt en aangezet" in n for n in notes), notes
        assert any("aanzetten is mislukt" in n for n in notes), notes
        stored = requests.get(base_url + "/api/master_data/machine_combinations", timeout=TIMEOUT).json()["value"]
        assert combo_id in stored
        assert page.evaluate("() => _fteState.active") == []
        assert "uit in deze sessie" in page.locator("#fteDockKicker").inner_text().lower()
    finally:
        page.unroute("**/api/fte/combinations")

    # Herstelweg: het vinkje in het paneel zet hem alsnog aan.
    with page.expect_response(lambda r: "/api/fte/combinations" in r.url and r.ok):
        page.click("#fteIns-combo input[type=checkbox]")
    page.wait_for_function("(id) => _fteState.active.includes(id)", arg=combo_id, timeout=30000)
    _drop_combo(base_url, combo_id)
    assert page.js_errors == []


def test_f4_combination_panel_shows_the_default_rate_fallback(inspector_page):
    """Audit F4: rekent de motor met het 'default'-tarief, dan zegt het paneel
    dat — niet 'rekent stil met € 0'."""
    page = inspector_page
    base_url = page.server["base_url"]
    before = requests.get(base_url + "/api/master_data/labor_rates", timeout=TIMEOUT).json()
    pair = requests.get(base_url + "/api/fte", timeout=TIMEOUT).json()["fte"]["lines"]
    pair = [str(l["key"]) for l in pair if l["category"] == "machine" and sum(l["hours"].values()) > 0][:2]
    assert len(pair) == 2
    combo_id = "COMBI_AUDIT_F4"
    try:
        _set_rates(base_url, {**(before.get("value") or {}), "default": {"function_group": "default", "cost_per_fte_per_year": 72000}})
        _put_combo(base_url, combo_id, pair, "AUDIT_MISSING_RATE")
        assert requests.post(base_url + "/api/fte/combinations", json={"active_combinations": [combo_id]}, timeout=TIMEOUT).ok
        _open_workbench(page)
        page.click(f"#fteWbBody tr[data-fte-row='group:{combo_id}'] td:nth-child(4)")
        page.wait_for_selector("#fteIns-rate", timeout=15000)
        text = page.locator("#fteIns-rate").inner_text()
        assert 'valt terug op "default"' in text, text
        assert "72.000" in text, text
        assert "rekent stil met € 0" not in text, text
        assert page.evaluate("(id) => _fteAgg(_fteLineByRowId('group:' + id).cost)", combo_id) > 0
        page.keyboard.press("Escape")
        assert page.js_errors == []
    finally:
        _drop_combo(base_url, combo_id)
        _set_rates(base_url, before.get("value") or {})


def test_f5_delayed_panel_opening_is_cancelled_by_a_tab_switch(inspector_page):
    """Audit F5: wie tijdens het laden van het paneel van tabblad wisselt,
    krijgt achteraf geen paneel meer — ook niet in de state."""
    page = inspector_page
    _open_workbench(page)
    row_id = page.locator("#fteWbBody tr[data-fte-row^='group:']").first.evaluate("r => r.dataset.fteRow")
    page.evaluate(
        """() => { const orig = window.fetch;
                  window.fetch = (u, o) => String(u).includes('/api/master_data/labor_rates')
                      ? new Promise(res => setTimeout(() => res(orig(u, o)), 1500)) : orig(u, o); }""")
    page.click(f"#fteWbBody tr[data-fte-row='{row_id}'] td:nth-child(4)")
    page.evaluate("() => showTab('planning')")
    page.wait_for_timeout(2500)
    state = page.evaluate(
        "() => ({ tab: _activeTabName, mode: _fteDrawerMode, open: document.getElementById('fteDock').classList.contains('open'), rowId: _fteInspector.rowId })")
    assert state == {"tab": "planning", "mode": None, "open": False, "rowId": None}, state
    assert page.js_errors == []


def test_f6_what_if_controls_stay_reachable_in_every_panel(inspector_page):
    """Audit F6: zolang een paneel open is verbergt de CSS de zwevende lade,
    dus élk paneeltype moet de wat-als-bediening in zijn voet tonen."""
    page = inspector_page
    _open_workbench(page)
    if page.evaluate("() => Object.keys(_fteState.overrides).length"):
        with page.expect_response(lambda r: "/api/fte/norm_overrides" in r.url and r.ok):
            page.evaluate("() => revertFteNorms()")
    with page.expect_response(lambda r: "/api/fte/norm_overrides" in r.url and r.ok):
        page.evaluate(
            """() => { const input = document.querySelector('#fteWbBody input[data-fte-key]');
                      input.value = '2'; input.dispatchEvent(new Event('change', { bubbles: true })); }""")
    page.wait_for_function("() => Object.keys(_fteState.overrides).length === 1", timeout=15000)

    # Installatieparameters (masterdata-editor in het paneel).
    page.locator("#fteKpiStaffedSub .fte-kpi-link").click()
    page.wait_for_function("() => _fteDrawerMode === 'master'", timeout=15000)
    expect(page.locator("#fteDockFoot .fte-dock-whatif button:has-text('Terugzetten')")).to_be_attached()
    page.keyboard.press("Escape")
    page.wait_for_function("() => _fteDrawerMode === null", timeout=5000)

    # Combineerformulier: terugzetten vanuit de voet werkt, en de voet volgt.
    page.click("#fteCombineBtn")
    page.wait_for_function("() => _fteDrawerMode === 'combine'", timeout=10000)
    expect(page.locator("#fteDockFoot .fte-dock-whatif button:has-text('Terugzetten')")).to_be_attached()
    with page.expect_response(lambda r: "/api/fte/norm_overrides" in r.url and r.ok):
        page.click("#fteDockFoot .fte-dock-whatif button:has-text('Terugzetten')")
    page.wait_for_function("() => Object.keys(_fteState.overrides).length === 0", timeout=15000)
    page.wait_for_function("() => !document.querySelector('#fteDockFoot .fte-dock-whatif')", timeout=5000)
    page.keyboard.press("Escape")
    assert page.js_errors == []


def test_f7_kpi_caveat_counts_a_combination_without_rate(inspector_page):
    """Audit F7: een actieve combinatie met FTE maar zonder tarief telt stil
    € 0 mee; de KPI-kanttekening telt haar mee, net als de rij-badge."""
    page = inspector_page
    base_url = page.server["base_url"]
    before = requests.get(base_url + "/api/master_data/labor_rates", timeout=TIMEOUT).json()
    if (before.get("value") or {}).get("default"):
        pytest.skip("de store heeft een default-tarief; dan is er geen stille € 0")
    pair = requests.get(base_url + "/api/fte", timeout=TIMEOUT).json()["fte"]["lines"]
    pair = [str(l["key"]) for l in pair if l["category"] == "machine" and sum(l["hours"].values()) > 0][:2]
    combo_id = "COMBI_AUDIT_F7"
    try:
        _put_combo(base_url, combo_id, pair, "AUDIT_NO_RATE")
        assert requests.post(base_url + "/api/fte/combinations", json={"active_combinations": [combo_id]}, timeout=TIMEOUT).ok
        _open_workbench(page)
        report = page.evaluate(
            """(id) => { const note = document.querySelector('#fteKpiCostSub .fte-kpi-note');
                        const badges = document.querySelectorAll('#fteWbBody button[title^="Geen loontarief"]').length;
                        const comboBadge = !!document.querySelector(`#fteWbBody tr[data-fte-row='group:${id}'] button[title^="Geen loontarief"]`);
                        return { note: note ? note.textContent : null, badges, comboBadge,
                                 predicate: _fteState.data.lines.filter(_fteIsSilentZero).length }; }""",
            combo_id)
        assert report["comboBadge"] is True, report
        assert report["note"] is not None, report
        assert int(report["note"].split()[0]) == report["badges"] == report["predicate"], report
    finally:
        _drop_combo(base_url, combo_id)
