_NARROW_CAP_PX = 960   # 60rem × 16px — default max-width
_WIDE_CAP_PX   = 1280  # 80rem × 16px — wide-screen max-width (min-width: 80rem)


def test_no_horizontal_overflow_at_narrow_viewport(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/sources")

    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    inner_width = page.evaluate("window.innerWidth")

    assert scroll_width <= inner_width


def test_no_horizontal_overflow_at_narrow_viewport_jobs(live_server, page):
    """The jobs filter bar (issue #254) is the densest in the app -- the one
    most likely to overflow a phone-width viewport if the grouping/stacking
    CSS regresses."""
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/jobs")

    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    inner_width = page.evaluate("window.innerWidth")

    assert scroll_width <= inner_width


def test_jobs_filter_groups_stack_full_width_at_narrow_viewport(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/jobs")

    bar_width = page.evaluate("document.querySelector('.filter-bar').getBoundingClientRect().width")
    group_widths = page.evaluate(
        "Array.from(document.querySelectorAll('.filter-group')).map(g => g.getBoundingClientRect().width)"
    )
    assert group_widths, "expected at least one .filter-group on the jobs filter bar"
    for width in group_widths:
        assert width >= bar_width - 1  # each group spans the full bar width when stacked


def test_content_expands_on_wide_viewport(live_server, page):
    """main should exceed 60rem width when the viewport is at least 80rem wide."""
    page.set_viewport_size({"width": 1400, "height": 900})
    page.goto(live_server + "/")

    width = page.evaluate("document.querySelector('main').getBoundingClientRect().width")
    assert width > _NARROW_CAP_PX


def test_content_capped_on_medium_viewport(live_server, page):
    """main should not exceed 60rem when viewport is between 60rem and 80rem."""
    page.set_viewport_size({"width": 1100, "height": 800})
    page.goto(live_server + "/")

    width = page.evaluate("document.querySelector('main').getBoundingClientRect().width")
    assert width <= _NARROW_CAP_PX


def test_footer_expands_on_wide_viewport(live_server, page):
    """footer max-width should match main on wide screens."""
    page.set_viewport_size({"width": 1400, "height": 900})
    page.goto(live_server + "/")

    width = page.evaluate("document.querySelector('footer').getBoundingClientRect().width")
    assert width > _NARROW_CAP_PX


def test_footer_capped_on_medium_viewport(live_server, page):
    """footer should stay at 60rem max-width on medium viewports."""
    page.set_viewport_size({"width": 1100, "height": 800})
    page.goto(live_server + "/")

    width = page.evaluate("document.querySelector('footer').getBoundingClientRect().width")
    assert width <= _NARROW_CAP_PX
