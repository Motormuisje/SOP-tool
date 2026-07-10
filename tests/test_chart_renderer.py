import pytest

from modules import chart_renderer


pytestmark = pytest.mark.no_fixture


def _assert_png(buf):
    data = buf.getvalue()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(data) > 1_000


def test_chart_renderer_short_labels_formats_periods_and_preserves_bad_values():
    assert chart_renderer._short_labels(["2025-01", "2025-12", "bad"]) == [
        "Jan-25",
        "Dec-25",
        "bad",
    ]


def test_chart_renderer_financial_metrics_returns_png():
    _assert_png(
        chart_renderer.financial_metrics(
            ["2025-01", "2025-02"],
            {
                "TURNOVER": [1000.0, 1200.0],
                "COST OF GOODS": [400.0, 450.0],
                "GROSS MARGIN": [600.0, 750.0],
                "INVENTORY VALUE": [300.0, 280.0],
            },
        )
    )


def test_chart_renderer_roce_components_and_bar_return_pngs():
    periods = ["2025-01", "2025-02"]
    _assert_png(
        chart_renderer.roce_components(
            periods,
            {
                "EBIT": [100.0, 150.0],
                "CAPITAL INVESTMENT": [1000.0, 900.0],
                "OPERATIONAL CASHFLOW": [200.0, 250.0],
            },
        )
    )
    _assert_png(chart_renderer.roce_bar(periods, [0.1, 0.2], average=0.15))


def test_chart_renderer_inventory_charts_return_pngs():
    periods = ["2025-01", "2025-02"]
    _assert_png(
        chart_renderer.top10_overstocks(
            periods,
            [
                {"name": "MAT-1", "values": [100.0, 120.0]},
                {"name": "MAT-2", "values": [50.0, 20.0]},
            ],
        )
    )
    _assert_png(
        chart_renderer.inventory_quality(
            periods,
            {
                "under": [1.0, 2.0],
                "safety": [2.0, 3.0],
                "strategic": [3.0, 4.0],
                "normal": [4.0, 5.0],
                "overstock": [5.0, 6.0],
            },
            actual_stock=[10.0, 11.0],
            cogs=[20.0, 22.0],
        )
    )


def test_chart_renderer_mom_scatter_returns_png_for_empty_and_populated_inputs():
    _assert_png(chart_renderer.mom_scatter([], [], [], []))
    _assert_png(
        chart_renderer.mom_scatter(
            ["MAT-1", "MAT-2"],
            [100.0, -50.0],
            [120.0, 20.0],
            ["C6EFCE", "FFC7CE"],
        )
    )
