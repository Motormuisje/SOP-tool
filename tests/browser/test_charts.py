import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.browser


def _open_tab(page, name):
    page.locator(f"button.tab-btn[onclick*=\"showTab('{name}'\"]").click()
    expect(page.locator(f"#{name}-tab")).to_be_visible()


def _canvas_stats(page, selector):
    page.wait_for_function(
        """selector => {
            const canvas = document.querySelector(selector);
            return Boolean(
                canvas
                && canvas.width > 0
                && canvas.height > 0
                && window.Chart
                && window.Chart.getChart(canvas)
            );
        }""",
        arg=selector,
        timeout=60000,
    )
    return page.locator(selector).evaluate(
        """canvas => {
            const ctx = canvas.getContext('2d');
            const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
            let visible = 0;
            let colored = 0;
            for (let i = 0; i < pixels.length; i += 4) {
                const r = pixels[i];
                const g = pixels[i + 1];
                const b = pixels[i + 2];
                const a = pixels[i + 3];
                if (a > 0) visible += 1;
                if (a > 0 && (r < 245 || g < 245 || b < 245)) colored += 1;
            }
            return {
                width: canvas.width,
                height: canvas.height,
                visible,
                colored,
            };
        }"""
    )


def _assert_canvas_has_real_pixels(page, selector):
    stats = _canvas_stats(page, selector)
    assert stats["width"] >= 100
    assert stats["height"] >= 100
    assert stats["visible"] > 0
    assert stats["colored"] > 50


def test_dashboard_charts_render_nonblank_canvases(browser_page):
    page = browser_page

    _open_tab(page, "dashboard")

    for selector in ("#financialChart", "#utilChart", "#fteChart", "#roceChart"):
        _assert_canvas_has_real_pixels(page, selector)

    assert page.js_errors == []


def test_values_and_machine_tabs_render_nonblank_charts(browser_page):
    page = browser_page

    _open_tab(page, "values")
    _assert_canvas_has_real_pixels(page, "#finChart")

    _open_tab(page, "capacity")
    _assert_canvas_has_real_pixels(page, "#machChartSlot1 canvas")
    _assert_canvas_has_real_pixels(page, "#machChartSlot2 canvas")

    assert page.js_errors == []


def _require_chartjs(page):
    if not page.evaluate("() => typeof window.Chart !== 'undefined'"):
        pytest.skip("Chart.js vendor asset not served (ui/static/vendor missing)")


def test_chart_zoom_affordances_are_injected(browser_page):
    """Fase 1.1: a 'Vergroot' button is injected next to every PNG export
    button. DOM-only, independent of chart pixel rendering."""
    page = browser_page
    _open_tab(page, "dashboard")
    _require_chartjs(page)

    # Panels carry data-panel-id (not id); count injected zoom buttons there.
    count = page.evaluate(
        """() => Array.from(document.querySelectorAll(
                    '[data-panel-id="panel-fin-metrics"] button'))
                    .filter(b => /Vergroot/.test(b.textContent)).length"""
    )
    assert count >= 1


def test_chart_zoom_modal_opens_and_closes(browser_page):
    """Fase 1.1: enlarging a chart opens a modal holding a live Chart instance
    and closes on Escape. Uses a throwaway Chart so it is independent of the
    app's (environment-flaky) dashboard chart rendering, exercising the zoom
    logic itself: openChartZoomForCanvas, the display toggle, and Escape."""
    page = browser_page
    _require_chartjs(page)

    # Build a minimal Chart on a temp canvas, then zoom it.
    page.evaluate(
        """() => {
            const c = document.createElement('canvas');
            c.id = 'zoomTestSrc';
            c.width = 200; c.height = 120;
            document.body.appendChild(c);
            // eslint-disable-next-line no-new
            new Chart(c.getContext('2d'), {
                type: 'bar',
                data: { labels: ['a','b'], datasets: [{ data: [1,2] }] },
                options: { animation: false, responsive: false }
            });
            openChartZoomForCanvas(c, 'Test grafiek');
        }"""
    )

    modal = page.locator("#chartZoomModal")
    expect(modal).to_be_visible()
    assert page.evaluate(
        "() => Boolean(window.Chart.getChart(document.querySelector('#chartZoomCanvas')))"
    )
    expect(page.locator("#chartZoomTitle")).to_have_text("Test grafiek")

    page.keyboard.press("Escape")
    expect(modal).to_be_hidden()
    assert page.js_errors == []
