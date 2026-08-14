from app.adapters import workday
from app.config import WorkdaySource


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

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
    assert jobs[0].url == "https://dulyhealthandcare.wd1.myworkdayjobs.com/job/naperville/Registered-Nurse_JR100001"
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
