import time


def _seed_one_run(live_server, page):
    page.goto(live_server + "/")
    page.click('button:has-text("Run now")')
    page.wait_for_url(live_server + "/")

    for _ in range(20):
        page.goto(live_server + "/history")
        if page.query_selector(".table-scroll td"):
            return
        time.sleep(0.25)
    raise AssertionError("run did not appear in history in time")


def test_history_table_is_grid_at_desktop_width(live_server, page):
    page.goto(live_server + "/history")

    thead_display = page.eval_on_selector(
        '.table-scroll thead, .table-scroll tr:first-child',
        "el => getComputedStyle(el).display",
    )
    assert thead_display != "none"


def test_history_table_becomes_cards_at_narrow_width(live_server, page):
    _seed_one_run(live_server, page)

    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/history")

    label_content = page.eval_on_selector(
        '.table-scroll td',
        "el => getComputedStyle(el, '::before').content",
    )
    assert label_content not in (None, "none", '""')


def test_no_horizontal_overflow_on_history_at_narrow_viewport(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/history")

    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    inner_width = page.evaluate("window.innerWidth")
    assert scroll_width <= inner_width


def test_no_horizontal_overflow_on_guide_at_narrow_viewport(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/guide")

    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    inner_width = page.evaluate("window.innerWidth")
    assert scroll_width <= inner_width
