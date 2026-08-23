import time


def _seed_one_run(live_server, page):
    page.goto(live_server + "/")
    page.click('button:has-text("Run now")')
    page.wait_for_url(live_server + "/")

    for _ in range(20):
        page.goto(live_server + "/")
        if page.query_selector(".table-scroll td"):
            return
        time.sleep(0.25)
    raise AssertionError("run did not appear in the dashboard table in time")


def test_dashboard_table_is_grid_at_desktop_width(live_server, page):
    page.goto(live_server + "/")

    thead_display = page.eval_on_selector(
        '.table-scroll thead, .table-scroll tr:first-child',
        "el => getComputedStyle(el).display",
    )
    assert thead_display != "none"


def test_dashboard_table_becomes_cards_at_narrow_width(live_server, page):
    _seed_one_run(live_server, page)

    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/")

    label_content = page.eval_on_selector(
        '.table-scroll td',
        "el => getComputedStyle(el, '::before').content",
    )
    assert label_content not in (None, "none", '""')


def test_no_horizontal_overflow_on_dashboard_at_narrow_viewport(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/")

    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    inner_width = page.evaluate("window.innerWidth")
    assert scroll_width <= inner_width


def test_no_horizontal_overflow_on_guide_at_narrow_viewport(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/guide")

    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    inner_width = page.evaluate("window.innerWidth")
    assert scroll_width <= inner_width


# ── Issue #83: last card row missing internal row separators ──────────────────

def test_last_card_row_has_row_separators_at_narrow_width(live_server, page):
    """Mobile: the last tr (card) must show border-bottom between its td cells."""
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/guide")

    border = page.eval_on_selector(
        ".table-scroll tr:last-child td:not(:last-child)",
        "el => getComputedStyle(el).borderBottomWidth",
    )
    assert border != "0px", f"expected row separator in last mobile card, got {border!r}"


def test_last_card_last_cell_has_no_bottom_border_at_narrow_width(live_server, page):
    """Mobile: the final td in the last card must NOT have a bottom border (the tr border covers it)."""
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/guide")

    border = page.eval_on_selector(
        ".table-scroll tr:last-child td:last-child",
        "el => getComputedStyle(el).borderBottomWidth",
    )
    assert border == "0px", f"expected no bottom border on last cell of last card, got {border!r}"


def test_intermediate_card_rows_have_row_separators_at_narrow_width(live_server, page):
    """Mobile: non-last tr cards also have internal row separators (regression guard)."""
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/guide")

    border = page.eval_on_selector(
        ".table-scroll tr:not(:last-child) td:not(:last-child)",
        "el => getComputedStyle(el).borderBottomWidth",
    )
    assert border != "0px", f"expected row separator in non-last mobile card, got {border!r}"


def test_last_row_cells_have_no_bottom_border_at_desktop_width(live_server, page):
    """Desktop: the last table row must have no td bottom border (table container provides the edge)."""
    page.set_viewport_size({"width": 1024, "height": 800})
    page.goto(live_server + "/guide")

    border = page.eval_on_selector(
        ".table-scroll tr:last-child td",
        "el => getComputedStyle(el).borderBottomWidth",
    )
    assert border == "0px", f"expected no bottom border on last row at desktop, got {border!r}"


def test_intermediate_row_cells_have_bottom_border_at_desktop_width(live_server, page):
    """Desktop: non-last td cells must have a bottom border as row separators."""
    page.set_viewport_size({"width": 1024, "height": 800})
    page.goto(live_server + "/guide")

    border = page.eval_on_selector(
        ".table-scroll tr:not(:last-child) td",
        "el => getComputedStyle(el).borderBottomWidth",
    )
    assert border != "0px", f"expected row separator on non-last row at desktop, got {border!r}"


def test_last_dashboard_card_row_has_row_separators_at_narrow_width(live_server, page):
    """Mobile: same fix holds on the dashboard history table (multi-column rows)."""
    _seed_one_run(live_server, page)
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/")

    border = page.eval_on_selector(
        ".table-scroll tr:last-child td:not(:last-child)",
        "el => getComputedStyle(el).borderBottomWidth",
    )
    assert border != "0px", f"expected row separator in last dashboard card, got {border!r}"
