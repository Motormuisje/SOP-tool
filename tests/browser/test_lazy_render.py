from playwright.sync_api import expect


# Lazy per-tab rendering (ui/templates/index.html): on a cold start only the active
# tab renders. Planning and Values Planning are deferred (via state.pendingRender)
# and render the first time their tab is opened. This keeps the main thread from
# freezing on load (the cold start otherwise builds ~57k DOM nodes at once).


def test_cold_start_defers_planning_and_values(browser_page):
    page = browser_page

    state = page.evaluate(
        """() => ({
            activeTab: _activeTabName,
            hasResults: !!state.results,
            planRows: document.querySelectorAll('#planBody tr[data-material]').length,
            vpRows: document.querySelectorAll('#vpBody tr[data-material]').length,
            pendingPlanning: !!(state.pendingRender && state.pendingRender.planning),
            pendingValues: !!(state.pendingRender && state.pendingRender.values),
        })"""
    )
    assert state["activeTab"] == "dashboard"
    assert state["hasResults"] is True
    # Heavy tables are not in the DOM until their tab is opened.
    assert state["planRows"] == 0
    assert state["vpRows"] == 0
    assert state["pendingPlanning"] is True
    assert state["pendingValues"] is True
    assert page.js_errors == []


def test_opening_tab_renders_deferred_table(browser_page):
    page = browser_page

    page.locator("button.tab-btn[onclick*=\"showTab('planning'\"]").first.click()
    expect(page.locator("#planBody tr[data-material]").nth(0)).to_be_visible(timeout=60000)
    assert page.evaluate("document.querySelectorAll('#planBody tr[data-material]').length") > 0
    # Pending flag cleared after first render.
    assert page.evaluate("!!(state.pendingRender && state.pendingRender.planning)") is False

    page.locator("button.tab-btn[onclick*=\"showTab('values'\"]").first.click()
    expect(page.locator("#vpBody tr[data-material]").nth(0)).to_be_visible(timeout=60000)
    assert page.evaluate("document.querySelectorAll('#vpBody tr[data-material]').length") > 0
    assert page.js_errors == []
