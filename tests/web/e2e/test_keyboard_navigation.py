def test_tab_order_reaches_skip_link_first(live_server, page):
    page.goto(live_server + "/")

    page.keyboard.press("Tab")

    assert page.evaluate("document.activeElement.className") == "skip-link"


def test_tab_order_reaches_theme_toggle_after_skip_link_and_nav(live_server, page):
    page.goto(live_server + "/")

    # skip-link, then the 4 nav links (Dashboard/History/Sources/Settings), then the toggle
    for _ in range(6):
        page.keyboard.press("Tab")

    assert page.evaluate("document.activeElement.id") == "theme-toggle"


def test_settings_tabs_navigate_and_mark_current_tab(live_server, page):
    page.goto(live_server + "/settings/email")

    assert page.get_attribute('nav[aria-label="Settings tabs"] a[href="/settings/email"]', "aria-current") == "page"
    assert page.get_attribute('nav[aria-label="Settings tabs"] a[href="/settings/data"]', "aria-current") is None

    page.click('nav[aria-label="Settings tabs"] a[href="/settings/data"]')
    page.wait_for_url("**/settings/data")

    assert page.get_attribute('nav[aria-label="Settings tabs"] a[href="/settings/data"]', "aria-current") == "page"
    assert page.get_attribute('nav[aria-label="Settings tabs"] a[href="/settings/email"]', "aria-current") is None
