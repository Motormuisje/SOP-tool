from playwright.sync_api import expect


def test_mom_detail_table_sorts_by_delta(browser_page):
    page = browser_page

    page.locator("button.tab-btn[onclick*=\"showTab('mom'\"]").click()
    expect(page.locator("#mom-tab")).to_be_visible()
    expect(page.locator("#momBody tr").nth(0)).to_be_visible(timeout=60000)

    delta_header = page.locator("#momHead .mom-sort-btn").nth(6)
    delta_header.click()
    first_pass = page.locator("#momBody tr td:nth-child(7)").all_inner_texts()[:5]

    delta_header.click()
    second_pass = page.locator("#momBody tr td:nth-child(7)").all_inner_texts()[:5]

    assert first_pass
    assert second_pass
    assert first_pass != second_pass
    assert page.js_errors == []
