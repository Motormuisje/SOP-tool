"""Grafiek-analyse: het "Analyse"-zijpaneel in de chart-zoom modal.

Deterministic via page.evaluate + the window._lastChartAnalysis test hook;
panels are driven programmatically (openChartZoomForCanvas / openChartAnalysis
/ _analysisApplySelection) so the tests are independent of pixel positions.
"""

from playwright.sync_api import expect


def _open_dashboard(page):
    expect(page.locator("#busyOverlay")).to_have_class("hidden", timeout=60000)
    page.evaluate("() => window.showTab && window.showTab('dashboard')")
    page.wait_for_function(
        "() => typeof Chart !== 'undefined' && !!Chart.getChart(document.getElementById('financialChart'))",
        timeout=60000,
    )


def _zoom_and_open_analysis(page, canvas_id):
    page.evaluate(
        """(cid) => openChartZoomForCanvas(document.getElementById(cid), 'test')""",
        canvas_id,
    )
    page.wait_for_selector("#chartZoomModal", state="visible", timeout=15000)
    page.evaluate("() => openChartAnalysis()")
    page.wait_for_function(
        "() => !!window._lastChartAnalysis || "
        "(document.getElementById('chartAnalysisHeadline') || {}).textContent"
        "?.includes('Geen noemenswaardige')",
        timeout=30000,
    )


def test_analyse_button_visibility_registered_vs_not(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_dashboard(page)

    # Unregistered throwaway chart: knop verborgen.
    page.evaluate(
        """() => {
            let c = document.getElementById('throwawayAnalysis');
            if (!c) {
                c = document.createElement('canvas');
                c.id = 'throwawayAnalysis';
                document.querySelector('.card').appendChild(c);
            }
            new Chart(c.getContext('2d'), {type: 'line',
                data: {labels: ['a','b'], datasets: [{label: 'x', data: [1, 2]}]}});
            openChartZoomForCanvas(c, 'throwaway');
        }"""
    )
    assert not page.locator("#chartZoomAnalyseBtn").is_visible()
    page.evaluate("() => closeChartZoom()")

    # Registered chart: knop zichtbaar.
    page.evaluate(
        "() => openChartZoomForCanvas(document.getElementById('financialChart'), 'fin')")
    assert page.locator("#chartZoomAnalyseBtn").is_visible()
    page.evaluate("() => closeChartZoom()")
    assert page.js_errors == []


def test_financial_chart_turnover_contributors_reconcile(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_dashboard(page)
    _zoom_and_open_analysis(page, "financialChart")

    # Kies expliciet de Turnover-dataset op een bekend aangrenzend paar.
    page.evaluate(
        """() => {
            const ds = _zoomChart.data.datasets.findIndex(d => d.label === 'Turnover');
            return _analysisApplySelection(ds, 1, 2);  // eerste twee echte perioden
        }"""
    )
    page.wait_for_function(
        "() => window._lastChartAnalysis && window._lastChartAnalysis.iA === 1",
        timeout=30000,
    )
    check = page.evaluate(
        """() => {
            const a = window._lastChartAnalysis;
            const head = document.getElementById('chartAnalysisHeadline').textContent;
            const table = document.getElementById('chartAnalysisTableHost').textContent;
            return {
                head, rows: a.rows.length,
                reconciles: Math.abs(a.contributorSum - a.totalDelta)
                    <= Math.max(1, 0.005 * Math.abs(a.totalDelta)),
                hasSum: table.includes('Som bijdragen'),
                hasMove: table.includes('Beweging in grafiek'),
            };
        }"""
    )
    assert "Omzet" in check["head"] and "van" in check["head"], check["head"]
    assert check["rows"] >= 1
    assert check["reconciles"], check
    assert check["hasSum"] and check["hasMove"]
    assert page.js_errors == []


def test_derived_metric_shows_component_breakdown(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_dashboard(page)
    _zoom_and_open_analysis(page, "financialChart")

    page.evaluate(
        """() => {
            const ds = _zoomChart.data.datasets.findIndex(d => d.label === 'EBIT');
            return _analysisApplySelection(ds, 1, 2);
        }"""
    )
    page.wait_for_function(
        "() => document.getElementById('chartAnalysisNotes')"
        ".textContent.includes('afgeleide metriek')",
        timeout=30000,
    )
    table = page.evaluate(
        "() => document.getElementById('chartAnalysisTableHost').textContent")
    assert "EBITDA" in table and "Afschrijvingen" in table
    assert page.js_errors == []


def test_two_point_custom_segment_updates_headline(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_dashboard(page)
    _zoom_and_open_analysis(page, "financialChart")

    info = page.evaluate(
        """() => {
            const ds = _zoomChart.data.datasets.findIndex(d => d.label === 'Turnover');
            _analysisApplySelection(ds, 1, 4);  // niet-aangrenzend segment
            return { la: _zoomChart.data.labels[1], lb: _zoomChart.data.labels[4],
                     wired: typeof _zoomChart.options.onClick === 'function' };
        }"""
    )
    assert info["wired"], "onClick two-point wiring missing on zoom clone"
    page.wait_for_function(
        "() => window._lastChartAnalysis && window._lastChartAnalysis.iB === 4",
        timeout=30000,
    )
    head = page.evaluate(
        "() => document.getElementById('chartAnalysisHeadline').textContent")
    seg = page.evaluate(
        "() => document.getElementById('chartAnalysisSegmentSel').selectedOptions[0].textContent")
    assert info["la"] in head and info["lb"] in head, (head, info)
    assert "Eigen selectie" in seg
    assert page.js_errors == []


def test_analysis_resets_on_close_and_rezoom(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_dashboard(page)
    _zoom_and_open_analysis(page, "financialChart")
    assert page.locator("#chartAnalysisPanel").is_visible()

    page.evaluate("() => closeChartZoom()")
    page.evaluate(
        "() => openChartZoomForCanvas(document.getElementById('financialChart'), 'fin2')")
    state = page.evaluate(
        """() => ({
            visible: document.getElementById('chartAnalysisPanel').style.display !== 'none',
            content: document.getElementById('chartAnalysisPanel').innerHTML,
        })"""
    )
    assert not state["visible"] and state["content"] == ""
    page.evaluate("() => closeChartZoom()")
    assert page.js_errors == []
