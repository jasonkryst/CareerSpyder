from unittest.mock import MagicMock, patch

from app.adapters import infor
from app.adapters.infor import _title_changed, default_frame_fetcher
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


# ── v1 parsing tests ──────────────────────────────────────────────────────────

def test_fetch_parses_single_page_of_v1_cards():
    def fake_fetcher(url, page_number):
        assert url == "https://rush.test/careers"
        return PAGE_1_HTML if page_number == 1 else None

    jobs = infor.fetch(make_source(), frame_fetcher=fake_fetcher)

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

    jobs = infor.fetch(make_source(max_pages=2), frame_fetcher=fake_fetcher)

    assert calls == [1, 2]
    assert [j.title for j in jobs] == ["Anesthesia Tech 1", "Supply Chain MDM Analyst", "Physical Therapist"]


def test_fetch_stops_early_when_frame_fetcher_returns_none():
    def fake_fetcher(url, page_number):
        return PAGE_1_HTML if page_number == 1 else None

    jobs = infor.fetch(make_source(max_pages=5), frame_fetcher=fake_fetcher)

    assert len(jobs) == 2


def test_fetch_stops_when_a_page_has_zero_cards():
    def fake_fetcher(url, page_number):
        if page_number == 1:
            return PAGE_1_HTML
        return "<div>no cards here</div>"

    jobs = infor.fetch(make_source(max_pages=5), frame_fetcher=fake_fetcher)

    assert len(jobs) == 2


def test_v1_card_missing_posted_and_location_still_yields_a_job_with_none_fields():
    def fake_fetcher(url, page_number):
        return CARD_MISSING_POSTED_AND_LOCATION if page_number == 1 else None

    jobs = infor.fetch(make_source(), frame_fetcher=fake_fetcher)

    assert len(jobs) == 1
    assert jobs[0].title == "Bare Title Only"
    assert jobs[0].posted_date is None
    assert jobs[0].location is None


def test_job_key_is_stable_across_identical_cards_and_differs_for_different_ones():
    def fake_fetcher(url, page_number):
        return PAGE_1_HTML if page_number == 1 else None

    jobs = infor.fetch(make_source(), frame_fetcher=fake_fetcher)

    assert jobs[0].key != jobs[1].key
    jobs_again = infor.fetch(make_source(), frame_fetcher=fake_fetcher)
    assert jobs[0].key == jobs_again[0].key


# ── v2 parsing tests ──────────────────────────────────────────────────────────

def test_fetch_parses_v2_listview_cards():
    def fake_fetcher(url, page_number):
        return V2_PAGE_1_HTML if page_number == 1 else None

    jobs = infor.fetch(make_source(), frame_fetcher=fake_fetcher)

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

    jobs = infor.fetch(make_source(), frame_fetcher=fake_fetcher)

    assert len(jobs) == 1
    assert jobs[0].title == "CT Tech"
    assert jobs[0].location == "Evanston, IL"
    assert jobs[0].posted_date == "Posted: 08/09/2026"


def test_v2_card_missing_p_listview_heading_is_skipped():
    def fake_fetcher(url, page_number):
        return V2_CARD_MISSING_TITLE if page_number == 1 else None

    jobs = infor.fetch(make_source(), frame_fetcher=fake_fetcher)

    assert len(jobs) == 0


def test_v2_takes_priority_over_v1_when_both_selectors_present():
    mixed_html = V2_PAGE_1_HTML + PAGE_1_HTML

    def fake_fetcher(url, page_number):
        return mixed_html if page_number == 1 else None

    jobs = infor.fetch(make_source(), frame_fetcher=fake_fetcher)

    # v2 cards are found first; v1 cards are ignored
    assert all(j.title in ("Radiation Therapist", "MRI Technologist") for j in jobs)
    assert len(jobs) == 2


def test_v2_key_is_stable_and_differs_between_cards():
    def fake_fetcher(url, page_number):
        return V2_PAGE_1_HTML if page_number == 1 else None

    jobs = infor.fetch(make_source(), frame_fetcher=fake_fetcher)
    jobs_again = infor.fetch(make_source(), frame_fetcher=fake_fetcher)

    assert jobs[0].key != jobs[1].key
    assert jobs[0].key == jobs_again[0].key


# ── Pagination/polling branch logic ───────────────────────────────────────────

def test_title_changed_true_when_different():
    assert _title_changed("New Title", "Old Title") is True


def test_title_changed_false_when_same():
    assert _title_changed("Same Title", "Same Title") is False


def test_title_changed_true_when_previous_is_none():
    assert _title_changed("First Title", None) is True


def _make_page_mock(*, cell_count=1, disabled=False):
    """Builds a fake Playwright page/frame chain for v1 (Slickgrid) fetcher tests.

    page.locator("#jobListScreen") returns count=0 so the v1 iframe branch is
    taken.  _first_title() tries "p.listview-heading" first (v2), then
    ".inforCardstackHeading" (v1); the mock returns count=0 for the v2 selector
    so it falls through to v1 — each call returns a new unique title so
    _wait_for_new_first_title always sees a change on its first iteration without
    burning real-time on the 15-second deadline (only time.sleep is mocked, not
    time.monotonic).
    """
    v2_heading = MagicMock()
    v2_heading.count.return_value = 0

    v1_heading = MagicMock()
    v1_heading.count.return_value = 1
    titles = (f"Title {i}" for i in range(1000))
    v1_heading.first.text_content.side_effect = lambda: next(titles)

    card_locator = MagicMock()
    card_locator.count.return_value = cell_count

    next_locator = MagicMock()
    next_locator.count.return_value = 1
    next_locator.is_disabled.return_value = disabled

    body_locator = MagicMock()
    body_locator.inner_html.return_value = "<div class='inforCardstackCell'></div>"

    frame = MagicMock()

    def frame_locator_side_effect(selector):
        return {
            infor._CARD_SELECTOR: card_locator,
            infor._NEXT_SELECTOR: next_locator,
            "p.listview-heading": v2_heading,
            ".inforCardstackHeading": v1_heading,
            "body": body_locator,
        }[selector]

    frame.locator.side_effect = frame_locator_side_effect

    # v2-detection locator: count=0 so code takes the v1 iframe branch
    job_list_screen_locator = MagicMock()
    job_list_screen_locator.count.return_value = 0

    page = MagicMock()
    page.frame_locator.return_value = frame
    page.locator.side_effect = lambda sel: job_list_screen_locator if sel == "#jobListScreen" else MagicMock()

    pw_browser = MagicMock()
    pw_browser.new_page.return_value = page

    p = MagicMock()
    p.chromium.launch.return_value = pw_browser

    sync_playwright_cm = MagicMock()
    sync_playwright_cm.__enter__.return_value = p
    sync_playwright_cm.__exit__.return_value = False

    return sync_playwright_cm, pw_browser, page, next_locator, card_locator


def _make_v2_page_mock(*, cell_count=2, has_load_more=False, cell_count_after_load=None):
    """Builds a fake Playwright page for v2 (list-view SPA) fetcher tests.

    page.locator("#jobListScreen").count() returns 1, steering the fetcher into
    the v2 branch.  cell_count_after_load lets pagination tests simulate the
    count rising after a "load more" click.
    """
    job_list_screen_locator = MagicMock()
    job_list_screen_locator.count.return_value = 1

    v2_card_locator = MagicMock()
    if cell_count_after_load is not None:
        v2_card_locator.count.side_effect = [cell_count, cell_count_after_load] * 10
    else:
        v2_card_locator.count.return_value = cell_count

    load_more_locator = MagicMock()
    load_more_locator.count.return_value = 1 if has_load_more else 0
    load_more_locator.is_visible.return_value = has_load_more

    grid_content_locator = MagicMock()
    grid_content_locator.inner_html.return_value = (
        "<li job-req='1'><p class='listview-heading'>Test Job</p></li>"
    )

    def page_locator_side_effect(selector):
        return {
            "#jobListScreen": job_list_screen_locator,
            infor._V2_CARD: v2_card_locator,
            "#gridBottom": load_more_locator,
            "div.gridContent": grid_content_locator,
        }.get(selector, MagicMock())

    page = MagicMock()
    page.locator.side_effect = page_locator_side_effect

    pw_browser = MagicMock()
    pw_browser.new_page.return_value = page

    p = MagicMock()
    p.chromium.launch.return_value = pw_browser

    sync_playwright_cm = MagicMock()
    sync_playwright_cm.__enter__.return_value = p
    sync_playwright_cm.__exit__.return_value = False

    return sync_playwright_cm, pw_browser, page, load_more_locator, v2_card_locator


def test_default_frame_fetcher_returns_none_when_next_button_is_disabled():
    sync_playwright_cm, *_ = _make_page_mock(disabled=True)

    with patch("app.adapters.infor.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.infor.assert_safe_url"), \
         patch("app.adapters.infor.install_ssrf_guard"):
        result = default_frame_fetcher("https://rush.test/careers", page_number=2)

    assert result is None


def test_default_frame_fetcher_returns_none_when_no_next_button():
    sync_playwright_cm, _, _, next_locator, _ = _make_page_mock()
    next_locator.count.return_value = 0

    with patch("app.adapters.infor.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.infor.assert_safe_url"), \
         patch("app.adapters.infor.install_ssrf_guard"):
        result = default_frame_fetcher("https://rush.test/careers", page_number=2)

    assert result is None


def test_default_frame_fetcher_returns_none_when_zero_cards():
    sync_playwright_cm, *_ = _make_page_mock(cell_count=0)

    with patch("app.adapters.infor.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.infor.assert_safe_url"), \
         patch("app.adapters.infor.install_ssrf_guard"):
        result = default_frame_fetcher("https://rush.test/careers", page_number=1)

    assert result is None


def test_default_frame_fetcher_clicks_next_page_number_minus_one_times():
    sync_playwright_cm, _, _, next_locator, _ = _make_page_mock(cell_count=1)

    with patch("app.adapters.infor.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.infor.assert_safe_url"), \
         patch("app.adapters.infor.install_ssrf_guard"), \
         patch("app.adapters.infor.time.sleep"):
        default_frame_fetcher("https://rush.test/careers", page_number=3)

    assert next_locator.click.call_count == 2


def test_default_frame_fetcher_returns_html_when_cards_present():
    sync_playwright_cm, *_ = _make_page_mock(cell_count=1)

    with patch("app.adapters.infor.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.infor.assert_safe_url"), \
         patch("app.adapters.infor.install_ssrf_guard"):
        result = default_frame_fetcher("https://rush.test/careers", page_number=1)

    assert result == "<div class='inforCardstackCell'></div>"


def test_default_frame_fetcher_validates_url_before_launching_browser():
    from app.security.ssrf_guard import UnsafeUrlError

    with patch("app.adapters.infor.assert_safe_url", side_effect=UnsafeUrlError("blocked")) as mock_assert, \
         patch("app.adapters.infor.sync_playwright") as mock_sync_playwright:
        try:
            default_frame_fetcher("http://169.254.169.254/", page_number=1)
        except UnsafeUrlError:
            pass

    mock_assert.assert_called_once_with("http://169.254.169.254/")
    mock_sync_playwright.assert_not_called()


def test_default_frame_fetcher_v2_returns_html_when_cards_present():
    sync_playwright_cm, *_ = _make_v2_page_mock(cell_count=2)

    with patch("app.adapters.infor.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.infor.assert_safe_url"), \
         patch("app.adapters.infor.install_ssrf_guard"):
        result = default_frame_fetcher("https://rush.test/careers", page_number=1)

    assert result == "<li job-req='1'><p class='listview-heading'>Test Job</p></li>"


def test_default_frame_fetcher_v2_returns_none_when_zero_cards():
    sync_playwright_cm, *_ = _make_v2_page_mock(cell_count=0)

    with patch("app.adapters.infor.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.infor.assert_safe_url"), \
         patch("app.adapters.infor.install_ssrf_guard"):
        result = default_frame_fetcher("https://rush.test/careers", page_number=1)

    assert result is None


def test_default_frame_fetcher_v2_returns_none_when_no_load_more_button():
    sync_playwright_cm, _, _, load_more_locator, _ = _make_v2_page_mock(
        cell_count=2, has_load_more=False
    )

    with patch("app.adapters.infor.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.infor.assert_safe_url"), \
         patch("app.adapters.infor.install_ssrf_guard"):
        result = default_frame_fetcher("https://rush.test/careers", page_number=2)

    assert result is None
    load_more_locator.click.assert_not_called()


def test_default_frame_fetcher_v2_clicks_load_more_page_number_minus_one_times():
    sync_playwright_cm, _, _, load_more_locator, _ = _make_v2_page_mock(
        cell_count=2, has_load_more=True, cell_count_after_load=4
    )

    with patch("app.adapters.infor.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.infor.assert_safe_url"), \
         patch("app.adapters.infor.install_ssrf_guard"), \
         patch("app.adapters.infor.time.sleep"):
        default_frame_fetcher("https://rush.test/careers", page_number=3)

    assert load_more_locator.click.call_count == 2
