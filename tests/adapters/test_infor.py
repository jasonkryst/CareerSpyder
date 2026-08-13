from app.adapters import infor
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
