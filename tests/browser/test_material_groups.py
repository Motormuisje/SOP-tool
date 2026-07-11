"""Materiaalgroepen — browser tests.

Start met de regressietest voor de gemelde bug: een materiaal-scope op de
planningstabel werd stilletjes gewist door updateEditBadge() (bij 0 edits)
en overleefde de filtergeschiedenis ("←") niet, waardoor bv. een
linetype-wijziging het filter leek te breken.
"""

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
