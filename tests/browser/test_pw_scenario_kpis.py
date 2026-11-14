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
