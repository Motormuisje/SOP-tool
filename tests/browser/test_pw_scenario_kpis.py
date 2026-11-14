"""Scenariovergelijking op kerncijfers, in de browser.

Een planner slaat de stand op als scenario, verhoogt de vraag van één product
en vergelijkt daarna 'opgeslagen' met 'huidige stand'. De tabel moet de
kerncijfers van beide kolommen tonen en het verschil precies zoals de API het
berekent: dezelfde getallen die het dashboard uit dezelfde consolidatie haalt.

Draait op een eigen server: deze module slaat scenario's op en bewerkt cellen.
"""

import pytest
import requests
from playwright.sync_api import expect

DEMAND = "01. Demand forecast"


@pytest.fixture
def app_page(page, own_server):
    js_errors = []
    page.on("console", lambda m: js_errors.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource:") else None)
    response = page.goto(own_server["base_url"], wait_until="networkidle")
    assert response is not None and response.ok
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=120000)
    page.wait_for_function("() => !!state.results", timeout=300000)
    # De scenarioknoppen staan in de werkbalk van het tabblad Planning.
    page.evaluate("() => showTab('planning')")
    page.js_errors = js_errors
    page.server = own_server
    return page


def _demand_cell(base_url):
    results = requests.get(base_url + "/api/results", timeout=300).json()["results"]
    for row in results[DEMAND]:
        for period, value in sorted(row["values"].items())[1:]:
            if value and value > 10:
                return row["material_number"], row.get("aux_column") or "", period, value
    raise AssertionError("geen bruikbare vraagcel")


def test_compare_button_appears_with_one_saved_scenario_and_compares_with_the_current_plan(app_page):
    page = app_page
    base_url = page.server["base_url"]
    assert page.evaluate("() => document.getElementById('scenarioCompareBtn').style.display") == "none"

    saved = requests.post(base_url + "/api/scenarios/save", json={"name": "Basis KPI"}, timeout=300).json()
    assert saved.get("success"), saved
    page.evaluate("() => refreshScenarioDrop()")
    expect(page.locator("#scenarioCompareBtn")).to_be_visible(timeout=10000)

    material, aux, period, value = _demand_cell(base_url)
    edit = requests.post(base_url + "/api/update_volume", json={
        "line_type": DEMAND, "material_number": material, "aux_column": aux,
        "period": period, "new_value": value * 3,
    }, timeout=300).json()
    assert edit.get("success"), edit

    page.click("#scenarioCompareBtn")
    expect(page.locator("#kpiCompareSection")).to_be_visible(timeout=10000)
    # Standaard aangevinkt: het laatst opgeslagen scenario en de huidige stand.
    assert page.evaluate("() => _kpiSelected()") == [saved["scenario_id"], "current"]
    # Met één opgeslagen scenario is er geen celvergelijking van twee scenario's.
    expect(page.locator("#cellCompareSection")).to_be_hidden()

    with page.expect_response(lambda r: "/api/scenarios/kpis" in r.url and r.ok) as resp:
        page.click("#kpiRunBtn")
    api = resp.value.json()
    page.wait_for_selector('#kpiResult tr[data-kpi-row="ebit"]', timeout=15000)

    base, live = api["columns"]
    assert base["name"] == "Basis KPI" and live["is_current"] is True
    assert live["compatibility"] == "gelijk"
    assert live["deltas"]["total_demand"] > 0          # de vraag is verhoogd
    assert any("planbewerkingen" in c for c in live["input_changes"])

    header = page.inner_text("#kpiResult thead")
    assert "Basis KPI" in header and "Huidige stand" in header
    ebit_row = page.inner_text('#kpiResult tr[data-kpi-row="ebit"]')
    assert "€" in ebit_row
    if abs(live["deltas"]["ebit"]) > 1e-6:
        assert ("+" in ebit_row) or ("−" in ebit_row)

    page.click("#kpiResult >> text=Meer cijfers")
    page.wait_for_selector('#kpiResult tr[data-kpi-row="total_demand"]', timeout=5000)
    assert page.evaluate("() => !!document.getElementById('kpiChart')")
    assert page.js_errors == []


def test_compare_needs_two_to_four_columns(app_page):
    page = app_page
    page.evaluate("() => refreshScenarioDrop()")
    expect(page.locator("#scenarioCompareBtn")).to_be_visible(timeout=10000)
    page.click("#scenarioCompareBtn")
    expect(page.locator("#kpiCompareSection")).to_be_visible(timeout=10000)

    page.evaluate("""() => document.querySelectorAll('#kpiPick input[data-kpi-col]')
                       .forEach(el => { el.checked = false; })""")
    page.evaluate("() => _kpiSyncBase()")
    assert page.evaluate("() => document.getElementById('kpiRunBtn').disabled") is True

    page.evaluate("""() => { const boxes = document.querySelectorAll('#kpiPick input[data-kpi-col]');
                             boxes[0].checked = true; boxes[boxes.length - 1].checked = true; _kpiSyncBase(); }""")
    assert page.evaluate("() => document.getElementById('kpiRunBtn').disabled") is False
    assert page.js_errors == []


def _results(base_url):
    return requests.get(base_url + "/api/results", timeout=300).json()["results"]


def test_whatif_builder_demand_driver_is_one_undoable_edit(app_page):
    """+50 % for one product family over three months changes exactly those
    cells by a factor 1.5; one Undo takes the whole driver back."""
    page = app_page
    base_url = page.server["base_url"]
    before = _results(base_url)
    periods = sorted(before[DEMAND][0]["values"])[1:4]
    family = next(r["product_family"] for r in before[DEMAND]
                  if r.get("product_family") and any((r["values"].get(p) or 0) > 0 for p in periods))

    page.click("#scenarioBuildBtn")
    page.select_option("#sbScope", "family")
    page.select_option("#sbFamily", family)
    page.fill("#sbPct", "50")
    page.select_option("#sbFrom", periods[0])
    page.select_option("#sbTo", periods[-1])
    page.dispatch_event("#sbPct", "input")
    expect(page.locator("#sbPreview")).to_contain_text("cel(len) veranderen")
    with page.expect_response(lambda r: "/api/update_volume_bulk" in r.url and r.ok):
        page.click("#sbApply")
    expect(page.locator("#scenarioBuilderModal")).to_have_count(0, timeout=60000)

    after = _results(base_url)
    old = {(r["material_number"], r["aux_column"]): r for r in before[DEMAND]}
    changed = 0
    for row in after[DEMAND]:
        prev = old[(row["material_number"], row["aux_column"])]
        for p, v in row["values"].items():
            expected = prev["values"][p] * 1.5 if (row.get("product_family") == family and p in periods) else prev["values"][p]
            assert v == pytest.approx(expected, rel=1e-9, abs=1e-9), (row["material_number"], p)
            changed += abs(expected - prev["values"][p]) > 1e-9
    assert changed > 0

    undo = requests.post(base_url + "/api/undo", timeout=300).json()
    assert undo.get("success"), undo
    restored = {(r["material_number"], r["aux_column"]): r["values"] for r in _results(base_url)[DEMAND]}
    for key, row in old.items():
        assert restored[key] == pytest.approx(row["values"]), key
    assert page.js_errors == []


def test_whatif_builder_machine_driver_sets_availability_for_the_chosen_months(app_page):
    page = app_page
    base_url = page.server["base_url"]
    before = _results(base_url)
    avail_rows = before["09. Available capacity"]
    row = next(r for r in avail_rows if any((v or 0) > 0 for v in r["values"].values()))
    periods = sorted(row["values"])[2:4]

    page.click("#scenarioBuildBtn")
    page.check('input[name="sbType"][value="machine"]')
    page.select_option("#sbMachineSel", str(row["material_number"]))
    page.fill("#sbAvail", "0")
    page.select_option("#sbFrom", periods[0])
    page.select_option("#sbTo", periods[-1])
    page.dispatch_event("#sbAvail", "input")
    expect(page.locator("#sbPreview")).to_contain_text("maand(en)")
    with page.expect_response(lambda r: "/api/update_volume_bulk" in r.url and r.ok):
        page.click("#sbApply")
    expect(page.locator("#scenarioBuilderModal")).to_have_count(0, timeout=60000)

    after = next(r for r in _results(base_url)["09. Available capacity"]
                 if r["material_number"] == row["material_number"])
    for p, v in after["values"].items():
        assert v == pytest.approx(0.0 if p in periods else row["values"][p]), p
    requests.post(base_url + "/api/undo", timeout=300)
    assert page.js_errors == []


def test_whatif_builder_refuses_empty_or_impossible_input(app_page):
    page = app_page
    page.click("#scenarioBuildBtn")
    page.fill("#sbPct", "-150")
    page.dispatch_event("#sbPct", "input")
    expect(page.locator("#sbPreview")).to_contain_text("onder nul")
    assert page.evaluate("() => document.getElementById('sbApply').disabled") is True
    page.fill("#sbPct", "abc")
    page.dispatch_event("#sbPct", "input")
    assert page.evaluate("() => document.getElementById('sbApply').disabled") is True
    periods = page.evaluate("() => state.periods")
    page.select_option("#sbFrom", periods[-1])
    page.select_option("#sbTo", periods[0])
    page.fill("#sbPct", "10")
    page.dispatch_event("#sbPct", "input")
    expect(page.locator("#sbPreview")).to_contain_text("beginmaand ligt na de eindmaand")
    assert page.js_errors == []
