"""Masterdata in de app — import + bewerken via de Config-tab."""

import math

import pytest
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


def _ensure_store(page, base_url, golden_fixture_path):
    status = requests.get(base_url + "/api/master_data", timeout=60).json()
    if status.get("exists"):
        return
    with golden_fixture_path.open("rb") as workbook:
        resp = requests.post(base_url + "/api/master_data/import",
                             files={"file": (golden_fixture_path.name, workbook)},
                             timeout=300)
    assert resp.ok and resp.json().get("success"), resp.text


def test_sales_price_edit_recomputes_revenue(browser_page, golden_fixture_path):
    """Prijs per eenheid is het invoerveld; omzet = prijs x volume.

    Ongewijzigde rijen moeten EXACT round-trippen (de afgeronde weergave mag
    de opgeslagen data niet herschrijven)."""
    page = browser_page
    base_url = page.server["base_url"]
    page.reload(wait_until="networkidle")
    _open_config(page)
    _ensure_store(page, base_url, golden_fixture_path)

    original = requests.get(base_url + "/api/master_data/sales_prices",
                            timeout=60).json()["value"]
    keys = sorted(original.keys())
    assert len(keys) >= 2, "test heeft minstens 2 prijsregels nodig"
    target, untouched = keys[0], keys[1]
    orig_vol = float(original[target]["volume_2025"])
    orig_rev = float(original[target]["ex_works_revenue"])
    orig_price = orig_rev / orig_vol

    try:
        # 1) Round-trip zonder wijziging: opslaan verandert niets.
        page.evaluate("() => openMasterDatasetModal('sales_prices')")
        page.wait_for_selector("#masterDatasetModal tr[data-master-key]", timeout=30000)
        with page.expect_response(
                lambda r: "/api/master_data/sales_prices" in r.url
                and r.request.method == "PATCH" and r.ok, timeout=60000):
            page.evaluate("() => saveMasterDataset('sales_prices')")
        after = requests.get(base_url + "/api/master_data/sales_prices",
                             timeout=60).json()["value"]
        assert after == original, "opslaan zonder wijziging herschreef de data"

        # 2) Prijs verdubbelen via het prijsveld; omzet-weergave rekent live mee.
        page.evaluate("() => openMasterDatasetModal('sales_prices')")
        page.wait_for_selector("#masterDatasetModal tr[data-master-key]", timeout=30000)
        shown = page.evaluate(
            """([key, newPrice]) => {
                const row = document.querySelector(`#masterDatasetModal tr[data-master-key="${key}"]`);
                const input = row.querySelector('[data-master-col="price"] .master-edit');
                input.value = String(newPrice);
                input.dispatchEvent(new Event('input', { bubbles: true }));
                return row.querySelector('[data-master-col="revenue_display"]').textContent;
            }""",
            [target, round(orig_price * 2, 4)],
        )
        assert shown not in ("", "—")  # live herrekend, geen foutstreepje
        with page.expect_response(
                lambda r: "/api/master_data/sales_prices" in r.url
                and r.request.method == "PATCH" and r.ok, timeout=60000):
            page.evaluate("() => saveMasterDataset('sales_prices')")

        after = requests.get(base_url + "/api/master_data/sales_prices",
                             timeout=60).json()["value"]
        new_rev = float(after[target]["ex_works_revenue"])
        assert abs(new_rev - 2 * orig_rev) / (2 * orig_rev) < 1e-3, \
            f"omzet niet ~verdubbeld: {orig_rev} -> {new_rev}"
        assert float(after[target]["volume_2025"]) == orig_vol  # volume onaangetast
        assert after[untouched] == original[untouched]  # buurman exact gelijk
    finally:
        requests.patch(base_url + "/api/master_data/sales_prices",
                       json={"value": original}, timeout=120)
        page.evaluate("() => { const m = document.getElementById('masterDatasetModal'); if (m) m.remove(); }")
    assert page.js_errors == []


def test_locale_parser_rejects_malformed_numbers(browser_page, golden_fixture_path):
    """Gemelde bug (checklist A6): '3000,5,6' werd stil 300056.

    De parser moet echte groepen-van-drie eisen en het hele veld moet een
    getal zijn; de masterdata-grid weigert het veld dan met een NL-fout."""
    page = browser_page
    base_url = page.server["base_url"]
    page.reload(wait_until="networkidle")
    _open_config(page)
    _ensure_store(page, base_url, golden_fixture_path)

    cases = {
        "3000,5,6": None, "12abc": None, "abc": None, "12.34,5": None,
        "1.234,5": 1234.5, "1,234.5": 1234.5, "1.234.567": 1234567,
        "1,234,567": 1234567, "2,5": 2.5, "2.5": 2.5, "-1.234,5": -1234.5,
        "1e3": 1000, "1,23": 1.23,
    }
    got = page.evaluate(
        "(keys) => Object.fromEntries(keys.map(k => [k, parseLocaleNumber(k)]))",
        list(cases))
    for raw, expected in cases.items():
        actual = got[raw]
        if expected is None:
            assert actual is None or (isinstance(actual, float) and math.isnan(actual)),                 f"{raw!r} moest NaN zijn, was {actual}"
        else:
            assert actual == pytest.approx(expected), f"{raw!r}: {actual}"

    # Volledige A6-flow: foutieve lotgrootte in de veiligheidsvoorraad-grid
    # levert een foutmelding op en er wordt NIETS opgeslagen.
    version_before = requests.get(base_url + "/api/master_data", timeout=60).json()["version"]
    original = requests.get(base_url + "/api/master_data/safety_stock",
                            timeout=60).json()["value"]
    page.evaluate("() => openMasterDatasetModal('safety_stock')")
    page.wait_for_selector("#masterDatasetModal tr[data-master-key]", timeout=30000)
    error = page.evaluate(
        """() => {
            const row = document.querySelector('#masterDatasetModal tr[data-master-key]');
            row.querySelector('[data-master-col="lot_size"] .master-edit').value = '3000,5,6';
            return (collectMasterDataset('safety_stock').error || '');
        }""")
    assert "Ongeldig getal" in error
    page.evaluate("() => document.getElementById('masterDatasetModal').remove()")
    status = requests.get(base_url + "/api/master_data", timeout=60).json()
    assert status["version"] == version_before
    after = requests.get(base_url + "/api/master_data/safety_stock",
                         timeout=60).json()["value"]
    assert after == original
    assert page.js_errors == []
