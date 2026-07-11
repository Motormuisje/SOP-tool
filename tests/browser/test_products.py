"""Fase 3 — dynamische producten: add via Config-tab card, verify in the
planning results, then delete (shared session-scoped server; the test cleans
up after itself so later tests see the baseline)."""

import requests
from playwright.sync_api import expect

MN = "900000001"


def _open_config(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.evaluate("() => window.showTab && window.showTab('config')")
    page.wait_for_selector("#addedProductsTbody", timeout=15000)


def test_add_and_delete_dynamic_product(browser_page):
    page = browser_page
    base_url = page.server["base_url"]
    page.reload(wait_until="networkidle")
    _open_config(page)

    try:
        # --- add ---
        page.evaluate("() => openProductModal()")
        page.wait_for_selector("#productModal #prodNumber", timeout=15000)
        page.fill("#prodNumber", MN)
        page.fill("#prodName", "Browsertest product")
        page.fill("#prodFlatVolume", "150")
        with page.expect_response(
                lambda r: "/api/products/added" in r.url
                and r.request.method == "POST" and r.ok,
                timeout=180000):
            page.click("#btnSaveProduct")

        # Card table lists the product; modal closed.
        page.wait_for_selector(f'tr[data-added-product="{MN}"]', timeout=60000)
        assert page.locator("#productModal").count() == 0

        # The product flowed through the pipeline into the planning results.
        page.wait_for_function(
            """(mn) => {
                const rows = (state.results && state.results['01. Demand forecast']) || [];
                return rows.some(r => String(r.material_number) === mn);
            }""",
            arg=MN,
            timeout=60000,
        )

        # Server truth: session store carries the product.
        listing = requests.get(base_url + "/api/products/added", timeout=60).json()
        assert [p["material_number"] for p in listing["added_products"]] == [MN]

        # --- delete (confirm dialog) ---
        page.once("dialog", lambda d: d.accept())
        with page.expect_response(
                lambda r: f"/api/products/added/{MN}" in r.url
                and r.request.method == "DELETE" and r.ok,
                timeout=180000):
            page.click(f'tr[data-added-product="{MN}"] button:has-text("Verwijderen")')

        page.wait_for_function(
            """(mn) => {
                const rows = (state.results && state.results['01. Demand forecast']) || [];
                return !rows.some(r => String(r.material_number) === mn);
            }""",
            arg=MN,
            timeout=60000,
        )
        listing = requests.get(base_url + "/api/products/added", timeout=60).json()
        assert listing["added_products"] == []
        assert page.js_errors == []
    finally:
        # Never leave the shared server with the product installed.
        try:
            requests.delete(base_url + f"/api/products/added/{MN}", timeout=300)
        except requests.RequestException:
            pass


def test_add_rejects_workbook_collision_with_dutch_error(browser_page):
    page = browser_page
    base_url = page.server["base_url"]
    # Pick a real workbook material number via the API.
    listing = requests.get(base_url + "/api/products/added", timeout=60).json()
    existing = listing["materials"][0]["number"]

    resp = requests.post(base_url + "/api/products/added", json={
        "material_number": existing, "name": "Botsing", "product_type": "bulk",
        "flat_volume": 1.0,
    }, timeout=60)
    assert resp.status_code == 400
    assert "bestaat al in het bronbestand" in resp.json()["error"]
