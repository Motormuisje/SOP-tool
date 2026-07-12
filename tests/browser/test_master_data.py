"""Masterdata in de app — import + bewerken via de Config-tab."""

import requests
from playwright.sync_api import expect

MN_RENAME = "Golden hernoemd (browsertest)"


def _open_config(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.evaluate("() => window.showTab && window.showTab('config')")
    page.wait_for_selector("#masterDataStatus", timeout=15000)


def test_master_data_import_and_edit_flow(browser_page, golden_fixture_path):
    page = browser_page
    base_url = page.server["base_url"]
    page.reload(wait_until="networkidle")
    _open_config(page)

    status = requests.get(base_url + "/api/master_data", timeout=60).json()
    if not status.get("exists"):
        # UI toont de lege toestand vóór de import.
        page.wait_for_function(
            "() => document.getElementById('masterDataStatus')"
            ".textContent.includes('Nog geen masterdata')",
            timeout=15000,
        )
        with golden_fixture_path.open("rb") as workbook:
            resp = requests.post(
                base_url + "/api/master_data/import",
                files={"file": (golden_fixture_path.name, workbook)},
                timeout=300,
            )
        body = resp.json()
        assert resp.ok and body.get("success"), body
        assert body["counts"]["materials"] > 0

    # Originele naam van het eerste materiaal vastleggen (voor herstel).
    first = requests.get(base_url + "/api/master_data/materials",
                         timeout=60).json()["value"][0]
    original_key, original_name = str(first["material_number"]), first["name"]

    # UI-status na import: versie + datasetknoppen.
    page.evaluate("() => loadMasterDataStatus()")
    page.wait_for_function(
        "() => document.getElementById('masterDataStatus')"
        ".textContent.includes('Masterdata in de app')",
        timeout=15000,
    )
    assert page.locator("#masterDatasetButtons button").count() >= 8

    # Materialen-modal openen en de eerste naam bewerken.
    page.evaluate("() => openMasterDatasetModal('materials')")
    page.wait_for_selector("#masterDatasetModal tr[data-master-key]", timeout=30000)
    key = page.evaluate(
        """(name) => {
            const row = document.querySelector('#masterDatasetModal tr[data-master-key]');
            row.querySelector('[data-master-col="name"] input').value = name;
            return row.dataset.masterKey;
        }""",
        MN_RENAME,
    )
    version_before = requests.get(base_url + "/api/master_data", timeout=60).json()["version"]
    with page.expect_response(
            lambda r: "/api/master_data/materials" in r.url
            and r.request.method == "PATCH" and r.ok,
            timeout=60000):
        page.evaluate("() => saveMasterDataset('materials')")

    status = requests.get(base_url + "/api/master_data", timeout=60).json()
    assert status["version"] == version_before + 1
    materials = requests.get(base_url + "/api/master_data/materials",
                             timeout=60).json()["value"]
    renamed = next(m for m in materials if str(m["material_number"]) == str(key))
    assert renamed["name"] == MN_RENAME
    assert page.locator("#masterDatasetModal").count() == 0  # modal sluit na opslaan

    # Gemelde bug: 'ik verander de naam en herbereken, maar de naam wordt
    # niet geüpdatet'. De actieve sessie is een WERKBOEK-sessie; de app-
    # masterdata moet die bij herberekening overlayen (app = bron van
    # waarheid). Herbereken en controleer de naam in de resultaten.
    try:
        calc = requests.post(base_url + "/api/calculate", json={
            "planning_month": "2025-12", "months_actuals": 11,
            "months_forecast": 12}, timeout=300)
        assert calc.ok and calc.json().get("success"), calc.text
        rows = requests.get(base_url + "/api/results", timeout=120).json()["results"]
        names = {str(r["material_number"]): r["material_name"]
                 for r in rows.get("01. Demand forecast", [])}
        if str(key) in names:  # materiaal heeft een forecastregel
            assert names[str(key)] == MN_RENAME, \
                "hernoemde masterdata kwam niet door in de herberekening"
        else:  # anders: controleer op een willekeurige regel van dit materiaal
            found = [r for lt in rows.values() for r in lt
                     if str(r["material_number"]) == str(key)]
            assert found and found[0]["material_name"] == MN_RENAME
    finally:
        # Exacte originele naam terugzetten zodat de gedeelde server geen
        # drift opbouwt (volgende herberekening gebruikt weer het origineel).
        materials = requests.get(base_url + "/api/master_data/materials",
                                 timeout=60).json()["value"]
        for m in materials:
            if str(m["material_number"]) == original_key:
                m["name"] = original_name
        requests.patch(base_url + "/api/master_data/materials",
                       json={"value": materials}, timeout=120)
    assert str(key) == original_key  # de grid bewerkte de eerste rij
    assert page.js_errors == []
