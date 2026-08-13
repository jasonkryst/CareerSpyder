from app.adapters import phenompeople
from app.config import PhenomPeopleSource


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def make_hit(job_id="457323", title="Family Medicine Physician",
             location="Bartlett, Illinois, 60103", posted="2026-07-27T19:05:38.996+0000"):
    return {"jobId": job_id, "title": title, "location": location, "postedDate": posted}


def make_envelope(hits, total_hits=None):
    return {"refineSearch": {
        "status": 200, "hits": len(hits), "totalHits": total_hits if total_hits is not None else len(hits),
        "data": {"jobs": hits},
    }}


def make_source(state="Illinois", company=None):
    return PhenomPeopleSource(
        id="s1", name="Ascension (PhenomPeople)", company=company,
        type="phenompeople", career_site_url="https://jobs.ascension.org", state=state,
    )


def test_fetch_maps_phenompeople_jobs_to_job_objects():
    payload = make_envelope([make_hit()])

    def fake_post(url, json, timeout):
        return FakeResponse(payload)

    jobs = phenompeople.fetch(make_source(company="Ascension"), http_post=fake_post)

    assert len(jobs) == 1
    assert jobs[0].key == "phenompeople:457323"
    assert jobs[0].title == "Family Medicine Physician"
    assert jobs[0].url == "https://jobs.ascension.org/us/en/job/457323"
    assert jobs[0].company == "Ascension"
    assert jobs[0].location == "Bartlett, Illinois, 60103"
    assert jobs[0].posted_date == "2026-07-27T19:05:38.996+0000"
    assert jobs[0].source_name == "Ascension (PhenomPeople)"


def test_fetch_sends_expected_request_url_and_body_with_state():
    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json))
        return FakeResponse(make_envelope([]))

    phenompeople.fetch(make_source(state="Illinois"), http_post=fake_post)

    url, body = calls[0]
    assert url == "https://jobs.ascension.org/widgets"
    assert body["ddoKey"] == "refineSearch"
    assert body["jobs"] is True
    assert body["counts"] is True
    assert body["from"] == 0
    assert body["selected_fields"] == {"state": ["Illinois"]}


def test_fetch_omits_state_filter_when_state_not_set():
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json)
        return FakeResponse(make_envelope([]))

    phenompeople.fetch(make_source(state=None), http_post=fake_post)

    assert calls[0]["selected_fields"] == {}


def test_fetch_maps_multiple_hits_in_order():
    payload = make_envelope([
        make_hit(job_id="1", title="Nurse"),
        make_hit(job_id="2", title="Therapist"),
    ])

    def fake_post(url, json, timeout):
        return FakeResponse(payload)

    jobs = phenompeople.fetch(make_source(), http_post=fake_post)

    assert [j.title for j in jobs] == ["Nurse", "Therapist"]
    assert [j.key for j in jobs] == ["phenompeople:1", "phenompeople:2"]


def test_fetch_handles_missing_location_and_posted_date_gracefully():
    hit = make_hit()
    del hit["location"]
    del hit["postedDate"]
    payload = make_envelope([hit])

    def fake_post(url, json, timeout):
        return FakeResponse(payload)

    jobs = phenompeople.fetch(make_source(), http_post=fake_post)

    assert jobs[0].location is None
    assert jobs[0].posted_date is None


def test_fetch_returns_empty_list_when_no_jobs():
    def fake_post(url, json, timeout):
        return FakeResponse(make_envelope([]))

    jobs = phenompeople.fetch(make_source(), http_post=fake_post)

    assert jobs == []
