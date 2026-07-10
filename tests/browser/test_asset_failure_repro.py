from pathlib import Path

from playwright.sync_api import expect


BLOCKED_ASSET_FRAGMENTS = (
    "cdn.tailwindcss.com",
    "cdnjs.cloudflare.com/ajax/libs/Chart.js",
    "cdn.jsdelivr.net/npm/chartjs-plugin-datalabels",
)


def test_external_asset_failure_still_renders_app(page, server):
    """Old CDN failures should not produce an unstyled restart view."""

    def route_asset(route):
        url = route.request.url
        if any(fragment in url for fragment in BLOCKED_ASSET_FRAGMENTS):
            route.abort()
            return
        route.continue_()

    page.route("**/*", route_asset)
    response = page.goto(server["base_url"], wait_until="networkidle")

    assert response is not None
    assert response.ok

    expect(page.locator("#busyOverlay")).to_be_hidden()
    expect(page.locator("button.tab-btn[onclick*=\"showTab('planning'\"]")).to_be_visible()
    artifact_dir = Path("test-results")
    artifact_dir.mkdir(exist_ok=True)
    screenshot_path = artifact_dir / "external-asset-failure-guard.png"
    page.screenshot(path=str(screenshot_path), full_page=True)

    assert screenshot_path.exists()
    assert page.evaluate("() => typeof window.Chart") == "function"
