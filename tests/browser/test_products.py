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
        page.evaluate("() => _wizGoto(2)")  # C4c: volume staat op stap 2
        page.fill("#prodFlatVolume", "150")
        page.evaluate("() => _wizGoto(4)")  # opslaan staat op stap 4
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


def test_sourcing_selector_toggles_sections(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_config(page)
    page.evaluate("() => openProductModal()")
    page.wait_for_selector("#productModal #prodSourcing", timeout=15000)

    # C4c: sourcing staat op stap 1, de secties op stap 3 — de test vult
    # dummy-identificatie in en wisselt per keuze naar stap 3 voor de checks.
    page.fill("#prodNumber", "999999999")
    page.fill("#prodName", "toggle-test")

    # Default: purchased -> purchase fields visible, production sections hidden.
    assert page.locator("#prodSourcing").input_value() == "purchased"
    page.evaluate("() => _wizGoto(3)")
    assert page.locator("#prodWrapMoq").is_visible()
    assert not page.locator("#prodSectionRouting").is_visible()
    assert not page.locator("#prodSectionBomParent").is_visible()
    assert not page.locator("#prodWrapPap").is_visible()

    page.evaluate("() => _wizGoto(1)")
    page.select_option("#prodSourcing", "produced")
    page.evaluate("() => _wizGoto(3)")
    assert page.locator("#prodSectionRouting").is_visible()
    assert page.locator("#prodSectionBomParent").is_visible()
    assert not page.locator("#prodWrapMoq").is_visible()
    assert not page.locator("#prodWrapLeadTime").is_visible()

    page.evaluate("() => _wizGoto(1)")
    page.select_option("#prodSourcing", "mix")
    page.evaluate("() => _wizGoto(3)")
    assert page.locator("#prodSectionRouting").is_visible()
    assert page.locator("#prodWrapMoq").is_visible()
    assert page.locator("#prodWrapPap").is_visible()

    page.evaluate("() => document.getElementById('productModal').remove()")
    assert page.js_errors == []


def test_add_produced_product_end_to_end(browser_page):
    """Sourcing 'produced': component + routing via the dynamic row editors;
    the result must carry a production plan and NO purchase rows."""
    page = browser_page
    base_url = page.server["base_url"]
    mn = "900000042"
    page.reload(wait_until="networkidle")
    _open_config(page)

    listing = requests.get(base_url + "/api/products/added", timeout=60).json()
    component = listing["materials"][0]["number"]
    machine = listing["machines"][0]

    try:
        page.evaluate("() => openProductModal()")
        page.wait_for_selector("#productModal #prodSourcing", timeout=15000)
        page.fill("#prodNumber", mn)
        page.fill("#prodName", "Browsertest geproduceerd")
        page.select_option("#prodSourcing", "produced")
        page.evaluate("() => _wizGoto(2)")
        page.fill("#prodFlatVolume", "90")
        page.evaluate("() => _wizGoto(3)")
        page.fill("#prodSalesPrice", "10")
        page.click("#prodSectionBomParent button")
        page.fill("#prodBomParentTbody .prod-link-ref", component)
        page.fill("#prodBomParentTbody .prod-link-qty", "2")
        page.click("#prodSectionRouting button")
        page.fill("#prodRoutingTbody .prod-rout-wc", machine)
        page.fill("#prodRoutingTbody .prod-rout-bq", "1000")
        page.fill("#prodRoutingTbody .prod-rout-st", "8")
        page.evaluate("() => _wizGoto(4)")
        with page.expect_response(
                lambda r: "/api/products/added" in r.url
                and r.request.method == "POST" and r.ok,
                timeout=180000):
            page.click("#btnSaveProduct")

        page.wait_for_function(
            """(mn) => {
                const prod = (state.results && state.results['06. Production plan']) || [];
                return prod.some(r => String(r.material_number) === mn);
            }""",
            arg=mn,
            timeout=60000,
        )
        branch = page.evaluate(
            """(mn) => ({
                production: ((state.results['06. Production plan'] || [])
                    .filter(r => String(r.material_number) === mn)).length,
                purchase: ((state.results['06. Purchase receipt'] || [])
                    .filter(r => String(r.material_number) === mn)).length,
            })""",
            mn,
        )
        assert branch["production"] == 1 and branch["purchase"] == 0, branch

        # Financial flow into the UI: the value overlay carries the revenue
        # (sales price 10 × volume 90 = 900 per period).
        revenue = page.evaluate(
            """(mn) => {
                const rows = (state.valueResults
                    && state.valueResults['01. Demand forecast']) || [];
                const row = rows.find(r => String(r.material_number) === mn);
                if (!row) return null;
                return Object.values(row.values);
            }""",
            mn,
        )
        assert revenue, "added product missing from value overlay in the UI"
        assert all(abs(v - 900.0) < 1e-6 for v in revenue), revenue
        assert page.js_errors == []
    finally:
        try:
            requests.delete(base_url + f"/api/products/added/{mn}", timeout=300)
        except requests.RequestException:
            pass


def test_products_card_refreshes_on_session_switch(browser_page):
    """De productenkaart toont per-sessie data: na een sessiewissel moet de
    kaart de producten van de NIEUWE sessie tonen, niet die van de vorige."""
    page = browser_page
    base_url = page.server["base_url"]
    sid_orig = page.server["session_id"]
    mn = "900000055"
    sid_b = None
    try:
        # Instantie B aanmaken VÓÓR het product bestaat: B blijft leeg.
        snap = requests.post(base_url + "/api/sessions/snapshot",
                             json={"name": "Wisseltest B"}, timeout=120)
        assert snap.ok, snap.text
        sid_b = snap.json()["session"]["id"]

        resp = requests.post(base_url + "/api/products/added", json={
            "material_number": mn, "name": "Wisseltest product",
            "product_type": "other", "sourcing": "purchased",
            "flat_volume": 10.0,
        }, timeout=300)
        assert resp.ok, resp.text

        page.reload(wait_until="networkidle")
        _open_config(page)
        page.evaluate("() => loadAddedProducts()")
        page.wait_for_selector(f'tr[data-added-product="{mn}"]', timeout=30000)

        # Wissel naar B via de UI: kaart moet leeg worden (B heeft niets).
        page.evaluate("(sid) => switchSession(sid)", sid_b)
        page.wait_for_function(
            "(sid) => state.activeSessionId === sid", arg=sid_b, timeout=180000)
        page.wait_for_function(
            """() => {
                const tbody = document.getElementById('addedProductsTbody');
                return tbody && tbody.textContent.includes('Nog geen producten');
            }""",
            timeout=60000,
        )
        assert page.locator(f'tr[data-added-product="{mn}"]').count() == 0

        # Terug naar de oorspronkelijke sessie: product weer zichtbaar.
        page.evaluate("(sid) => switchSession(sid)", sid_orig)
        page.wait_for_function(
            "(sid) => state.activeSessionId === sid", arg=sid_orig, timeout=180000)
        page.wait_for_selector(f'tr[data-added-product="{mn}"]', timeout=60000)
        assert page.js_errors == []
    finally:
        try:
            requests.post(base_url + "/api/sessions/switch",
                          json={"session_id": sid_orig}, timeout=300)
            requests.delete(base_url + f"/api/products/added/{mn}", timeout=300)
            if sid_b:
                requests.delete(base_url + f"/api/sessions/{sid_b}", timeout=60)
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
