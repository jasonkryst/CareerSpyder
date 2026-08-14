from app.adapters import talentbrew
from app.config import TalentBrewSource


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def make_card(job_id="98562951856", title="Radiation Therapist Full time",
              href="/job/warrenville/radiation-therapist-full-time/27763/98562951856",
              location="Warrenville, IL"):
    return f"""
    <li>
      <a href="{href}" data-job-id="{job_id}">
        <h2>{title}</h2>
      </a>
      <span class="job-jobStatus">Full-Time</span>
      <span class="job-location">{location}</span>
    </li>
    """


def make_envelope(total_pages, cards_html):
    section = (
        f'<section id="search-results" data-total-pages="{total_pages}" data-total-results="1401">'
        f'<ul class="search-job-list-data">{cards_html}</ul>'
        f'</section>'
    )
    return {"filters": "", "results": section, "hasJobs": True, "hasContent": True}


def make_source(max_pages=60):
    return TalentBrewSource(
        id="s1", name="NM (TalentBrew)", company="Northwestern Medicine",
        type="talentbrew", base_url="https://jobs.nm.org", max_pages=max_pages,
    )


def test_fetch_maps_talentbrew_jobs_to_job_objects():
    payload = make_envelope(1, make_card())
    calls = []

    def fake_get(url, params, timeout, headers):
        calls.append((url, params.get("CurrentPage")))
        return FakeResponse(payload)

    jobs = talentbrew.fetch(make_source(), http_get=fake_get)

    assert calls == [("https://jobs.nm.org/search-jobs/results", "1")]
    assert len(jobs) == 1
    assert jobs[0].key == "talentbrew:98562951856"
    assert jobs[0].title == "Radiation Therapist Full time"
    assert jobs[0].url == "https://jobs.nm.org/job/warrenville/radiation-therapist-full-time/27763/98562951856"
    assert jobs[0].company == "Northwestern Medicine"
    assert jobs[0].location == "Warrenville, IL"
    assert jobs[0].posted_date is None
    assert jobs[0].source_name == "NM (TalentBrew)"
    assert jobs[0].source_id == "s1"


def test_fetch_uses_title_az_sort_deterministically():
    calls = []

    def fake_get(url, params, timeout, headers):
        calls.append(params.get("SortCriteria"))
        return FakeResponse(make_envelope(1, ""))

    talentbrew.fetch(make_source(), http_get=fake_get)

    assert calls[0] == "3"


def test_fetch_paginates_until_reported_total_pages():
    calls = []

    def fake_get(url, params, timeout, headers):
        page = params.get("CurrentPage")
        calls.append(page)
        if page == "1":
            return FakeResponse(make_envelope(2, make_card(job_id="1", title="Nurse")))
        return FakeResponse(make_envelope(2, make_card(job_id="2", title="Therapist")))

    jobs = talentbrew.fetch(make_source(), http_get=fake_get)

    assert calls == ["1", "2"]
    assert [j.title for j in jobs] == ["Nurse", "Therapist"]


def test_fetch_stops_early_when_a_page_returns_no_cards():
    calls = []

    def fake_get(url, params, timeout, headers):
        page = params.get("CurrentPage")
        calls.append(page)
        if page == "1":
            return FakeResponse(make_envelope(5, make_card()))
        return FakeResponse(make_envelope(5, ""))

    jobs = talentbrew.fetch(make_source(max_pages=60), http_get=fake_get)

    assert calls == ["1", "2"]
    assert len(jobs) == 1


def test_fetch_respects_max_pages_as_a_hard_cap():
    calls = []

    def fake_get(url, params, timeout, headers):
        page = params.get("CurrentPage")
        calls.append(page)
        return FakeResponse(make_envelope(60, make_card(job_id=page, title=f"Job {page}")))

    jobs = talentbrew.fetch(make_source(max_pages=2), http_get=fake_get)

    assert calls == ["1", "2"]
    assert len(jobs) == 2


def test_fetch_handles_card_missing_location_gracefully():
    card = """
    <li>
      <a href="/job/x/y/1/2" data-job-id="2">
        <h2>No Location Job</h2>
      </a>
    </li>
    """
    payload = make_envelope(1, card)

    def fake_get(url, params, timeout, headers):
        return FakeResponse(payload)

    jobs = talentbrew.fetch(make_source(), http_get=fake_get)

    assert jobs[0].location is None
