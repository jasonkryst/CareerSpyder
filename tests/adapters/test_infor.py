from unittest.mock import MagicMock, patch

from app.adapters import infor
from app.adapters.infor import _title_changed, default_frame_fetcher
from app.config import InforSource

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


def make_source(max_pages=3):
    return InforSource(
        id="s1", name="Rush (Infor)", company="Rush University Medical Center",
        type="infor", url="https://rush.test/careers", max_pages=max_pages,
    )


def test_fetch_parses_single_page_of_cards():
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
        return None  # would be page 3, but max_pages=2 stops us first

    jobs = infor.fetch(make_source(max_pages=2), frame_fetcher=fake_fetcher)

    assert calls == [1, 2]
    assert [j.title for j in jobs] == ["Anesthesia Tech 1", "Supply Chain MDM Analyst", "Physical Therapist"]


def test_fetch_stops_early_when_frame_fetcher_returns_none():
    def fake_fetcher(url, page_number):
        return PAGE_1_HTML if page_number == 1 else None

    jobs = infor.fetch(make_source(max_pages=5), frame_fetcher=fake_fetcher)

    assert len(jobs) == 2  # only page 1's cards, even though max_pages allows up to 5


def test_fetch_stops_when_a_page_has_zero_cards():
    def fake_fetcher(url, page_number):
        if page_number == 1:
            return PAGE_1_HTML
        return "<div>no cards here</div>"

    jobs = infor.fetch(make_source(max_pages=5), frame_fetcher=fake_fetcher)

    assert len(jobs) == 2


def test_card_missing_posted_and_location_still_yields_a_job_with_none_fields():
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
    # Re-fetching the identical page must produce the identical key (dedup relies on this).
    jobs_again = infor.fetch(make_source(), frame_fetcher=fake_fetcher)
    assert jobs[0].key == jobs_again[0].key


# --- Pagination/polling branch logic (issue #136) ---

def test_title_changed_true_when_different():
    assert _title_changed("New Title", "Old Title") is True


def test_title_changed_false_when_same():
    assert _title_changed("Same Title", "Same Title") is False


def test_title_changed_true_when_previous_is_none():
    assert _title_changed("First Title", None) is True


def _make_page_mock(*, cell_count=1, disabled=False):
    """Builds a fake Playwright `page`/`frame` chain deep enough for
    default_frame_fetcher's branch logic. Each `.text_content()` call
    returns a new, distinct title so _wait_for_new_first_title's real
    polling loop always sees a change on its very first check -- without
    this, the mocked title would never change and the loop would burn its
    full 15s real-time deadline per click (only time.sleep is mocked, not
    time.monotonic)."""
    heading_locator = MagicMock()
    heading_locator.count.return_value = 1
    titles = (f"Title {i}" for i in range(1000))
    heading_locator.first.text_content.side_effect = lambda: next(titles)

    next_button = MagicMock()
    next_button.is_disabled.return_value = disabled

    cardstack_cell = MagicMock()
    cardstack_cell.count.return_value = cell_count

    body_locator = MagicMock()
    body_locator.inner_html.return_value = "<div class='inforCardstackCell'></div>"

    frame = MagicMock()

    def locator_side_effect(selector):
        return {
            ".inforCardstackHeading": heading_locator,
            "button.nextPage": next_button,
            ".slick-row": MagicMock(first=MagicMock(wait_for=MagicMock())),
            ".inforCardstackCell": cardstack_cell,
            "body": body_locator,
        }[selector]

    frame.locator.side_effect = locator_side_effect

    page = MagicMock()
    page.frame_locator.return_value = frame

    pw_browser = MagicMock()
    pw_browser.new_page.return_value = page

    p = MagicMock()
    p.chromium.launch.return_value = pw_browser

    sync_playwright_cm = MagicMock()
    sync_playwright_cm.__enter__.return_value = p
    sync_playwright_cm.__exit__.return_value = False

    return sync_playwright_cm, pw_browser, page, next_button, cardstack_cell


def test_default_frame_fetcher_returns_none_when_next_button_is_disabled():
    sync_playwright_cm, _pw_browser, _page, _next_button, _cardstack_cell = _make_page_mock(disabled=True)

    with patch("app.adapters.infor.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.infor.assert_safe_url"), \
         patch("app.adapters.infor.install_ssrf_guard"):
        result = default_frame_fetcher("https://rush.test/careers", page_number=2)

    assert result is None


def test_default_frame_fetcher_returns_none_when_zero_cards():
    sync_playwright_cm, _pw_browser, _page, _next_button, _cardstack_cell = _make_page_mock(cell_count=0)

    with patch("app.adapters.infor.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.infor.assert_safe_url"), \
         patch("app.adapters.infor.install_ssrf_guard"):
        result = default_frame_fetcher("https://rush.test/careers", page_number=1)

    assert result is None


def test_default_frame_fetcher_clicks_next_page_number_minus_one_times():
    sync_playwright_cm, _pw_browser, _page, next_button, _cardstack_cell = _make_page_mock(cell_count=1)

    with patch("app.adapters.infor.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.infor.assert_safe_url"), \
         patch("app.adapters.infor.install_ssrf_guard"), \
         patch("app.adapters.infor.time.sleep"):
        default_frame_fetcher("https://rush.test/careers", page_number=3)

    assert next_button.click.call_count == 2


def test_default_frame_fetcher_returns_html_when_cards_present():
    sync_playwright_cm, _pw_browser, _page, _next_button, _cardstack_cell = _make_page_mock(cell_count=1)

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
