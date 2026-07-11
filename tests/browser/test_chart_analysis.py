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


def test_demand_trend_contributors_reconcile_with_rounding(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_dashboard(page)
    page.wait_for_function(
        "() => !!Chart.getChart(document.getElementById('demandTrendChart'))",
        timeout=30000,
    )
    _zoom_and_open_analysis(page, "demandTrendChart")
    page.wait_for_function("() => !!window._lastChartAnalysis", timeout=30000)
    check = page.evaluate(
        """() => {
            const a = window._lastChartAnalysis;
            return {
                head: document.getElementById('chartAnalysisHeadline').textContent,
                reconciles: Math.abs(a.contributorSum - a.totalDelta)
                    <= Math.max(1, 0.005 * Math.abs(a.totalDelta)),
            };
        }"""
    )
    assert "Totale vraag" in check["head"] or "Geen noemenswaardige" in check["head"]
    assert check["reconciles"], check
    assert page.js_errors == []


def test_util_chart_shows_factor_split_and_product_section(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_dashboard(page)
    page.wait_for_function(
        "() => !!Chart.getChart(document.getElementById('utilChart'))",
        timeout=30000,
    )
    _zoom_and_open_analysis(page, "utilChart")
    page.wait_for_function(
        "() => document.getElementById('chartAnalysisTableHost')"
        ".textContent.includes('Effect benodigde uren')",
        timeout=30000,
    )
    table = page.evaluate(
        "() => document.getElementById('chartAnalysisTableHost').textContent")
    assert "Effect beschikbare capaciteit" in table
    # Productsectie of expliciete geen-detail-melding, met eerlijkheidsnotitie.
    assert ("productbewegingen op deze machine" in table
            or "Geen productbewegingen" in table
            or "Productdetail niet beschikbaar" in table), table
    if "productbewegingen op deze machine" in table:
        assert "niet uren" in table
    assert page.js_errors == []


def test_roce_ratio_split_sums_exactly(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_dashboard(page)
    page.wait_for_function(
        "() => !!Chart.getChart(document.getElementById('roceChart'))",
        timeout=30000,
    )
    _zoom_and_open_analysis(page, "roceChart")
    page.wait_for_function("() => !!window._lastChartAnalysis", timeout=30000)
    check = page.evaluate(
        """() => {
            const a = window._lastChartAnalysis;
            const table = document.getElementById('chartAnalysisTableHost').textContent;
            // Dashboard rounds EBIT/kapitaal to whole euros but ROCE to 6
            // decimals; the identity split is exact on the rounded inputs, so
            // allow display-precision tolerance (0.01 pp) vs the plotted line.
            return {
                table,
                exact: Math.abs(a.contributorSum - a.totalDelta) < 0.01,
            };
        }"""
    )
    assert "Effect EBIT" in check["table"], check["table"]
    assert "Effect geïnvesteerd kapitaal" in check["table"]
    assert check["exact"], "ratio-splitsing moet optellen binnen weergaveprecisie"
    assert page.js_errors == []


def test_component_drill_and_back(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_dashboard(page)
    _zoom_and_open_analysis(page, "financialChart")
    page.evaluate(
        """() => {
            const ds = _zoomChart.data.datasets.findIndex(d => d.label === 'Gross Margin');
            return _analysisApplySelection(ds, 1, 2);
        }"""
    )
    page.wait_for_function(
        "() => document.getElementById('chartAnalysisTableHost')"
        ".textContent.includes('Omzet')",
        timeout=30000,
    )
    # Drill into the Turnover component -> product contributors verschijnen.
    page.evaluate("() => _analysisDrillComponent('TURNOVER')")
    page.wait_for_function(
        "() => document.getElementById('chartAnalysisTableHost')"
        ".textContent.includes('Terug naar grafiekanalyse')",
        timeout=30000,
    )
    head = page.evaluate(
        "() => document.getElementById('chartAnalysisHeadline').textContent")
    assert "Omzet" in head
    # Terug herstelt de componentweergave.
    page.evaluate("() => _analysisDrillBack()")
    page.wait_for_function(
        "() => !document.getElementById('chartAnalysisTableHost')"
        ".textContent.includes('Terug naar grafiekanalyse')",
        timeout=30000,
    )
    assert page.js_errors == []


def test_inventory_quality_bucket_decomposition(browser_page):
    page = browser_page
    page.reload(wait_until="networkidle")
    _open_dashboard(page)
    page.wait_for_function(
        "() => !!Chart.getChart(document.getElementById('invQualityChart'))",
        timeout=30000,
    )
    _zoom_and_open_analysis(page, "invQualityChart")
    page.wait_for_function("() => !!window._lastChartAnalysis", timeout=30000)
    check = page.evaluate(
        """() => {
            const a = window._lastChartAnalysis;
            return {
                head: document.getElementById('chartAnalysisHeadline').textContent,
                rows: a.rows.length,
                reconciles: Math.abs(a.contributorSum - a.totalDelta)
                    <= Math.max(1, 0.005 * Math.abs(a.totalDelta)),
            };
        }"""
    )
    assert check["rows"] >= 1 or "Geen noemenswaardige" in check["head"]
    assert check["reconciles"], check
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
