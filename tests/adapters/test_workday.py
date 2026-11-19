import pytest
import requests

from app.adapters import workday
from app.config import WorkdaySource


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Pacing/backoff must never slow the suite down; tests that care about
    the waits pass their own `sleep` recorder instead."""
    monkeypatch.setattr(workday, "_sleep", lambda _s: None)


class FakeResponse:
    def __init__(self, payload=None, status_code=200, headers=None):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} Client Error", response=self)

    def json(self):
        return self._payload


def make_posting(req_id="JR100001", title="Registered Nurse",
                  external_path="/job/naperville/Registered-Nurse_JR100001",
                  location="Naperville, Illinois", posted="Posted Today"):
    return {
        "title": title,
        "externalPath": external_path,
        "locationsText": location,
        "postedOn": posted,
        "bulletFields": ["Regular", req_id],
    }


def make_source(max_pages=60):
    return WorkdaySource(
        id="s1", name="Duly (Workday)", company="Duly Health and Care",
        type="workday", career_site_url="https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly",
        max_pages=max_pages,
    )


def test_fetch_derives_api_url_from_career_site_url():
    calls = []

    def fake_post(url, json, timeout):
        calls.append(url)
        return FakeResponse({"total": 0, "jobPostings": []})

    workday.fetch(make_source(), http_post=fake_post)

    assert calls == ["https://dulyhealthandcare.wd1.myworkdayjobs.com/wday/cxs/dulyhealthandcare/Duly/jobs"]


def test_fetch_maps_postings_to_job_objects():
    def fake_post(url, json, timeout):
        return FakeResponse({"total": 1, "jobPostings": [make_posting()]})

    jobs = workday.fetch(make_source(), http_post=fake_post)

    assert len(jobs) == 1
    assert jobs[0].key == "workday:JR100001"
    assert jobs[0].title == "Registered Nurse"
    assert jobs[0].url == "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly/job/naperville/Registered-Nurse_JR100001"
    assert jobs[0].company == "Duly Health and Care"
    assert jobs[0].location == "Naperville, Illinois"
    assert jobs[0].posted_date == "Posted Today"
    assert jobs[0].source_name == "Duly (Workday)"
    assert jobs[0].source_id == "s1"


def test_fetch_falls_back_to_external_path_when_requisition_id_missing():
    posting = make_posting()
    posting["bulletFields"] = ["Regular"]  # no requisition id element

    def fake_post(url, json, timeout):
        return FakeResponse({"total": 1, "jobPostings": [posting]})

    jobs = workday.fetch(make_source(), http_post=fake_post)

    assert jobs[0].key == f"workday:{posting['externalPath']}"


def test_fetch_ignores_total_zero_on_later_pages_and_still_fetches_all():
    # Verified real-API quirk: total reports 0 on every page after the first.
    calls = []

    def fake_post(url, json, timeout):
        offset = json["offset"]
        calls.append(offset)
        if offset == 0:
            return FakeResponse({"total": 45, "jobPostings": [make_posting(req_id=f"JR{offset}")]})
        return FakeResponse({"total": 0, "jobPostings": [make_posting(req_id=f"JR{offset}")]})

    jobs = workday.fetch(make_source(), http_post=fake_post)

    # 45 total at page size 20 -> offsets 0, 20, 40
    assert calls == [0, 20, 40]
    assert len(jobs) == 3


def test_fetch_never_requests_an_offset_that_would_wrap_around():
    # Verified real-API quirk: an offset at/past the true total silently
    # returns page 1's content again instead of an empty list. The loop
    # must stop strictly before that, using only the frozen page-1 total.
    calls = []

    def fake_post(url, json, timeout):
        offset = json["offset"]
        calls.append(offset)
        if offset >= 40:
            raise AssertionError(f"fetched offset {offset}, which would wrap around on the real API")
        return FakeResponse({"total": 40, "jobPostings": [make_posting(req_id=f"JR{offset}")]})

    jobs = workday.fetch(make_source(), http_post=fake_post)

    assert calls == [0, 20]
    assert len(jobs) == 2


def test_fetch_respects_max_pages_as_a_hard_cap():
    calls = []

    def fake_post(url, json, timeout):
        offset = json["offset"]
        calls.append(offset)
        return FakeResponse({"total": 1000, "jobPostings": [make_posting(req_id=f"JR{offset}")]})

    jobs = workday.fetch(make_source(max_pages=2), http_post=fake_post)

    assert calls == [0, 20]
    assert len(jobs) == 2


def test_fetch_skips_malformed_record_and_keeps_valid_ones():
    good1 = make_posting(req_id="JR001", title="Good One")
    malformed = {"externalPath": "/job/bad"}  # missing 'title' → KeyError
    good2 = make_posting(req_id="JR002", title="Good Two")
    payload = {"total": 3, "jobPostings": [good1, malformed, good2]}

    def fake_post(url, json, timeout):
        return FakeResponse(payload)

    jobs = workday.fetch(make_source(), http_post=fake_post)

    assert len(jobs) == 2
    assert jobs[0].title == "Good One"
    assert jobs[1].title == "Good Two"


def test_job_url_includes_the_career_site_segment():
    # Workday's externalPath is relative to the career site, not the host:
    # {origin}{externalPath} 404s, {origin}/{site}{externalPath} is the real
    # posting page (issue #175, verified against Duly and Endeavour).
    source = WorkdaySource(
        id="s2", name="Endeavour", company="Endeavour", type="workday",
        career_site_url="https://nshs.wd1.myworkdayjobs.com/ns-eeh/",
    )

    def fake_post(url, json, timeout):
        return FakeResponse({"total": 1, "jobPostings": [
            make_posting(external_path="/job/EVH-Evanston-Hospital/RN_R41824-1"),
        ]})

    jobs = workday.fetch(source, http_post=fake_post)

    assert jobs[0].url == "https://nshs.wd1.myworkdayjobs.com/ns-eeh/job/EVH-Evanston-Hospital/RN_R41824-1"


# --- Rate limiting (HTTP 429). Workday throttles per client IP across a
# wdN cluster: a production run saw Duly 429 mid-pagination and Endeavour
# (same wd1 cluster, run right after) 429 on its very first page.


def _ok_page(total, offset):
    return FakeResponse({"total": total, "jobPostings": [make_posting(req_id=f"JR{offset}")]})


def test_fetch_retries_a_429_and_then_succeeds():
    responses = iter([FakeResponse(status_code=429), _ok_page(1, 0)])
    waits = []

    jobs = workday.fetch(make_source(), http_post=lambda url, json, timeout: next(responses), sleep=waits.append)

    assert [j.key for j in jobs] == ["workday:JR0"]
    assert len(waits) == 1 and waits[0] > 0


def test_fetch_honors_a_numeric_retry_after_header():
    responses = iter([FakeResponse(status_code=429, headers={"Retry-After": "7"}), _ok_page(1, 0)])
    waits = []

    workday.fetch(make_source(), http_post=lambda url, json, timeout: next(responses), sleep=waits.append)

    assert waits == [7.0]


def test_fetch_caps_an_excessive_retry_after():
    responses = iter([FakeResponse(status_code=429, headers={"Retry-After": "3600"}), _ok_page(1, 0)])
    waits = []

    workday.fetch(make_source(), http_post=lambda url, json, timeout: next(responses), sleep=waits.append)

    assert waits == [workday._MAX_RETRY_WAIT_S]


def test_fetch_retries_only_the_throttled_page_not_the_whole_crawl():
    offsets = []
    throttled_once = []

    def fake_post(url, json, timeout):
        offsets.append(json["offset"])
        if json["offset"] == 20 and not throttled_once:
            throttled_once.append(True)
            return FakeResponse(status_code=429)
        return _ok_page(45, json["offset"])

    jobs = workday.fetch(make_source(), http_post=fake_post, sleep=lambda _s: None)

    assert offsets == [0, 20, 20, 40]
    assert [j.key for j in jobs] == ["workday:JR0", "workday:JR20", "workday:JR40"]


def test_fetch_raises_after_exhausting_retries_rather_than_returning_partial_results():
    # A partial result would let reconcile_jobs mark the missing jobs removed,
    # so a persistent 429 must fail the source outright.
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json["offset"])
        if json["offset"] == 0:
            return _ok_page(45, 0)
        return FakeResponse(status_code=429)

    with pytest.raises(requests.exceptions.HTTPError):
        workday.fetch(make_source(), http_post=fake_post, sleep=lambda _s: None)

    assert calls == [0] + [20] * (1 + workday._MAX_RETRIES)


def test_fetch_does_not_retry_a_non_throttling_error():
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json["offset"])
        return FakeResponse(status_code=500)

    with pytest.raises(requests.exceptions.HTTPError):
        workday.fetch(make_source(), http_post=fake_post, sleep=lambda _s: None)

    assert calls == [0]


def test_fetch_paces_page_requests_but_not_the_first():
    waits = []

    workday.fetch(make_source(), http_post=lambda url, json, timeout: _ok_page(45, json["offset"]), sleep=waits.append)

    # Three pages (0, 20, 40): a pause before each page after the first.
    assert waits == [workday._PAGE_DELAY_S, workday._PAGE_DELAY_S]


# --- Edge bot protection. Production got 429s from Cloudflare that were an
# HTML block page, not an API rate limit: the same IP got 200s from a desktop
# browser and from another client at the same moment. Retrying a deliberate
# block only adds traffic, so it fails fast with a clear reason.


def _block_page(status):
    return FakeResponse(
        status_code=status,
        headers={"Content-Type": "text/html; charset=UTF-8", "Server": "cloudflare"},
    )


@pytest.mark.parametrize("status", [403, 429])
def test_fetch_fails_fast_on_an_html_block_page_without_retrying(status):
    calls, waits = [], []

    def fake_post(url, json, timeout):
        calls.append(json["offset"])
        return _block_page(status)

    with pytest.raises(workday.WorkdayBlockedError) as exc:
        workday.fetch(make_source(), http_post=fake_post, sleep=waits.append)

    assert calls == [0]
    assert waits == []
    message = str(exc.value)
    assert f"HTTP {status}" in message
    assert "blocked" in message and "cloudflare" in message.lower()


def test_block_error_is_still_an_http_error():
    # Callers that already handle requests' HTTPError keep working.
    assert issubclass(workday.WorkdayBlockedError, requests.exceptions.HTTPError)


def test_a_json_429_is_still_treated_as_a_rate_limit_and_retried():
    responses = iter([
        FakeResponse(status_code=429, headers={"Content-Type": "application/json"}),
        _ok_page(1, 0),
    ])
    waits = []

    jobs = workday.fetch(make_source(), http_post=lambda url, json, timeout: next(responses), sleep=waits.append)

    assert len(jobs) == 1 and len(waits) == 1


def test_throttle_retries_are_logged_at_warning_so_production_shows_them(caplog):
    # The app configures no logging, so Python's last-resort handler drops
    # anything below WARNING -- an INFO retry line never reaches the container log.
    responses = iter([FakeResponse(status_code=429), _ok_page(1, 0)])

    with caplog.at_level("WARNING", logger="app.adapters.workday"):
        workday.fetch(make_source(), http_post=lambda url, json, timeout: next(responses), sleep=lambda _s: None)

    assert any("throttled" in r.getMessage() and r.levelname == "WARNING" for r in caplog.records)
