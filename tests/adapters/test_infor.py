from unittest.mock import patch

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.adapters import infor
from app.adapters.infor import _title_changed, default_page_iterator
from app.config import InforSource

# ── v1 (Slickgrid card-stack) HTML fixtures ──────────────────────────────────

PAGE_1_HTML = """
<div class="inforCardstackCell">
  <span class="inforCardstackHeading">Anesthesia Tech 1</span>
  <div class="floatRight PostedDiv">
    <label class="inforCardstackLabel PostedLbl">Posted</label>
    <label class="inforCardstackValue">08/12/2026</label>
  </div>
  <br>
  <label class="inforCardstackLabel LocationLbl">Location</label>
  <label class="inforCardstackValue">US:IL:Chicago</label>
</div>
<div class="inforCardstackCell">
  <span class="inforCardstackHeading">Supply Chain MDM Analyst</span>
  <div class="floatRight PostedDiv">
    <label class="inforCardstackLabel PostedLbl">Posted</label>
    <label class="inforCardstackValue">08/11/2026</label>
  </div>
  <br>
  <label class="inforCardstackLabel LocationLbl">Location</label>
  <label class="inforCardstackValue">US:IL:Chicago</label>
</div>
"""

PAGE_2_HTML = """
<div class="inforCardstackCell">
  <span class="inforCardstackHeading">Physical Therapist</span>
  <div class="floatRight PostedDiv">
    <label class="inforCardstackLabel PostedLbl">Posted</label>
    <label class="inforCardstackValue">08/10/2026</label>
  </div>
  <br>
  <label class="inforCardstackLabel LocationLbl">Location</label>
  <label class="inforCardstackValue">US:IL:Oak Park</label>
</div>
"""

CARD_MISSING_POSTED_AND_LOCATION = """
<div class="inforCardstackCell">
  <span class="inforCardstackHeading">Bare Title Only</span>
</div>
"""

# ── v2 (list-view SPA) HTML fixtures ─────────────────────────────────────────

V2_PAGE_1_HTML = """
<ul>
  <li style="position: relative;" job-req="10001" job-post="20001">
    <div>
      <p class="listview-heading">Radiation Therapist</p>
      <div class="listview-subheading">
        <span class="listview-subheading">Department: Radiology</span>
      </div>
      <div class="listview-subheading">
        <span class="listview-subheading">Chicago, IL</span>
      </div>
    </div>
    <div>
      <span class="listview-subheading">Posted: 08/12/2026</span>
    </div>
  </li>
  <li style="position: relative;" job-req="10002" job-post="20002">
    <div>
      <p class="listview-heading">MRI Technologist</p>
      <div class="listview-subheading">
        <span class="listview-subheading">Department: Imaging</span>
      </div>
      <div class="listview-subheading">
        <span class="listview-subheading">Oak Park, IL</span>
      </div>
    </div>
    <div>
      <span class="listview-subheading">Posted: 08/11/2026</span>
    </div>
  </li>
</ul>
"""

V2_CARD_NO_SUBCATEGORY = """
<li style="position: relative;" job-req="10003" job-post="20003">
  <div>
    <p class="listview-heading">CT Tech</p>
    <div class="listview-subheading">
      <span class="listview-subheading">Evanston, IL</span>
    </div>
  </div>
  <div>
    <span class="listview-subheading">Posted: 08/09/2026</span>
  </div>
</li>
"""

V2_CARD_MISSING_TITLE = """
<li style="position: relative;" job-req="10004" job-post="20004">
  <div>
    <span class="listview-subheading">Chicago, IL</span>
  </div>
</li>
"""


def make_source(max_pages=3):
    return InforSource(
        id="s1", name="Rush (Infor)", company="Rush University Medical Center",
        type="infor", url="https://rush.test/careers", max_pages=max_pages,
    )


def _by_page_number(fetcher):
    """Adapts a `fetcher(url, page_number) -> html | None` fake to the
    `page_iterator(url, max_pages)` shape fetch() takes."""
    def page_iterator(url, max_pages):
        for page_number in range(1, max_pages + 1):
            html = fetcher(url, page_number)
            if html is None:
                return
            yield html
    return page_iterator


# ── v1 parsing tests ──────────────────────────────────────────────────────────

def test_fetch_parses_single_page_of_v1_cards():
    def fake_fetcher(url, page_number):
        assert url == "https://rush.test/careers"
        return PAGE_1_HTML if page_number == 1 else None

    jobs = infor.fetch(make_source(), page_iterator=_by_page_number(fake_fetcher))

    assert len(jobs) == 2
    assert jobs[0].title == "Anesthesia Tech 1"
    assert jobs[0].posted_date == "08/12/2026"
    assert jobs[0].location == "US:IL:Chicago"
    assert jobs[0].company == "Rush University Medical Center"
    assert jobs[0].url == "https://rush.test/careers"
    assert jobs[0].source_name == "Rush (Infor)"
    assert jobs[0].source_id == "s1"
    assert jobs[1].title == "Supply Chain MDM Analyst"


def test_fetch_paginates_up_to_max_pages():
    calls = []

    def fake_fetcher(url, page_number):
        calls.append(page_number)
        if page_number == 1:
            return PAGE_1_HTML
        if page_number == 2:
            return PAGE_2_HTML
        return None

    jobs = infor.fetch(make_source(max_pages=2), page_iterator=_by_page_number(fake_fetcher))

    assert calls == [1, 2]
    assert [j.title for j in jobs] == ["Anesthesia Tech 1", "Supply Chain MDM Analyst", "Physical Therapist"]


def test_fetch_stops_early_when_page_iterator_is_exhausted():
    def fake_fetcher(url, page_number):
        return PAGE_1_HTML if page_number == 1 else None

    jobs = infor.fetch(make_source(max_pages=5), page_iterator=_by_page_number(fake_fetcher))

    assert len(jobs) == 2


def test_fetch_stops_when_a_page_has_zero_cards():
    def fake_fetcher(url, page_number):
        if page_number == 1:
            return PAGE_1_HTML
        return "<div>no cards here</div>"

    jobs = infor.fetch(make_source(max_pages=5), page_iterator=_by_page_number(fake_fetcher))

    assert len(jobs) == 2


def test_v1_card_missing_posted_and_location_still_yields_a_job_with_none_fields():
    def fake_fetcher(url, page_number):
        return CARD_MISSING_POSTED_AND_LOCATION if page_number == 1 else None

    jobs = infor.fetch(make_source(), page_iterator=_by_page_number(fake_fetcher))

    assert len(jobs) == 1
    assert jobs[0].title == "Bare Title Only"
    assert jobs[0].posted_date is None
    assert jobs[0].location is None


def test_job_key_is_stable_across_identical_cards_and_differs_for_different_ones():
    def fake_fetcher(url, page_number):
        return PAGE_1_HTML if page_number == 1 else None

    jobs = infor.fetch(make_source(), page_iterator=_by_page_number(fake_fetcher))

    assert jobs[0].key != jobs[1].key
    jobs_again = infor.fetch(make_source(), page_iterator=_by_page_number(fake_fetcher))
    assert jobs[0].key == jobs_again[0].key


# ── v2 parsing tests ──────────────────────────────────────────────────────────

def test_fetch_parses_v2_listview_cards():
    def fake_fetcher(url, page_number):
        return V2_PAGE_1_HTML if page_number == 1 else None

    jobs = infor.fetch(make_source(), page_iterator=_by_page_number(fake_fetcher))

    assert len(jobs) == 2
    assert jobs[0].title == "Radiation Therapist"
    assert jobs[0].location == "Chicago, IL"
    assert jobs[0].posted_date == "Posted: 08/12/2026"
    assert jobs[0].company == "Rush University Medical Center"
    assert jobs[0].url == "https://rush.test/careers"
    assert jobs[1].title == "MRI Technologist"
    assert jobs[1].location == "Oak Park, IL"


def test_v2_card_without_subcategory_parses_correctly():
    def fake_fetcher(url, page_number):
        return V2_CARD_NO_SUBCATEGORY if page_number == 1 else None

    jobs = infor.fetch(make_source(), page_iterator=_by_page_number(fake_fetcher))

    assert len(jobs) == 1
    assert jobs[0].title == "CT Tech"
    assert jobs[0].location == "Evanston, IL"
    assert jobs[0].posted_date == "Posted: 08/09/2026"


def test_v2_card_missing_p_listview_heading_is_skipped():
    def fake_fetcher(url, page_number):
        return V2_CARD_MISSING_TITLE if page_number == 1 else None

    jobs = infor.fetch(make_source(), page_iterator=_by_page_number(fake_fetcher))

    assert len(jobs) == 0


def test_v2_takes_priority_over_v1_when_both_selectors_present():
    mixed_html = V2_PAGE_1_HTML + PAGE_1_HTML

    def fake_fetcher(url, page_number):
        return mixed_html if page_number == 1 else None

    jobs = infor.fetch(make_source(), page_iterator=_by_page_number(fake_fetcher))

    # v2 cards are found first; v1 cards are ignored
    assert all(j.title in ("Radiation Therapist", "MRI Technologist") for j in jobs)
    assert len(jobs) == 2


def test_v2_key_is_stable_and_differs_between_cards():
    def fake_fetcher(url, page_number):
        return V2_PAGE_1_HTML if page_number == 1 else None

    jobs = infor.fetch(make_source(), page_iterator=_by_page_number(fake_fetcher))
    jobs_again = infor.fetch(make_source(), page_iterator=_by_page_number(fake_fetcher))

    assert jobs[0].key != jobs[1].key
    assert jobs[0].key == jobs_again[0].key


# ── Pagination/polling branch logic ───────────────────────────────────────────

def test_title_changed_true_when_different():
    assert _title_changed("New Title", "Old Title") is True


def test_title_changed_false_when_same():
    assert _title_changed("Same Title", "Same Title") is False


def test_title_changed_true_when_previous_is_none():
    assert _title_changed("First Title", None) is True


# ── fetch(): session lifecycle ───────────────────────────────────────────────

def test_fetch_dedupes_cumulative_v2_pages_by_key():
    # v2 "load more" appends to the same grid, so each yielded page repeats
    # the earlier cards; fetch must not return them twice.
    def page_iterator(url, max_pages):
        yield V2_PAGE_1_HTML
        yield V2_PAGE_1_HTML + V2_CARD_NO_SUBCATEGORY

    jobs = infor.fetch(make_source(), page_iterator=page_iterator)

    assert [j.title for j in jobs] == ["Radiation Therapist", "MRI Technologist", "CT Tech"]


def test_fetch_closes_the_page_iterator_when_it_stops_early():
    closed = []

    def page_iterator(url, max_pages):
        try:
            yield PAGE_1_HTML
            yield "<div>no cards</div>"
            yield PAGE_2_HTML
        finally:
            closed.append(True)

    infor.fetch(make_source(max_pages=5), page_iterator=page_iterator)

    assert closed == [True]


def test_fetch_propagates_a_mid_run_failure_instead_of_returning_partial_jobs():
    # A partial result would make reconcile_jobs mark every job on the unread
    # pages as removed, then re-email them on the next full run.
    def page_iterator(url, max_pages):
        yield PAGE_1_HTML
        raise PlaywrightTimeoutError("page 2 never rendered")

    with pytest.raises(PlaywrightTimeoutError):
        infor.fetch(make_source(max_pages=5), page_iterator=page_iterator)


# ── Browser session (default_page_iterator) with a fake Playwright page ──────

class _FakeLocator:
    def __init__(self, count=0, html="", text=None, disabled=False, visible=True, on_click=None):
        self._count, self._html, self._text = count, html, text
        self._disabled, self._visible, self._on_click = disabled, visible, on_click
        self.clicks = 0

    def count(self):
        return self._count() if callable(self._count) else self._count

    @property
    def first(self):
        return self

    def inner_html(self):
        return self._html() if callable(self._html) else self._html

    def text_content(self):
        return self._text() if callable(self._text) else self._text

    def is_disabled(self):
        return self._disabled

    def is_visible(self):
        return self._visible

    def click(self):
        self.clicks += 1
        if self._on_click:
            self._on_click()


class _FakeFrame:
    def __init__(self, locators):
        self._locators = locators

    def locator(self, selector):
        return self._locators.get(selector, _FakeLocator())


class _FakePage:
    def __init__(self, page_locators=None, frame_locators=None):
        self._page_locators = page_locators or {}
        self._frame = _FakeFrame(frame_locators or {})
        self.closed = False

    def goto(self, url, wait_until, timeout):
        pass

    def locator(self, selector):
        return self._page_locators.get(selector, _FakeLocator())

    def frame_locator(self, selector):
        assert selector == "#parentIframe"
        return self._frame

    def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, pages):
        self._pages = list(pages)
        self.opened: list[_FakePage] = []
        self.closed = False

    def new_page(self):
        page = self._pages.pop(0)
        self.opened.append(page)
        return page

    def close(self):
        self.closed = True


class _FakePlaywright:
    def __init__(self, browser):
        self.chromium = self
        self._browser = browser

    def launch(self):
        return self._browser

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _v1_page(pages_html, *, ready_after_polls=0):
    """Lawson-hybrid/v1 board: Slickgrid rows inside #parentIframe, paged by a
    next button. Rows appear only after `ready_after_polls` readiness polls."""
    state = {"page": 0, "polls": 0}

    def rows():
        state["polls"] += 1
        return 10 if state["polls"] > ready_after_polls else 0

    def advance():
        state["page"] += 1

    next_button = _FakeLocator(count=1, on_click=advance)
    frame = {
        infor._V1_SLICK_ROW: _FakeLocator(count=rows),
        infor._CARD_SELECTOR: _FakeLocator(count=lambda: 1 if state["page"] < len(pages_html) else 0),
        infor._NEXT_SELECTOR: next_button,
        ".inforCardstackHeading": _FakeLocator(count=1, text=lambda: f"first-title-{state['page']}"),
        "body": _FakeLocator(html=lambda: pages_html[min(state["page"], len(pages_html) - 1)]),
    }
    page = _FakePage(page_locators={"#jobListScreen": _FakeLocator(count=1),
                                    "#parentIframe": _FakeLocator(count=1)},
                     frame_locators=frame)
    return page, next_button


def _v2_page(grid_html, *, cards=2):
    return _FakePage(page_locators={
        "#jobListScreen": _FakeLocator(count=1),
        infor._V2_READY: _FakeLocator(count=cards),
        "#jobListScreen .gridContent": _FakeLocator(html=grid_html),
        "#gridBottom": _FakeLocator(count=0, visible=False),
    })


def _never_ready_page():
    return _FakePage(page_locators={"#jobListScreen": _FakeLocator(count=1)})


def _run(browser, url="https://rush.test/careers", max_pages=5, ready_timeout_s=0.05):
    with patch("app.adapters.infor.sync_playwright", return_value=_FakePlaywright(browser)), \
         patch("app.adapters.infor.assert_safe_url"), \
         patch("app.adapters.infor.install_ssrf_guard"), \
         patch("app.adapters.infor.time.sleep"), \
         patch("app.adapters.infor._READY_TIMEOUT_S", ready_timeout_s):
        return list(default_page_iterator(url, max_pages))


def test_page_iterator_walks_all_v1_pages_in_one_browser_session():
    page, next_button = _v1_page([PAGE_1_HTML, PAGE_2_HTML])
    browser = _FakeBrowser([page])

    htmls = _run(browser, max_pages=5)

    assert htmls == [PAGE_1_HTML, PAGE_2_HTML]
    assert len(browser.opened) == 1          # one page load, not one per results page
    assert next_button.clicks == 2           # page 2, then the click that runs out of cards
    assert browser.closed


def test_page_iterator_respects_max_pages():
    page, next_button = _v1_page([PAGE_1_HTML, PAGE_2_HTML, PAGE_1_HTML])

    htmls = _run(_FakeBrowser([page]), max_pages=2)

    assert len(htmls) == 2
    assert next_button.clicks == 1


def test_page_iterator_stops_when_next_button_is_disabled():
    page, next_button = _v1_page([PAGE_1_HTML, PAGE_2_HTML])
    next_button._disabled = True

    assert _run(_FakeBrowser([page])) == [PAGE_1_HTML]


def test_page_iterator_waits_for_slow_lawson_iframe_instead_of_assuming_v2():
    # Regression for #153: RUMC's iframe rows sometimes take longer than the
    # old fixed 15s probe; the old code then waited for v2 cards that never
    # come and failed the whole source.
    page, _ = _v1_page([PAGE_1_HTML], ready_after_polls=3)

    assert _run(_FakeBrowser([page]), ready_timeout_s=5) == [PAGE_1_HTML]


def test_page_iterator_reads_v2_grid_when_there_are_no_iframe_rows():
    assert _run(_FakeBrowser([_v2_page(V2_PAGE_1_HTML)])) == [V2_PAGE_1_HTML]


def test_page_iterator_retries_the_initial_load_once():
    slow, good = _never_ready_page(), _v1_page([PAGE_1_HTML])[0]
    browser = _FakeBrowser([slow, good])

    assert _run(browser) == [PAGE_1_HTML]
    assert slow.closed
    assert browser.closed


def test_page_iterator_raises_after_the_retry_also_times_out():
    browser = _FakeBrowser([_never_ready_page(), _never_ready_page()])

    with pytest.raises(PlaywrightTimeoutError):
        _run(browser)
    assert browser.closed


def test_page_iterator_validates_url_before_launching_browser():
    from app.security.ssrf_guard import UnsafeUrlError

    with patch("app.adapters.infor.assert_safe_url", side_effect=UnsafeUrlError("blocked")), \
         patch("app.adapters.infor.sync_playwright") as mock_sync_playwright, \
         pytest.raises(UnsafeUrlError):
        list(default_page_iterator("http://169.254.169.254/", 1))

    mock_sync_playwright.assert_not_called()
