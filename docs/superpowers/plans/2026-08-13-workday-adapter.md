# Workday Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `workday` as a ninth CareerSpyder source type so employers on Workday's recruiting platform (e.g. Duly Health and Care) can be scraped via Workday's public CXS jobs API, with pagination that correctly accounts for two verified API quirks (unreliable `total` after page 1, silent wrap-around past the end).

**Architecture:** A new `WorkdaySource` config model plus a new `app/adapters/workday.py`. The adapter derives both the API URL and the job-detail-URL origin directly from the single `career_site_url` config field, fetches page 1 first to capture and freeze the real `total`, then fetches exactly the remaining pages that `total` implies — never trusting `total` from any later response, and never looping past the frozen bound (which would silently re-fetch page 1's content instead of failing loudly).

**Tech Stack:** Same as the rest of the project — Python 3.12, Pydantic v2, `requests`, pytest.

## Global Constraints

- Tests must not make live network calls or launch a real browser (existing project-wide constraint) — `workday.fetch()` takes an injectable `http_post`, same pattern as every other HTTP-based adapter.
- The API endpoint is derived, not configured directly: `{origin}/wday/cxs/{tenant}/{site}/jobs`, where `origin` is the scheme+host of `career_site_url`, `tenant` is the first label of that host, and `site` is the last path segment of `career_site_url`.
- Request body is always `{"appliedFacets": {}, "limit": 20, "offset": N, "searchText": ""}` — CareerSpyder's own `include_keywords`/`exclude_keywords` handle filtering, matching every other adapter.
- **`total` must only ever be read from the very first (`offset: 0`) response, and frozen there.** Every later response's `total` is ignored. This is a verified real-API quirk (`total` reports `0` on later pages despite real results), not a defensive assumption.
- **The pagination loop must never request an offset at or past the frozen `total`.** A real, verified API quirk: doing so doesn't return an empty page, it silently returns page 1's content again. The loop bound is `min(total, max_pages * 20)`, computed once from the frozen `total`.
- Design spec: `docs/superpowers/specs/2026-08-13-workday-adapter-design.md`.

---

### Task 1: `WorkdaySource` config model

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `BaseSource` (existing).
- Produces: `WorkdaySource` (pydantic model: `type: Literal["workday"]`, `career_site_url: str` non-empty, `max_pages: int = 60`), added to the `SourceConfig` discriminated union.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py` (after `test_talentbrew_max_pages_defaults_to_sixty`):

```python
def test_workday_rejects_empty_career_site_url():
    with pytest.raises(ValidationError):
        config.WorkdaySource(name="Duly", type="workday", career_site_url="")


def test_workday_max_pages_defaults_to_sixty():
    source = config.WorkdaySource(
        name="Duly", type="workday",
        career_site_url="https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly",
    )
    assert source.max_pages == 60
```

Also add a `workday` entry to `test_load_sources_parses_each_type`'s fixture list and assertion:

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
        {
            "id": "s9", "name": "Duly (Workday)", "type": "workday",
            "career_site_url": "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly", "max_pages": 20,
        },
    ])

    sources = config.load_sources(str(path))

    assert [s.type for s in sources] == [
        "greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor",
        "healthcaresource", "talentbrew", "workday",
    ]
    assert sources[0].board_token == "acme"
    assert sources[2].selectors.job_card == ".job"
    assert sources[5].max_pages == 5
    assert sources[6].site_id == "rcmc"
    assert sources[7].base_url == "https://jobs.nm.org"
    assert sources[7].max_pages == 10
    assert sources[8].career_site_url == "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly"
    assert sources[8].max_pages == 20
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: module 'app.config' has no attribute 'WorkdaySource'`.

- [ ] **Step 3: Add `WorkdaySource` to `app/config.py`**

Change:

```python
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

to:

```python
class TalentBrewSource(BaseSource):
    type: Literal["talentbrew"]
    base_url: str = Field(min_length=1)
    max_pages: int = 60


class WorkdaySource(BaseSource):
    type: Literal["workday"]
    career_site_url: str = Field(min_length=1)
    max_pages: int = 60


SourceConfig = Annotated[
    GreenhouseSource | LeverSource | GenericHtmlSource | LinkedInSource | IndeedSource | InforSource
    | HealthcareSource | TalentBrewSource | WorkdaySource,
    Field(discriminator="type"),
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: all pass (18 tests).

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add WorkdaySource config model"
```

---

### Task 2: `workday` adapter

**Files:**
- Create: `app/adapters/workday.py`
- Create: `tests/adapters/test_workday.py`

**Interfaces:**
- Consumes: `Job` (existing), `WorkdaySource` (Task 1).
- Produces: `workday.fetch(source: WorkdaySource, http_post=requests.post) -> list[Job]` — registered in Task 3's `ADAPTERS` dict.

**Context:** Real response shape, confirmed via direct `curl` calls against Duly Health and Care's live Workday site:

```json
{
  "total": 341,
  "jobPostings": [
    {
      "title": "Infusion Therapy Registered Nurse",
      "externalPath": "/job/Hinsdale-Illinois/Infusion-Therapy-Registered-Nurse_JR117797-1",
      "locationsText": "Hinsdale, Illinois",
      "postedOn": "Posted Today",
      "bulletFields": ["Regular", "JR117797"]
    }
  ]
}
```

The two verified pagination quirks (from the design spec — reproduce their exact behavior in the fixtures, don't just assume them): `total` is only correct on the `offset: 0` response (later pages report `0` despite real results), and requesting an offset at or past the true total returns page 1's content again instead of an empty list.

- [ ] **Step 1: Create `tests/adapters/test_workday.py` with the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/adapters/test_workday.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.workday'`.

- [ ] **Step 3: Write `app/adapters/workday.py`**

```python
from urllib.parse import urlparse

import requests

from app.config import WorkdaySource
from app.models import Job

_PAGE_SIZE = 20


def _resolve(career_site_url: str) -> tuple[str, str]:
    """Returns (api_url, origin), both derived from the career site URL."""
    parsed = urlparse(career_site_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    tenant = parsed.netloc.split(".")[0]
    site = parsed.path.strip("/").split("/")[-1]
    return f"{origin}/wday/cxs/{tenant}/{site}/jobs", origin


def _parse_postings(postings: list[dict], source: WorkdaySource, origin: str) -> list[Job]:
    jobs = []
    for posting in postings:
        bullet_fields = posting.get("bulletFields") or []
        external_path = posting.get("externalPath", "")
        requisition_id = bullet_fields[1] if len(bullet_fields) > 1 else external_path
        jobs.append(Job(
            key=f"workday:{requisition_id}",
            title=posting["title"],
            url=f"{origin}{external_path}",
            company=source.company,
            location=posting.get("locationsText"),
            posted_date=posting.get("postedOn"),
            source_name=source.name,
        ))
    return jobs


def fetch(source: WorkdaySource, http_post=requests.post) -> list[Job]:
    api_url, origin = _resolve(source.career_site_url)

    def fetch_page(offset: int):
        resp = http_post(
            api_url,
            json={"appliedFacets": {}, "limit": _PAGE_SIZE, "offset": offset, "searchText": ""},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    first_page = fetch_page(0)
    total = first_page.get("total", 0)
    all_jobs = _parse_postings(first_page.get("jobPostings", []), source, origin)

    # `total` is only trustworthy on this first response -- every later
    # response reports 0 regardless of how many real results remain, and
    # requesting an offset at/past this frozen total wraps back around to
    # page 1's content instead of returning empty. Both verified directly
    # against a real Workday site -- never re-derive the bound mid-loop.
    max_offset = min(total, source.max_pages * _PAGE_SIZE)

    offset = _PAGE_SIZE
    while offset < max_offset:
        page = fetch_page(offset)
        all_jobs.extend(_parse_postings(page.get("jobPostings", []), source, origin))
        offset += _PAGE_SIZE

    return all_jobs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/adapters/test_workday.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/adapters/workday.py tests/adapters/test_workday.py
git commit -m "feat: add Workday adapter with total-freezing pagination"
```

---

### Task 3: Register the adapter

**Files:**
- Modify: `app/adapters/__init__.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `workday.fetch` (Task 2).
- Produces: `ADAPTERS["workday"]`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py` (near `test_talentbrew_adapter_is_registered`):

```python
def test_workday_adapter_is_registered():
    from app.adapters import ADAPTERS
    assert "workday" in ADAPTERS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py::test_workday_adapter_is_registered -v`
Expected: FAIL — `AssertionError`.

- [ ] **Step 3: Register `workday` in `app/adapters/__init__.py`**

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
    workday,
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
    "workday": workday.fetch,
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
git commit -m "feat: register workday adapter"
```

---

### Task 4: Web UI wiring — source form

**Files:**
- Modify: `app/web/source_form.py`
- Modify: `app/web/templates/source_form.html`
- Test: `tests/web/test_source_form_helper.py`
- Test: `tests/web/test_source_form.py`

**Interfaces:**
- Consumes: `WorkdaySource` (Task 1).
- Produces: `/sources/new` and `/sources/{id}/edit` support `type=workday` end to end.

**Context:** `max_pages` is already a shared form field name (used by `infor`/`talentbrew`) and `echo_source` already exposes it generically — no new echo-side field needed for that one. Only `career_site_url` is new.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_source_form_helper.py` (after `test_talentbrew_max_pages_defaults_when_field_blank`):

```python
def test_parses_workday_fields():
    form = {
        "type": "workday", "name": "Duly (Workday)",
        "career_site_url": "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly",
        "max_pages": "20", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.type == "workday"
    assert source.career_site_url == "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly"
    assert source.max_pages == 20


def test_workday_max_pages_defaults_when_field_blank():
    form = {
        "type": "workday", "name": "Duly (Workday)",
        "career_site_url": "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly",
        "max_pages": "", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.max_pages == 60
```

Add to `tests/web/test_source_form.py` (after `test_post_new_talentbrew_source_with_empty_base_url_shows_error_and_does_not_save`):

```python
def test_post_new_workday_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "workday", "name": "Duly (Workday)",
        "career_site_url": "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly",
        "max_pages": "20", "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["type"] == "workday"
    assert saved[0]["career_site_url"] == "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly"
    assert saved[0]["max_pages"] == 20


def test_post_new_workday_source_with_empty_career_site_url_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "workday", "name": "Duly (Workday)", "career_site_url": "",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    with open(client.app.state.sources_path) as f:
        assert json.load(f)["sources"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_source_form_helper.py tests/web/test_source_form.py -v -k workday`
Expected: FAIL — `KeyError: 'workday'`.

- [ ] **Step 3: Wire `WorkdaySource` into `app/web/source_form.py`**

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
    WorkdaySource,
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
    "workday": WorkdaySource,
}
```

Then add a branch to `source_from_form`, changing:

```python
    elif source_type == "talentbrew":
        if "base_url" in form:
            common["base_url"] = _strip(form["base_url"])
        if form.get("max_pages"):
            common["max_pages"] = int(form["max_pages"])
    else:
```

to:

```python
    elif source_type == "talentbrew":
        if "base_url" in form:
            common["base_url"] = _strip(form["base_url"])
        if form.get("max_pages"):
            common["max_pages"] = int(form["max_pages"])
    elif source_type == "workday":
        if "career_site_url" in form:
            common["career_site_url"] = _strip(form["career_site_url"])
        if form.get("max_pages"):
            common["max_pages"] = int(form["max_pages"])
    else:
```

Then add `career_site_url` to `echo_source`'s returned `SimpleNamespace`, changing:

```python
        max_pages=form.get("max_pages", ""),
        site_id=form.get("site_id", ""),
        base_url=form.get("base_url", ""),
        include_keywords=_keywords(form.get("include_keywords", "")),
        exclude_keywords=_keywords(form.get("exclude_keywords", "")),
    )
```

to:

```python
        max_pages=form.get("max_pages", ""),
        site_id=form.get("site_id", ""),
        base_url=form.get("base_url", ""),
        career_site_url=form.get("career_site_url", ""),
        include_keywords=_keywords(form.get("include_keywords", "")),
        exclude_keywords=_keywords(form.get("exclude_keywords", "")),
    )
```

- [ ] **Step 4: Add the `workday` type option and fields to `app/web/templates/source_form.html`**

Change:

```html
      {% for t in ["greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor", "healthcaresource", "talentbrew"] %}
```

to:

```html
      {% for t in ["greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor", "healthcaresource", "talentbrew", "workday"] %}
```

Change:

```html
  <div id="fields-talentbrew" class="type-fields">
    <label>Base URL <input type="text" name="base_url" value="{{ source.base_url if source and source.type == 'talentbrew' else '' }}"></label><br>
    <label>Max pages <input type="number" name="max_pages" value="{{ source.max_pages if source and source.type == 'talentbrew' else 60 }}"></label>
  </div>
```

to:

```html
  <div id="fields-talentbrew" class="type-fields">
    <label>Base URL <input type="text" name="base_url" value="{{ source.base_url if source and source.type == 'talentbrew' else '' }}"></label><br>
    <label>Max pages <input type="number" name="max_pages" value="{{ source.max_pages if source and source.type == 'talentbrew' else 60 }}"></label>
  </div>
  <div id="fields-workday" class="type-fields">
    <label>Career site URL <input type="text" name="career_site_url" value="{{ source.career_site_url if source and source.type == 'workday' else '' }}"></label><br>
    <label>Max pages <input type="number" name="max_pages" value="{{ source.max_pages if source and source.type == 'workday' else 60 }}"></label>
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
git commit -m "feat: add workday source type to the web UI form"
```

---

### Task 5: Manual smoke test and documentation

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: a verified-working `workday` source type, documented for users and future maintainers.

**Note for whoever executes this task:** Step 1 hits a real, live third-party site (Duly Health and Care's actual careers site) across potentially many pages. Run it once, not repeatedly.

- [ ] **Step 1: Manual smoke test against the real Duly Health and Care site**

In a scratch Python shell or a throwaway script, run:

```python
from app.adapters import workday
from app.config import WorkdaySource

source = WorkdaySource(
    name="Duly (Workday) smoke test",
    type="workday",
    career_site_url="https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly",
    max_pages=60,
)
jobs = workday.fetch(source)
print(f"{len(jobs)} jobs found")

keys = [j.key for j in jobs]
print(f"unique keys: {len(set(keys))} (should equal total)")

for j in jobs[:5]:
    print(j.title, "|", j.location, "|", j.url)
```

Expected: several hundred jobs found (the real count may have changed
since this plan was written — 341 was observed during investigation),
with `unique keys == total jobs` (confirming the pagination bound is
exactly right — neither missing the tail nor wrapping into duplicates),
and each printed job having a real, resolvable `url`.

- [ ] **Step 2: Run the full suite one more time**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 3: Update `README.md`'s source type documentation**

In the "`sources.json`" section's field-reference table, change:

```markdown
| `talentbrew` | `base_url` | For employers on Radancy's TalentBrew career-site platform (e.g. `jobs.nm.org`). `base_url` is just the site's origin. Calls the platform's own internal AJAX results endpoint with an explicit Title-A-Z sort — the default "Relevancy" sort was found to paginate unreliably (overlapping pages), so this adapter deliberately avoids it. Paginates automatically up to the platform's own reported total page count, capped by `max_pages` (default 60) as a safety backstop. |
```

to:

```markdown
| `talentbrew` | `base_url` | For employers on Radancy's TalentBrew career-site platform (e.g. `jobs.nm.org`). `base_url` is just the site's origin. Calls the platform's own internal AJAX results endpoint with an explicit Title-A-Z sort — the default "Relevancy" sort was found to paginate unreliably (overlapping pages), so this adapter deliberately avoids it. Paginates automatically up to the platform's own reported total page count, capped by `max_pages` (default 60) as a safety backstop. |
| `workday` | `career_site_url` | For employers on Workday's recruiting platform — one of the largest ATS platforms, and this adapter works identically for any Workday tenant, not just the one it was built against. `career_site_url` is the full career site URL (e.g. `https://<tenant>.wd1.myworkdayjobs.com/<site>`); the API URL and job-detail links are both derived from it. No auth, no browser needed. Two verified API quirks are handled internally: the reported result total is only trustworthy on the first page (later pages report 0 regardless), and requesting a page past the real end silently wraps back to page 1 instead of returning empty — the adapter freezes the total from page 1 and never crosses that computed boundary. |
```

- [ ] **Step 4: Add a CHANGELOG entry**

In `CHANGELOG.md`'s `[Unreleased]` → `### Added` section, add:

```markdown
- `workday` source type, for employers on Workday's recruiting platform
  (e.g. Duly Health and Care). Calls Workday's public CXS jobs API
  directly — no auth, no browser, and the same adapter works for any
  Workday tenant. Handles two verified pagination quirks: the reported
  result total is only trustworthy on the first page, and paging past
  the real end silently wraps back to page 1 instead of returning empty.
```

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: document the workday source type"
```

---

## Self-Review Notes

- **Spec coverage:** every section of `docs/superpowers/specs/2026-08-13-workday-adapter-design.md` maps to a task — config schema (Task 1), URL derivation + total-freezing pagination + Job mapping (Task 2), `ADAPTERS` registration (Task 3), web UI wiring (Task 4), manual smoke test + docs (Task 5).
- **Placeholder scan:** none — every code block is complete, real content, including the exact verified request/response shapes and both verified pagination quirks from the live site.
- **Type consistency:** `WorkdaySource` (Task 1) is imported identically in `app/adapters/workday.py` (Task 2), `app/adapters/__init__.py` (Task 3), and `app/web/source_form.py` (Task 4). `workday.fetch`'s signature (`source: WorkdaySource, http_post=requests.post`) matches the calling convention every other adapter already uses.
- **Both verified API quirks are enforced in code, not just documented** — `total` is read exactly once (`first_page.get("total", 0)`, never re-read from a later response), and the loop condition (`offset < max_offset`, where `max_offset` is computed once from that frozen value) makes it structurally impossible to request an offset at or past the frozen total, matching the two dedicated regression tests in Task 2 that would fail loudly (via the fake's own `AssertionError`) if this were ever violated.
