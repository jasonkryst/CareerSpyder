from app.adapters import findly
from app.config import FindlySource


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def make_record(job_id=23633616, title="Public Safety Officer 1st shift - St Lukes Med Center",
                 url="https://careers.aah.org/job/23633616/public-safety-officer-1st-shift-st-lukes-med-center-milwaukee-wi/",
                 company_name="Advocate Aurora Health", primary_city="Milwaukee",
                 primary_state="WI", location_type="", open_date="2026-04-14T00:00:00Z"):
    return {
        "id": job_id, "title": title, "url": url, "company_name": company_name,
        "primary_city": primary_city, "primary_state": primary_state,
        "location_type": location_type, "open_date": open_date,
    }


def make_envelope(records, total_hits=None):
    return {"totalHits": total_hits if total_hits is not None else len(records), "queryResult": records}


def make_source(org_id="2297", max_pages=20, company=None):
    return FindlySource(
        id="s1", name="Advocate Health (Findly)", company=company,
        type="findly", org_id=org_id, career_site_url="https://careers.aah.org", max_pages=max_pages,
    )


def test_fetch_maps_findly_records_to_job_objects():
    def fake_get(url, params, timeout):
        return FakeResponse(make_envelope([make_record()]))

    jobs = findly.fetch(make_source(), http_get=fake_get)

    assert len(jobs) == 1
    assert jobs[0].key == "findly:23633616"
    assert jobs[0].title == "Public Safety Officer 1st shift - St Lukes Med Center"
    assert jobs[0].url == "https://careers.aah.org/job/23633616/public-safety-officer-1st-shift-st-lukes-med-center-milwaukee-wi/"
    assert jobs[0].company == "Advocate Aurora Health"
    assert jobs[0].location == "Milwaukee, WI"
    assert jobs[0].posted_date == "2026-04-14T00:00:00Z"
    assert jobs[0].source_name == "Advocate Health (Findly)"
    assert jobs[0].source_id == "s1"


def test_fetch_sends_expected_request_url_and_params():
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, params))
        return FakeResponse(make_envelope([]))

    findly.fetch(make_source(org_id="2297"), http_get=fake_get)

    url, params = calls[0]
    assert url == "https://jobsapi-internal.m-cloud.io/api/job"
    assert params == {
        "Organization": "2297", "Limit": 500, "offset": 1,
        "sortfield": "open_date", "sortorder": "descending",
    }


def test_fetch_falls_back_to_source_company_when_company_name_blank():
    record = make_record(company_name="")

    def fake_get(url, params, timeout):
        return FakeResponse(make_envelope([record]))

    jobs = findly.fetch(make_source(company="Advocate Health"), http_get=fake_get)

    assert jobs[0].company == "Advocate Health"


def test_fetch_uses_location_type_when_present():
    record = make_record(location_type="Remote")

    def fake_get(url, params, timeout):
        return FakeResponse(make_envelope([record]))

    jobs = findly.fetch(make_source(), http_get=fake_get)

    assert jobs[0].location == "Remote"


def test_fetch_builds_location_from_whichever_of_city_or_state_is_present():
    record = make_record(primary_city="", primary_state="WI")

    def fake_get(url, params, timeout):
        return FakeResponse(make_envelope([record]))

    jobs = findly.fetch(make_source(), http_get=fake_get)

    assert jobs[0].location == "WI"


def test_fetch_location_is_none_when_no_location_data_present():
    record = make_record(primary_city="", primary_state="", location_type="")

    def fake_get(url, params, timeout):
        return FakeResponse(make_envelope([record]))

    jobs = findly.fetch(make_source(), http_get=fake_get)

    assert jobs[0].location is None


def test_fetch_handles_missing_open_date_gracefully():
    record = make_record()
    del record["open_date"]

    def fake_get(url, params, timeout):
        return FakeResponse(make_envelope([record]))

    jobs = findly.fetch(make_source(), http_get=fake_get)

    assert jobs[0].posted_date is None


def test_fetch_paginates_using_offset_and_stops_on_a_short_page():
    calls = []

    def fake_get(url, params, timeout):
        offset = params["offset"]
        calls.append(offset)
        if offset == 1:
            records = [make_record(job_id=i) for i in range(500)]
            return FakeResponse(make_envelope(records, total_hits=600))
        records = [make_record(job_id=i) for i in range(500, 600)]
        return FakeResponse(make_envelope(records, total_hits=600))

    jobs = findly.fetch(make_source(), http_get=fake_get)

    assert calls == [1, 501]
    assert len(jobs) == 600


def test_fetch_respects_max_pages_as_a_hard_cap():
    calls = []

    def fake_get(url, params, timeout):
        offset = params["offset"]
        calls.append(offset)
        records = [make_record(job_id=n) for n in range(offset, offset + 500)]
        return FakeResponse(make_envelope(records, total_hits=5000))

    jobs = findly.fetch(make_source(max_pages=2), http_get=fake_get)

    assert calls == [1, 501]
    assert len(jobs) == 1000


def test_fetch_returns_empty_list_when_no_jobs():
    def fake_get(url, params, timeout):
        return FakeResponse(make_envelope([]))

    jobs = findly.fetch(make_source(), http_get=fake_get)

    assert jobs == []
