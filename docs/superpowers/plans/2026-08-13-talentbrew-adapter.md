# TalentBrew Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `talentbrew` as an eighth CareerSpyder source type so employers on Radancy's TalentBrew career-site platform (e.g. Northwestern Medicine) can be scraped with reliable, complete pagination.

**Architecture:** A new `TalentBrewSource` config model plus a new `app/adapters/talentbrew.py` that calls the platform's internal AJAX results endpoint (`GET {base_url}/search-jobs/results`) with an explicit Title-A-Z sort (deterministic, unlike the site's default "Relevancy" sort, which was verified to produce overlapping/inconsistent pages). The endpoint returns JSON with an HTML fragment inside it; the adapter parses that fragment for job cards and for the platform's own reported `data-total-pages`, then loops until that count is reached (or a page comes back empty, or `max_pages` is hit as a safety cap).

**Tech Stack:** Same as the rest of the project — Python 3.12, Pydantic v2, `requests`, BeautifulSoup4, pytest.

## Global Constraints

- Tests must not make live network calls or launch a real browser (existing project-wide constraint) — `talentbrew.fetch()` takes an injectable `http_get`, same pattern as every other HTTP-based adapter.
- The results endpoint is `GET {base_url}/search-jobs/results`, with a fixed set of constant query parameters (captured verbatim from the real site's own AJAX call) plus a varying `CurrentPage`. `SortCriteria=3` (Title A-Z) is required for deterministic, non-overlapping pagination — the default `SortCriteria=0` (Relevancy) was verified to overlap between adjacent pages and must never be used.
- The endpoint's JSON response has the job-card HTML inside a `results` key, not as the top-level response body — `resp.json()["results"]`, not `resp.text`, is what gets parsed.
- The wrapping `<section>` in that HTML fragment carries `data-total-pages="N"` — extract this from page 1's response and stop the loop there, rather than looping to `max_pages` unconditionally.
- `posted_date` is always `None` for this adapter — not exposed in the list view.
- Design spec: `docs/superpowers/specs/2026-08-13-talentbrew-adapter-design.md`.

---

### Task 1: `TalentBrewSource` config model

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `BaseSource` (existing).
- Produces: `TalentBrewSource` (pydantic model: `type: Literal["talentbrew"]`, `base_url: str` non-empty, `max_pages: int = 60`), added to the `SourceConfig` discriminated union.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py` (after `test_healthcaresource_rejects_empty_site_id`):

```python
def test_talentbrew_rejects_empty_base_url():
    with pytest.raises(ValidationError):
        config.TalentBrewSource(name="Northwestern Medicine", type="talentbrew", base_url="")


def test_talentbrew_max_pages_defaults_to_sixty():
    source = config.TalentBrewSource(name="Northwestern Medicine", type="talentbrew", base_url="https://jobs.nm.org")
    assert source.max_pages == 60
```

Also add a `talentbrew` entry to `test_load_sources_parses_each_type`'s fixture list and assertion:

```python
def test_load_sources_parses_each_type(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [
        {"id": "s1", "name": "Acme (Greenhouse)", "type": "greenhouse", "board_token": "acme"},
        {"id": "s2", "name": "Beta (Lever)", "type": "lever", "board_token": "beta"},
        {
            "id": "s3", "name": "Custom Co", "type": "generic_html",
            "url": "https://customco.test/careers",
            "selectors": {"job_card": ".job", "title": ".t", "link": "a"},
        },
        {"id": "s4", "name": "LinkedIn", "type": "linkedin", "url": "https://linkedin.test/jobs"},
        {"id": "s5", "name": "Indeed", "type": "indeed", "url": "https://indeed.test/jobs"},
        {"id": "s6", "name": "Rush (Infor)", "type": "infor", "url": "https://rush.test/careers", "max_pages": 5},
        {"id": "s7", "name": "Rush Copley (HealthcareSource)", "type": "healthcaresource", "site_id": "rcmc"},
        {"id": "s8", "name": "NM (TalentBrew)", "type": "talentbrew", "base_url": "https://jobs.nm.org", "max_pages": 10},
    ])

    sources = config.load_sources(str(path))

    assert [s.type for s in sources] == [
        "greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor", "healthcaresource", "talentbrew",
    ]
    assert sources[0].board_token == "acme"
    assert sources[2].selectors.job_card == ".job"
    assert sources[5].max_pages == 5
    assert sources[6].site_id == "rcmc"
    assert sources[7].base_url == "https://jobs.nm.org"
    assert sources[7].max_pages == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: module 'app.config' has no attribute 'TalentBrewSource'`.

- [ ] **Step 3: Add `TalentBrewSource` to `app/config.py`**

Change:

```python
class HealthcareSource(BaseSource):
    type: Literal["healthcaresource"]
    site_id: str = Field(min_length=1)


SourceConfig = Annotated[
    GreenhouseSource | LeverSource | GenericHtmlSource | LinkedInSource | IndeedSource | InforSource | HealthcareSource,
    Field(discriminator="type"),
]
```

to:

```python
class HealthcareSource(BaseSource):
    type: Literal["healthcaresource"]
    site_id: str = Field(min_length=1)


class TalentBrewSource(BaseSource):
    type: Literal["talentbrew"]
    base_url: str = Field(min_length=1)
    max_pages: int = 60


SourceConfig = Annotated[
    GreenhouseSource | LeverSource | GenericHtmlSource | LinkedInSource | IndeedSource | InforSource
    | HealthcareSource | TalentBrewSource,
    Field(discriminator="type"),
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: all pass (16 tests).

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add TalentBrewSource config model"
```

---

### Task 2: `talentbrew` adapter

**Files:**
- Create: `app/adapters/talentbrew.py`
- Create: `tests/adapters/test_talentbrew.py`

**Interfaces:**
- Consumes: `Job` (existing), `TalentBrewSource` (Task 1).
- Produces: `talentbrew.fetch(source: TalentBrewSource, http_get=requests.get) -> list[Job]` — registered in Task 3's `ADAPTERS` dict.

**Context:** Real job-card HTML structure, confirmed via live DOM inspection of Northwestern Medicine's TalentBrew site:

```html
<ul class="search-job-list-data">
  <li>
    <a href="/job/warrenville/radiation-therapist-full-time/27763/98562951856" data-job-id="98562951856">
      <h2>Radiation Therapist Full time</h2>
    </a>
    <span class="job-jobStatus">Full-Time</span>
    <span class="job-campaign">Evening Job (2nd)</span>
    <span class="job-location">Warrenville, IL</span>
    <span>Job REQID: 217709</span>
  </li>
</ul>
```

The results-endpoint response wraps this in JSON, with the whole fragment inside a `<section>` carrying `data-total-pages`:

```json
{"filters": "...", "results": "<section id=\"search-results\" data-total-pages=\"57\" data-total-results=\"1401\" ...>...<ul class=\"search-job-list-data\">...</ul>...</section>", "hasJobs": true, "hasContent": true}
```

Real, verified request parameters (everything except `CurrentPage` is constant for this deployment):

```python
{
    "ActiveFacetID": "0", "RecordsPerPage": "25", "TotalContentResults": "",
    "Distance": "50", "RadiusUnitType": "0", "Keywords": "", "Location": "",
    "ShowRadius": "False", "IsPagination": "True", "CustomFacetName": "",
    "FacetTerm": "", "FacetType": "0",
    "SearchResultsModuleName": "Search Results", "SearchFiltersModuleName": "Search Filters",
    "SortCriteria": "3", "SortDirection": "0", "SearchType": "1", "PostalCode": "",
    "ResultsType": "0", "fc": "", "fl": "", "fcf": "", "afc": "", "afl": "", "afcf": "",
    "TotalContentPages": "",
}
```

- [ ] **Step 1: Create `tests/adapters/test_talentbrew.py` with the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/adapters/test_talentbrew.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.talentbrew'`.

- [ ] **Step 3: Write `app/adapters/talentbrew.py`**

```python
import re

import requests
from bs4 import BeautifulSoup

from app.config import TalentBrewSource
from app.models import Job

_RESULTS_PARAMS = {
    "ActiveFacetID": "0",
    "RecordsPerPage": "25",
    "TotalContentResults": "",
    "Distance": "50",
    "RadiusUnitType": "0",
    "Keywords": "",
    "Location": "",
    "ShowRadius": "False",
    "IsPagination": "True",
    "CustomFacetName": "",
    "FacetTerm": "",
    "FacetType": "0",
    "SearchResultsModuleName": "Search Results",
    "SearchFiltersModuleName": "Search Filters",
    # Title (A-Z), not the page's default Relevancy (0) -- Relevancy was
    # verified to produce overlapping, non-deterministic pagination on a
    # real TalentBrew site.
    "SortCriteria": "3",
    "SortDirection": "0",
    "SearchType": "1",
    "PostalCode": "",
    "ResultsType": "0",
    "fc": "",
    "fl": "",
    "fcf": "",
    "afc": "",
    "afl": "",
    "afcf": "",
    "TotalContentPages": "",
}

_TOTAL_PAGES_RE = re.compile(r'data-total-pages="(\d+)"')


def _parse_page(html: str, source: TalentBrewSource) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select(".search-job-list-data li"):
        link = card.select_one("a")
        heading = card.select_one("h2")
        if link is None or heading is None:
            continue
        job_id = link.get("data-job-id")
        href = link.get("href", "")
        location_el = card.select_one(".job-location")
        jobs.append(Job(
            key=f"talentbrew:{job_id}",
            title=heading.get_text(strip=True),
            url=f"{source.base_url}{href}",
            company=source.company,
            location=location_el.get_text(strip=True) if location_el else None,
            posted_date=None,
            source_name=source.name,
        ))
    return jobs


def fetch(source: TalentBrewSource, http_get=requests.get) -> list[Job]:
    all_jobs: list[Job] = []
    total_pages = None
    page = 1
    while page <= source.max_pages and (total_pages is None or page <= total_pages):
        params = {**_RESULTS_PARAMS, "CurrentPage": str(page)}
        resp = http_get(
            f"{source.base_url}/search-jobs/results", params=params, timeout=15,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        resp.raise_for_status()
        html = resp.json().get("results", "")

        if total_pages is None:
            match = _TOTAL_PAGES_RE.search(html)
            total_pages = int(match.group(1)) if match else 1

        page_jobs = _parse_page(html, source)
        if not page_jobs:
            break
        all_jobs.extend(page_jobs)
        page += 1

    return all_jobs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/adapters/test_talentbrew.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/adapters/talentbrew.py tests/adapters/test_talentbrew.py
git commit -m "feat: add TalentBrew adapter with deterministic pagination"
```

---

### Task 3: Register the adapter

**Files:**
- Modify: `app/adapters/__init__.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `talentbrew.fetch` (Task 2).
- Produces: `ADAPTERS["talentbrew"]`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py` (near `test_healthcaresource_adapter_is_registered`):

```python
def test_talentbrew_adapter_is_registered():
    from app.adapters import ADAPTERS
    assert "talentbrew" in ADAPTERS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py::test_talentbrew_adapter_is_registered -v`
Expected: FAIL — `AssertionError`.

- [ ] **Step 3: Register `talentbrew` in `app/adapters/__init__.py`**

Change:

```python
from app.adapters import (
    generic_html,
    greenhouse,
    healthcaresource,
    indeed,
    infor,
    lever,
    linkedin,
)
from app.models import Job

ADAPTERS: dict[str, Callable[..., list[Job]]] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "generic_html": generic_html.fetch,
    "linkedin": linkedin.fetch,
    "indeed": indeed.fetch,
    "infor": infor.fetch,
    "healthcaresource": healthcaresource.fetch,
}
```

to:

```python
from app.adapters import (
    generic_html,
    greenhouse,
    healthcaresource,
    indeed,
    infor,
    lever,
    linkedin,
    talentbrew,
)
from app.models import Job

ADAPTERS: dict[str, Callable[..., list[Job]]] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "generic_html": generic_html.fetch,
    "linkedin": linkedin.fetch,
    "indeed": indeed.fetch,
    "infor": infor.fetch,
    "healthcaresource": healthcaresource.fetch,
    "talentbrew": talentbrew.fetch,
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_orchestrator.py -v`
Expected: all pass, including the new test.

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/adapters/__init__.py tests/test_orchestrator.py
git commit -m "feat: register talentbrew adapter"
```

---

### Task 4: Web UI wiring — source form

**Files:**
- Modify: `app/web/source_form.py`
- Modify: `app/web/templates/source_form.html`
- Test: `tests/web/test_source_form_helper.py`
- Test: `tests/web/test_source_form.py`

**Interfaces:**
- Consumes: `TalentBrewSource` (Task 1).
- Produces: `/sources/new` and `/sources/{id}/edit` support `type=talentbrew` end to end.

**Context:** `max_pages` is already a shared form field name (used by `infor`) and `echo_source` already exposes it generically — no new echo-side field needed for that one. Only `base_url` is new.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_source_form_helper.py` (after `test_parses_healthcaresource_fields`):

```python
def test_parses_talentbrew_fields():
    form = {
        "type": "talentbrew", "name": "NM (TalentBrew)", "base_url": "https://jobs.nm.org",
        "max_pages": "10", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.type == "talentbrew"
    assert source.base_url == "https://jobs.nm.org"
    assert source.max_pages == 10


def test_talentbrew_max_pages_defaults_when_field_blank():
    form = {
        "type": "talentbrew", "name": "NM (TalentBrew)", "base_url": "https://jobs.nm.org",
        "max_pages": "", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.max_pages == 60
```

Add to `tests/web/test_source_form.py` (after `test_post_new_healthcaresource_source_with_empty_site_id_shows_error_and_does_not_save`):

```python
def test_post_new_talentbrew_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "talentbrew", "name": "NM (TalentBrew)", "base_url": "https://jobs.nm.org",
        "max_pages": "10", "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["type"] == "talentbrew"
    assert saved[0]["base_url"] == "https://jobs.nm.org"
    assert saved[0]["max_pages"] == 10


def test_post_new_talentbrew_source_with_empty_base_url_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "talentbrew", "name": "NM (TalentBrew)", "base_url": "",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    with open(client.app.state.sources_path) as f:
        assert json.load(f)["sources"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_source_form_helper.py tests/web/test_source_form.py -v -k talentbrew`
Expected: FAIL — `KeyError: 'talentbrew'`.

- [ ] **Step 3: Wire `TalentBrewSource` into `app/web/source_form.py`**

Change:

```python
from app.config import (
    GenericHtmlSource,
    GreenhouseSource,
    HealthcareSource,
    IndeedSource,
    InforSource,
    LeverSource,
    LinkedInSource,
    Selectors,
)

TYPE_MODELS: dict[str, type[BaseModel]] = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "generic_html": GenericHtmlSource,
    "linkedin": LinkedInSource,
    "indeed": IndeedSource,
    "infor": InforSource,
    "healthcaresource": HealthcareSource,
}
```

to:

```python
from app.config import (
    GenericHtmlSource,
    GreenhouseSource,
    HealthcareSource,
    IndeedSource,
    InforSource,
    LeverSource,
    LinkedInSource,
    Selectors,
    TalentBrewSource,
)

TYPE_MODELS: dict[str, type[BaseModel]] = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "generic_html": GenericHtmlSource,
    "linkedin": LinkedInSource,
    "indeed": IndeedSource,
    "infor": InforSource,
    "healthcaresource": HealthcareSource,
    "talentbrew": TalentBrewSource,
}
```

Then add a branch to `source_from_form`, changing:

```python
    elif source_type == "healthcaresource":
        if "site_id" in form:
            common["site_id"] = _strip(form["site_id"])
    else:
```

to:

```python
    elif source_type == "healthcaresource":
        if "site_id" in form:
            common["site_id"] = _strip(form["site_id"])
    elif source_type == "talentbrew":
        if "base_url" in form:
            common["base_url"] = _strip(form["base_url"])
        if form.get("max_pages"):
            common["max_pages"] = int(form["max_pages"])
    else:
```

Then add `base_url` to `echo_source`'s returned `SimpleNamespace`, changing:

```python
        max_pages=form.get("max_pages", ""),
        site_id=form.get("site_id", ""),
        include_keywords=_keywords(form.get("include_keywords", "")),
        exclude_keywords=_keywords(form.get("exclude_keywords", "")),
    )
```

to:

```python
        max_pages=form.get("max_pages", ""),
        site_id=form.get("site_id", ""),
        base_url=form.get("base_url", ""),
        include_keywords=_keywords(form.get("include_keywords", "")),
        exclude_keywords=_keywords(form.get("exclude_keywords", "")),
    )
```

- [ ] **Step 4: Add the `talentbrew` type option and fields to `app/web/templates/source_form.html`**

Change:

```html
      {% for t in ["greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor", "healthcaresource"] %}
```

to:

```html
      {% for t in ["greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor", "healthcaresource", "talentbrew"] %}
```

Change:

```html
  <div id="fields-healthcaresource" class="type-fields">
    <label>Site ID <input type="text" name="site_id" value="{{ source.site_id if source and source.type == 'healthcaresource' else '' }}"></label>
  </div>
```

to:

```html
  <div id="fields-healthcaresource" class="type-fields">
    <label>Site ID <input type="text" name="site_id" value="{{ source.site_id if source and source.type == 'healthcaresource' else '' }}"></label>
  </div>
  <div id="fields-talentbrew" class="type-fields">
    <label>Base URL <input type="text" name="base_url" value="{{ source.base_url if source and source.type == 'talentbrew' else '' }}"></label><br>
    <label>Max pages <input type="number" name="max_pages" value="{{ source.max_pages if source and source.type == 'talentbrew' else 60 }}"></label>
  </div>
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/web/test_source_form_helper.py tests/web/test_source_form.py -v`
Expected: all pass.

- [ ] **Step 6: Run the full suite to confirm no regression**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/web/source_form.py app/web/templates/source_form.html tests/web/test_source_form_helper.py tests/web/test_source_form.py
git commit -m "feat: add talentbrew source type to the web UI form"
```

---

### Task 5: Manual smoke test and documentation

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: a verified-working `talentbrew` source type, documented for users and future maintainers.

**Note for whoever executes this task:** Step 1 hits a real, live third-party site (Northwestern Medicine's actual careers site) across potentially dozens of pages. This is a real request volume — run it once, not repeatedly.

- [ ] **Step 1: Manual smoke test against the real Northwestern Medicine site**

In a scratch Python shell or a throwaway script, run:

```python
from app.adapters import talentbrew
from app.config import TalentBrewSource

source = TalentBrewSource(
    name="NM (TalentBrew) smoke test",
    type="talentbrew",
    base_url="https://jobs.nm.org",
    max_pages=60,
)
jobs = talentbrew.fetch(source)
print(f"{len(jobs)} jobs found")

keys = [j.key for j in jobs]
print(f"unique keys: {len(set(keys))} (should equal total)")

for j in jobs[:5]:
    print(j.title, "|", j.location, "|", j.url)
```

Expected: several hundred jobs found (the real count may have changed
since this plan was written — around 1400 was observed during
investigation), with `unique keys == total jobs` (confirming no
duplicate/overlapping pages), and each printed job having a real,
resolvable `url`.

- [ ] **Step 2: Run the full suite one more time**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 3: Update `README.md`'s source type documentation**

In the "`sources.json`" section's field-reference table, change:

```markdown
| `healthcaresource` | `site_id` | For employers on the HealthcareSource/symplr talent platform (e.g. `pm.healthcaresource.com/CS/<site_id>`). Calls a directly-callable JSON API — no browser needed. Unlike `infor`, this platform has real per-job URLs and fetches every posting in one call (no pagination limit needed). |
```

to:

```markdown
| `healthcaresource` | `site_id` | For employers on the HealthcareSource/symplr talent platform (e.g. `pm.healthcaresource.com/CS/<site_id>`). Calls a directly-callable JSON API — no browser needed. Unlike `infor`, this platform has real per-job URLs and fetches every posting in one call (no pagination limit needed). |
| `talentbrew` | `base_url` | For employers on Radancy's TalentBrew career-site platform (e.g. `jobs.nm.org`). `base_url` is just the site's origin. Calls the platform's own internal AJAX results endpoint with an explicit Title-A-Z sort — the default "Relevancy" sort was found to paginate unreliably (overlapping pages), so this adapter deliberately avoids it. Paginates automatically up to the platform's own reported total page count, capped by `max_pages` (default 60) as a safety backstop. |
```

- [ ] **Step 4: Add a CHANGELOG entry**

In `CHANGELOG.md`'s `[Unreleased]` → `### Added` section, add:

```markdown
- `talentbrew` source type, for employers on Radancy's TalentBrew
  career-site platform (e.g. Northwestern Medicine). Calls the
  platform's internal AJAX results endpoint with an explicit Title-A-Z
  sort for deterministic pagination — the default "Relevancy" sort was
  verified to produce overlapping, unreliable pages on a real site.
```

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: document the talentbrew source type"
```

---

## Self-Review Notes

- **Spec coverage:** every section of `docs/superpowers/specs/2026-08-13-talentbrew-adapter-design.md` maps to a task — config schema (Task 1), results-endpoint call + pagination + Job mapping (Task 2), `ADAPTERS` registration (Task 3), web UI wiring (Task 4), manual smoke test + docs (Task 5).
- **Placeholder scan:** none — every code block is complete, real content, including the exact verified request parameters and response shape from the live site.
- **Type consistency:** `TalentBrewSource` (Task 1) is imported identically in `app/adapters/talentbrew.py` (Task 2), `app/adapters/__init__.py` (Task 3), and `app/web/source_form.py` (Task 4). `talentbrew.fetch`'s signature (`source: TalentBrewSource, http_get=requests.get`) matches the calling convention every other adapter already uses.
- **The deterministic-sort requirement is enforced in code, not just documented** — `SortCriteria: "3"` is a fixed value in `_RESULTS_PARAMS`, not a per-source config option, so there's no way to accidentally configure a `talentbrew` source back into the unreliable default sort.
