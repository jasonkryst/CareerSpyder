def test_nav_toggle_hidden_at_desktop_width(live_server, page):
    page.goto(live_server + "/")

    assert page.is_hidden("#nav-toggle")


def test_nav_toggle_opens_and_closes_menu_at_narrow_width(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/")

    assert page.is_visible("#nav-toggle")
    assert page.get_attribute("#nav-toggle", "aria-expanded") == "false"

    page.click("#nav-toggle")
    assert page.get_attribute("#nav-toggle", "aria-expanded") == "true"
    assert page.is_visible('nav[aria-label="Main"] a[href="/jobs"]')

    page.click("#nav-toggle")
    assert page.get_attribute("#nav-toggle", "aria-expanded") == "false"


def test_escape_key_closes_open_menu(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/")

    page.click("#nav-toggle")
    assert page.get_attribute("#nav-toggle", "aria-expanded") == "true"

    page.keyboard.press("Escape")
    assert page.get_attribute("#nav-toggle", "aria-expanded") == "false"


def test_clicking_outside_closes_open_menu(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/")

    page.click("#nav-toggle")
    assert page.get_attribute("#nav-toggle", "aria-expanded") == "true"

    page.mouse.click(10, 10)
    assert page.get_attribute("#nav-toggle", "aria-expanded") == "false"


def test_nav_links_reachable_by_keyboard_when_open(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/")

    page.click("#nav-toggle")
    page.click('nav[aria-label="Main"] a[href="/jobs"]')
    page.wait_for_url("**/jobs")
