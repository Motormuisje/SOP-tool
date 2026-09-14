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
