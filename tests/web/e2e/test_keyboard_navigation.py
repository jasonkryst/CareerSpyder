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
