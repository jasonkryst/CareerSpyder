def test_no_horizontal_overflow_at_narrow_viewport(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/sources")

    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    inner_width = page.evaluate("window.innerWidth")

    assert scroll_width <= inner_width
