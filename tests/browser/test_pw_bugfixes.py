"""Regressietests bij drie bugs die de browsersuite van augustus 2026 vond.

Elke test hoort te FALEN op de code van vóór de fix. Ze staan bewust apart van
de gebiedsmodules: zo is bij een latere refactor meteen zichtbaar dat het om
vastgelegd gedrag gaat en niet om dekking-om-de-dekking.

1. `collectMasterDataset` liet lead time 0 vallen bij het opslaan van de
   inkoopdataset. `get_lead_time()` viel dan terug op de VBA-default 1 — die
   alleen bedoeld is voor materialen die NIET in de Purchase sheet staan — en
   het inkoopplan schoof stil een maand op.
2. `_VALID_TABS` miste 'fte', waardoor het tabblad Capaciteit & FTE na een
   herlaad terugviel op het dashboard.
3. `setBusy(false)` annuleerde de geplande requestAnimationFrame van
   `setBusy(true)` niet. Bij een taak binnen één frame zette die de klasse
   'show' terug en ving een onzichtbare overlay ~140 ms lang alle kliks op.
4. Gevonden tijdens het schrijven van test 1: `_masterCellValue` geeft
   `undefined` terug als het invoerveld ontbreekt, maar de inkooptak
   controleerde alleen op `=== null`. Dat werd verderop `Math.round(undefined)`
   = NaN, kwam als JSON-null bij de server aan en blies daar `int(None)` op.
   De oude `if (lead > 0)` maskeerde dit door zulke rijen stil te laten vallen.
"""

import pytest
import requests
from playwright.sync_api import expect


pytestmark = pytest.mark.browser


def _open_config(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.evaluate("() => window.showTab && window.showTab('config')")
    page.wait_for_selector("#masterDataStatus", timeout=15000)


def _ensure_store(base_url, golden_fixture_path):
    status = requests.get(base_url + "/api/master_data", timeout=60).json()
    if status.get("exists"):
        return status
    with golden_fixture_path.open("rb") as workbook:
        resp = requests.post(
            base_url + "/api/master_data/import",
            files={"file": (golden_fixture_path.name, workbook)},
            timeout=600,
        )
    assert resp.ok and resp.json().get("success"), resp.text
    return requests.get(base_url + "/api/master_data", timeout=60).json()


def _purchase(base_url):
    body = requests.get(base_url + "/api/master_data/purchase", timeout=120).json()
    assert "error" not in body, body
    return body["value"]


def test_saving_purchase_grid_keeps_lead_time_zero(own_server, page, golden_fixture_path):
    """Lead time 0 betekent 'direct beschikbaar' en is een geldige waarde.

    De oude code deed `if (lead > 0)` bij het verzamelen, waardoor die
    materialen uit lead_times verdwenen. Omdat get_lead_time() voor een
    ontbrekend materiaal 1 teruggeeft, werd 0 stilzwijgend 1: het inkoopplan
    schoof een maand op zonder enig signaal. Deze test drukt op Opslaan ZONDER
    iets te wijzigen — dat alleen al was genoeg om de data te verliezen.
    """
    base_url = own_server["base_url"]
    page.goto(base_url, wait_until="networkidle")
    _open_config(page)
    _ensure_store(base_url, golden_fixture_path)

    before = _purchase(base_url)
    zeros = sorted(m for m, v in (before.get("lead_times") or {}).items() if int(v) == 0)
    if not zeros:
        pytest.skip("geen materiaal met lead time 0 in deze fixture")

    page.evaluate("() => loadMasterDataStatus()")
    page.wait_for_function(
        "() => document.querySelectorAll('#masterDatasetButtons button').length > 0",
        timeout=30000,
    )
    page.evaluate("() => openMasterDatasetModal('purchase')")
    page.wait_for_function(
        "() => document.querySelectorAll('#masterDatasetBody tr[data-master-key]').length > 0",
        timeout=30000,
    )

    # De rijen staan er; de 0-waarden moeten ook in het grid zichtbaar zijn.
    shown = page.evaluate(
        """(mats) => {
            const out = {};
            for (const row of document.querySelectorAll('#masterDatasetBody tr[data-master-key]')) {
                if (!mats.includes(row.dataset.masterKey)) continue;
                const cell = row.querySelector('[data-master-col="lead"]');
                out[row.dataset.masterKey] = (cell.textContent || '').trim();
            }
            return out;
        }""",
        zeros,
    )
    assert shown, "materialen met lead time 0 staan niet in het grid"

    with page.expect_response(
        lambda r: "/api/master_data/purchase" in r.url and r.request.method == "PATCH"
    ) as saved:
        page.evaluate("() => saveMasterDataset('purchase')")
    assert saved.value.ok, saved.value.text()
    page.wait_for_load_state("networkidle")

    after = _purchase(base_url)
    missing = [m for m in zeros if m not in (after.get("lead_times") or {})]
    assert missing == [], (
        f"{len(missing)} van {len(zeros)} materialen verloren hun lead time 0 "
        f"bij opslaan; get_lead_time() maakt er nu 1 van: {missing[:5]}"
    )
    for material in zeros:
        assert int(after["lead_times"][material]) == 0, (
            material, after["lead_times"][material])

    assert page.evaluate("() => window.__jsErrors || []") == []


def test_negative_lead_time_is_rejected_with_a_reason(own_server, page, golden_fixture_path):
    """Een negatieve lead time is onzin en werd vroeger stil weggegooid (en dus
    ook 1). Nu moet hij worden geweigerd MET uitleg, zodat de invoerfout bij de
    gebruiker blijft in plaats van in de cijfers te verdwijnen."""
    base_url = own_server["base_url"]
    page.goto(base_url, wait_until="networkidle")
    _open_config(page)
    _ensure_store(base_url, golden_fixture_path)
    before = _purchase(base_url)

    page.evaluate(
        """() => {
            window.__alerts = [];
            window.alert = (msg) => { window.__alerts.push(String(msg)); };
        }"""
    )
    page.evaluate("() => loadMasterDataStatus()")
    page.wait_for_function(
        "() => document.querySelectorAll('#masterDatasetButtons button').length > 0",
        timeout=30000,
    )
    page.evaluate("() => openMasterDatasetModal('purchase')")
    page.wait_for_function(
        "() => document.querySelectorAll('#masterDatasetBody tr[data-master-key]').length > 0",
        timeout=30000,
    )

    # Via het echte invoerveld: de cel bevat een <input class="master-edit">.
    # De waarde overschrijven met textContent zou dat veld slopen (en test dan
    # iets anders dan de gebruiker ooit doet).
    material = page.evaluate(
        """() => {
            const row = document.querySelector('#masterDatasetBody tr[data-master-key]');
            const input = row.querySelector('[data-master-col="lead"] .master-edit');
            if (!input) throw new Error('geen invoerveld in de lead-cel');
            input.value = '-3';
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            return row.dataset.masterKey;
        }"""
    )

    requests_seen = []
    page.on("request", lambda req: requests_seen.append((req.method, req.url)))
    page.evaluate("() => saveMasterDataset('purchase')")
    page.wait_for_function("() => (window.__alerts || []).length > 0", timeout=30000)

    alerts = page.evaluate("() => window.__alerts")
    assert any("negatief" in a.lower() for a in alerts), alerts
    assert any(material in a for a in alerts), alerts

    patched = [u for m, u in requests_seen
               if m == "PATCH" and "/api/master_data/purchase" in u]
    assert patched == [], "er ging tóch een PATCH uit na een geweigerde invoer"
    assert _purchase(base_url)["lead_times"] == before["lead_times"]


def test_unreadable_lead_cell_is_refused_client_side(own_server, page, golden_fixture_path):
    """Een cel zonder invoerveld levert `undefined`, niet `null`.

    De inkooptak controleerde alleen op `=== null`; `undefined` glipte erdoor en
    werd Math.round(undefined) = NaN. JSON maakt daar null van, en de server
    struikelde met `int() argument must be ... not 'NoneType'`. Dat is een
    serverfout op een invoerprobleem — het hoort in de UI geweigerd te worden,
    met de naam van het materiaal erbij.
    """
    base_url = own_server["base_url"]
    page.goto(base_url, wait_until="networkidle")
    _open_config(page)
    _ensure_store(base_url, golden_fixture_path)
    before = _purchase(base_url)

    page.evaluate(
        """() => {
            window.__alerts = [];
            window.alert = (msg) => { window.__alerts.push(String(msg)); };
        }"""
    )
    page.evaluate("() => loadMasterDataStatus()")
    page.wait_for_function(
        "() => document.querySelectorAll('#masterDatasetButtons button').length > 0",
        timeout=30000,
    )
    page.evaluate("() => openMasterDatasetModal('purchase')")
    page.wait_for_function(
        "() => document.querySelectorAll('#masterDatasetBody tr[data-master-key]').length > 0",
        timeout=30000,
    )

    material = page.evaluate(
        """() => {
            const row = document.querySelector('#masterDatasetBody tr[data-master-key]');
            const cell = row.querySelector('[data-master-col="lead"]');
            cell.textContent = '';          // sloopt het invoerveld -> undefined
            return row.dataset.masterKey;
        }"""
    )

    seen = []
    page.on("request", lambda req: seen.append((req.method, req.url)))
    page.evaluate("() => saveMasterDataset('purchase')")
    page.wait_for_function("() => (window.__alerts || []).length > 0", timeout=30000)

    alerts = page.evaluate("() => window.__alerts")
    assert any("Ongeldig getal" in a for a in alerts), alerts
    assert any(material in a for a in alerts), alerts
    # Geen serverfout: de PATCH mag niet eens vertrekken.
    assert [u for m, u in seen
            if m == "PATCH" and "/api/master_data/purchase" in u] == []
    assert not any("NoneType" in a for a in alerts), (
        "de invoerfout bereikte de server alsnog", alerts)
    assert _purchase(base_url)["lead_times"] == before["lead_times"]


def test_fte_tab_is_remembered_across_a_reload(browser_page):
    """Het tabblad Capaciteit & FTE moet na een herlaad open blijven.

    _VALID_TABS miste 'fte', waardoor _restoreUiPrefs() de opgeslagen waarde als
    onbekend verwierp en de gebruiker op het dashboard belandde — elke herlaad
    opnieuw, midden in het werk.
    """
    page = browser_page
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)

    page.evaluate("() => showTab('fte')")
    expect(page.locator("#fte-tab")).to_be_visible(timeout=60000)
    assert page.evaluate("() => _activeTabName") == "fte"
    assert page.evaluate("() => _VALID_TABS.has('fte')") is True

    stored = page.evaluate(
        """() => {
            for (const k of Object.keys(localStorage)) {
                try {
                    const v = JSON.parse(localStorage.getItem(k));
                    if (v && typeof v === 'object' && 'activeTab' in v) return v.activeTab;
                } catch (e) { /* geen json */ }
            }
            return null;
        }"""
    )
    assert stored == "fte", f"activeTab is niet als 'fte' bewaard: {stored!r}"

    page.reload(wait_until="networkidle")
    expect(page.locator("#fte-tab")).to_be_visible(timeout=60000)
    assert page.evaluate("() => _activeTabName") == "fte"
    expect(page.locator("#dashboard-tab")).to_be_hidden()

    # Opruimen: terug naar dashboard, anders start de volgende test op fte.
    page.evaluate("() => showTab('dashboard')")
    assert page.js_errors == []


def test_busy_overlay_does_not_reappear_after_a_sub_frame_task(browser_page):
    """setBusy(true) plant de 'show'-klasse in een requestAnimationFrame.

    Eindigt de taak binnen datzelfde frame, dan vuurde die RAF ná setBusy(false)
    en zette 'show' terug. De overlay is dan onzichtbaar (want .hidden komt er
    140 ms later overheen) maar heeft pointer-events:auto — hij vangt in dat
    gaatje alle kliks op. Klassiek 'mijn klik deed niets'.
    """
    page = browser_page
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)

    result = page.evaluate(
        """async () => {
            const overlay = document.getElementById('busyOverlay');
            setBusy(true, 'test');
            setBusy(false);                      // binnen hetzelfde frame
            const direct = overlay.className;
            // twee frames verder: een niet-geannuleerde RAF is dan gevuurd
            await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
            const box = overlay.getBoundingClientRect();
            return {
                direct,
                after: overlay.className,
                hasShow: overlay.classList.contains('show'),
                pointerEvents: getComputedStyle(overlay).pointerEvents,
                opacity: Number(getComputedStyle(overlay).opacity),
                covers: box.width > 0 && box.height > 0,
            };
        }"""
    )

    assert result["hasShow"] is False, (
        f"'show' kwam terug na de RAF: {result['after']!r} — de overlay vangt "
        f"kliks (pointer-events={result['pointerEvents']})"
    )
    assert result["pointerEvents"] == "none", result
    assert result["opacity"] == 0.0, result

    # En de UI is daarna gewoon klikbaar: het element onder de muis is niet de overlay.
    top = page.evaluate(
        """() => {
            const el = document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2);
            return el ? el.id || el.tagName : null;
        }"""
    )
    assert top != "busyOverlay", "de overlay ligt nog over de pagina heen"

    assert page.js_errors == []
