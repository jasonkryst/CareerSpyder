from app.adapters import healthcaresource
from app.config import HealthcareSource


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def make_hit(hit_id="4730_12040", title="Athletic Trainer", facility="Rush Copley Medical Center",
             locality_region="Yorkville, IL", posted="2026-06-29T00:00:00Z"):
    return {
        "_id": hit_id,
        "_source": {
            "title": title,
            "datePosted": posted,
            "hiringOrganization": {"name": facility},
            "jobLocation": {"address": {"addressLocalityRegion": locality_region}},
        },
    }


def make_source(company=None):
    return HealthcareSource(
        id="s1", name="Rush Copley (HealthcareSource)", company=company,
        type="healthcaresource", site_id="rcmc",
    )


def test_fetch_maps_healthcaresource_jobs_to_job_objects():
    payload = {"hits": {"total": {"value": 1}, "hits": [make_hit()]}}
    calls = []

    def fake_post(url, json, timeout):
        calls.append(url)
        return FakeResponse(payload)

    jobs = healthcaresource.fetch(make_source(), http_post=fake_post)

    assert calls == ["https://pm.healthcaresource.com/JobseekerSearchAPI/rcmc/api/Search?size=1000"]
    assert len(jobs) == 1
    assert jobs[0].key == "healthcaresource:4730_12040"
    assert jobs[0].title == "Athletic Trainer"
    assert jobs[0].url == "https://pm.healthcaresource.com/CS/rcmc/#/job/12040"
    assert jobs[0].company == "Rush Copley Medical Center"
    assert jobs[0].location == "Yorkville, IL"
    assert jobs[0].posted_date == "2026-06-29T00:00:00Z"
    assert jobs[0].source_name == "Rush Copley (HealthcareSource)"
    assert jobs[0].source_id == "s1"


def test_fetch_sends_the_expected_search_request_body():
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json)
        return FakeResponse({"hits": {"total": {"value": 0}, "hits": []}})

    healthcaresource.fetch(make_source(), http_post=fake_post)

    assert calls[0] == {
        "query": {
            "bool": {
                "must": {"match_all": {}},
                "should": {"match": {"userArea.isFeaturedJob": {"query": True, "boost": 1}}},
            }
        },
        "sort": {"title.raw": "asc"},
    }


def test_fetch_falls_back_to_source_company_when_hiring_organization_missing():
    hit = make_hit()
    del hit["_source"]["hiringOrganization"]
    payload = {"hits": {"total": {"value": 1}, "hits": [hit]}}

    def fake_post(url, json, timeout):
        return FakeResponse(payload)

    jobs = healthcaresource.fetch(make_source(company="Fallback Co"), http_post=fake_post)

    assert jobs[0].company == "Fallback Co"


def test_fetch_handles_missing_location_gracefully():
    hit = make_hit()
    del hit["_source"]["jobLocation"]
    payload = {"hits": {"total": {"value": 1}, "hits": [hit]}}

    def fake_post(url, json, timeout):
        return FakeResponse(payload)

    jobs = healthcaresource.fetch(make_source(), http_post=fake_post)

    assert jobs[0].location is None


def test_fetch_maps_multiple_hits_in_order():
    payload = {"hits": {"total": {"value": 2}, "hits": [
        make_hit(hit_id="4730_1", title="Nurse"),
        make_hit(hit_id="4730_2", title="Therapist"),
    ]}}

    def fake_post(url, json, timeout):
        return FakeResponse(payload)

    jobs = healthcaresource.fetch(make_source(), http_post=fake_post)

    assert [j.title for j in jobs] == ["Nurse", "Therapist"]
    assert [j.key for j in jobs] == ["healthcaresource:4730_1", "healthcaresource:4730_2"]


def test_fetch_returns_empty_list_when_no_hits():
    payload = {"hits": {"total": {"value": 0}, "hits": []}}

    def fake_post(url, json, timeout):
        return FakeResponse(payload)

    jobs = healthcaresource.fetch(make_source(), http_post=fake_post)

    assert jobs == []


def test_fetch_skips_malformed_record_and_keeps_valid_ones():
    payload = {"hits": {"total": {"value": 3}, "hits": [
        make_hit(hit_id="1_001", title="Good One"),
        {"_source": {}},  # malformed: no '_id' → KeyError
        make_hit(hit_id="1_003", title="Good Three"),
    ]}}

    def fake_post(url, json, timeout):
        return FakeResponse(payload)

    jobs = healthcaresource.fetch(make_source(), http_post=fake_post)

    assert len(jobs) == 2
    assert jobs[0].key == "healthcaresource:1_001"
    assert jobs[1].key == "healthcaresource:1_003"


def test_fetch_url_encodes_site_id_with_special_characters():
    search_calls = []

    def fake_post(url, json, timeout):
        search_calls.append(url)
        return FakeResponse({"hits": {"total": {"value": 1}, "hits": [make_hit()]}})

    source = HealthcareSource(id="s1", name="Test", type="healthcaresource", site_id="r c/mc")
    jobs = healthcaresource.fetch(source, http_post=fake_post)

    assert search_calls[0] == "https://pm.healthcaresource.com/JobseekerSearchAPI/r%20c%2Fmc/api/Search?size=1000"
    assert jobs[0].url == "https://pm.healthcaresource.com/CS/r%20c%2Fmc/#/job/12040"
