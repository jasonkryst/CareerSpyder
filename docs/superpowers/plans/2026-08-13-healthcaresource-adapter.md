# HealthcareSource Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `healthcaresource` as a seventh CareerSpyder source type so employers on the HealthcareSource/symplr talent platform (e.g. Rush Copley Medical Center) can be scraped like any other source.

**Architecture:** A new `HealthcareSource` config model plus a new `app/adapters/healthcaresource.py` that mirrors `greenhouse.py`/`lever.py` exactly — one injectable HTTP POST to a directly-callable, unauthenticated JSON (Elasticsearch-backed) API, parsed into `Job` objects. No Playwright, no pagination loop: `size=200` against a 117-job board returned every result in one call.

**Tech Stack:** Same as the rest of the project — Python 3.12, Pydantic v2, `requests`, pytest.

## Global Constraints

- Tests must not make live network calls or launch a real browser (existing project-wide constraint) — `healthcaresource.fetch()` takes an injectable `http_post`, same pattern as every other HTTP-based adapter's injectable I/O.
- The API endpoint is `https://pm.healthcaresource.com/JobseekerSearchAPI/{site_id}/api/Search?size=1000`, `POST`, JSON body — the request body is a fixed constant (captured verbatim from the real site's own network traffic), not built from per-source fields beyond `site_id` in the URL.
- The job detail URL is `https://pm.healthcaresource.com/CS/{site_id}/#/job/{job_id}`, where `job_id` is the part of the API response's `_id` field after the `_` (the `_id` itself is `"{clientId}_{jobId}"`).
- `company` comes from the API response's `hiringOrganization.name` per job (one board can span multiple facility names), falling back to `source.company` if that path is missing from a given hit.
- Design spec: `docs/superpowers/specs/2026-08-13-healthcaresource-adapter-design.md`.

---

### Task 1: `HealthcareSource` config model

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `BaseSource` (existing).
- Produces: `HealthcareSource` (pydantic model: `type: Literal["healthcaresource"]`, `site_id: str` non-empty), added to the `SourceConfig` discriminated union.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py` (after `test_infor_max_pages_defaults_to_three`):

```python
def test_healthcaresource_rejects_empty_site_id():
    with pytest.raises(ValidationError):
        config.HealthcareSource(name="Rush Copley", type="healthcaresource", site_id="")
```

Also add a `healthcaresource` entry to `test_load_sources_parses_each_type`'s fixture list and assertion:

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
    ])

    sources = config.load_sources(str(path))

    assert [s.type for s in sources] == [
        "greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor", "healthcaresource",
    ]
    assert sources[0].board_token == "acme"
    assert sources[2].selectors.job_card == ".job"
    assert sources[5].max_pages == 5
    assert sources[6].site_id == "rcmc"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: module 'app.config' has no attribute 'HealthcareSource'`.

- [ ] **Step 3: Add `HealthcareSource` to `app/config.py`**

Change:

```python
class InforSource(BaseSource):
    type: Literal["infor"]
    url: str = Field(min_length=1)
    max_pages: int = 3


SourceConfig = Annotated[
    GreenhouseSource | LeverSource | GenericHtmlSource | LinkedInSource | IndeedSource | InforSource,
    Field(discriminator="type"),
]
```

to:

```python
class InforSource(BaseSource):
    type: Literal["infor"]
    url: str = Field(min_length=1)
    max_pages: int = 3


class HealthcareSource(BaseSource):
    type: Literal["healthcaresource"]
    site_id: str = Field(min_length=1)


SourceConfig = Annotated[
    GreenhouseSource | LeverSource | GenericHtmlSource | LinkedInSource | IndeedSource | InforSource | HealthcareSource,
    Field(discriminator="type"),
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: all pass (14 tests).

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add HealthcareSource config model"
```

---

### Task 2: `healthcaresource` adapter

**Files:**
- Create: `app/adapters/healthcaresource.py`
- Create: `tests/adapters/test_healthcaresource.py`

**Interfaces:**
- Consumes: `Job` (existing), `HealthcareSource` (Task 1).
- Produces: `healthcaresource.fetch(source: HealthcareSource, http_post=requests.post) -> list[Job]` — registered in Task 3's `ADAPTERS` dict.

**Context:** Real API response shape, confirmed via live inspection of the Rush Copley board (`site_id=rcmc`) — request body captured verbatim from the site's own XHR call, response shape confirmed by calling the endpoint directly:

```json
{
  "hits": {
    "total": {"value": 117, "relation": "eq"},
    "hits": [
      {
        "_id": "4730_12040",
        "_source": {
          "title": "Athletic Trainer",
          "datePosted": "2026-06-29T00:00:00Z",
          "hiringOrganization": {"name": "Rush Copley Medical Center"},
          "jobLocation": {"address": {"addressLocalityRegion": "Yorkville, IL"}},
          "userArea": {"requisitionNumber": "16289"}
        }
      }
    ]
  }
}
```

Clicking this exact job in the real UI navigated to `https://pm.healthcaresource.com/CS/rcmc/#/job/12040` — confirmed by direct browser navigation, not inferred.

- [ ] **Step 1: Create `tests/adapters/test_healthcaresource.py` with the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/adapters/test_healthcaresource.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.healthcaresource'`.

- [ ] **Step 3: Write `app/adapters/healthcaresource.py`**

```python
import requests

from app.config import HealthcareSource
from app.models import Job

_SEARCH_BODY = {
    "query": {
        "bool": {
            "must": {"match_all": {}},
            "should": {"match": {"userArea.isFeaturedJob": {"query": True, "boost": 1}}},
        }
    },
    "sort": {"title.raw": "asc"},
}


def fetch(source: HealthcareSource, http_post=requests.post) -> list[Job]:
    url = f"https://pm.healthcaresource.com/JobseekerSearchAPI/{source.site_id}/api/Search?size=1000"
    resp = http_post(url, json=_SEARCH_BODY, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    jobs = []
    for hit in data.get("hits", {}).get("hits", []):
        src = hit["_source"]
        job_id = hit["_id"].split("_")[-1]
        hiring_org = src.get("hiringOrganization") or {}
        address = (src.get("jobLocation") or {}).get("address") or {}
        jobs.append(Job(
            key=f"healthcaresource:{hit['_id']}",
            title=src["title"],
            url=f"https://pm.healthcaresource.com/CS/{source.site_id}/#/job/{job_id}",
            company=hiring_org.get("name") or source.company,
            location=address.get("addressLocalityRegion"),
            posted_date=src.get("datePosted"),
            source_name=source.name,
        ))
    return jobs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/adapters/test_healthcaresource.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/adapters/healthcaresource.py tests/adapters/test_healthcaresource.py
git commit -m "feat: add HealthcareSource adapter"
```

---

### Task 3: Register the adapter

**Files:**
- Modify: `app/adapters/__init__.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `healthcaresource.fetch` (Task 2).
- Produces: `ADAPTERS["healthcaresource"]`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py` (near `test_infor_adapter_is_registered`):

```python
def test_healthcaresource_adapter_is_registered():
    from app.adapters import ADAPTERS
    assert "healthcaresource" in ADAPTERS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py::test_healthcaresource_adapter_is_registered -v`
Expected: FAIL — `AssertionError`.

- [ ] **Step 3: Register `healthcaresource` in `app/adapters/__init__.py`**

Change:

```python
from collections.abc import Callable

from app.adapters import generic_html, greenhouse, indeed, infor, lever, linkedin
from app.models import Job

ADAPTERS: dict[str, Callable[..., list[Job]]] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "generic_html": generic_html.fetch,
    "linkedin": linkedin.fetch,
    "indeed": indeed.fetch,
    "infor": infor.fetch,
}
```

to:

```python
from collections.abc import Callable

from app.adapters import generic_html, greenhouse, healthcaresource, indeed, infor, lever, linkedin
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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_orchestrator.py -v`
Expected: all pass, including the new test.

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/adapters/__init__.py tests/test_orchestrator.py
git commit -m "feat: register healthcaresource adapter"
```

---

### Task 4: Web UI wiring — source form

**Files:**
- Modify: `app/web/source_form.py`
- Modify: `app/web/templates/source_form.html`
- Test: `tests/web/test_source_form_helper.py`
- Test: `tests/web/test_source_form.py`

**Interfaces:**
- Consumes: `HealthcareSource` (Task 1).
- Produces: `/sources/new` and `/sources/{id}/edit` support `type=healthcaresource` end to end.

**Context:** Following the precedent set for `infor` (see `app/web/source_form.py`'s existing `infor_url` field), `healthcaresource` gets its own self-contained field block with a distinctly-named `site_id` input, rather than reusing the shared (and CSS-hidden-when-another-type-is-selected) `url` input that `generic_html`/`linkedin`/`indeed` rely on.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_source_form_helper.py` (after `test_infor_max_pages_defaults_when_field_blank`):

```python
def test_parses_healthcaresource_fields():
    form = {
        "type": "healthcaresource", "name": "Rush Copley (HealthcareSource)",
        "site_id": "rcmc", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.type == "healthcaresource"
    assert source.site_id == "rcmc"
```

Add to `tests/web/test_source_form.py` (after `test_post_new_infor_source_with_empty_url_shows_error_and_does_not_save`):

```python
def test_post_new_healthcaresource_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "healthcaresource", "name": "Rush Copley (HealthcareSource)",
        "site_id": "rcmc", "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["type"] == "healthcaresource"
    assert saved[0]["site_id"] == "rcmc"


def test_post_new_healthcaresource_source_with_empty_site_id_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "healthcaresource", "name": "Rush Copley (HealthcareSource)", "site_id": "",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    with open(client.app.state.sources_path) as f:
        assert json.load(f)["sources"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_source_form_helper.py tests/web/test_source_form.py -v -k healthcaresource`
Expected: FAIL — `KeyError: 'healthcaresource'`.

- [ ] **Step 3: Wire `HealthcareSource` into `app/web/source_form.py`**

Change:

```python
from app.config import (
    GenericHtmlSource,
    GreenhouseSource,
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

Then add a branch to `source_from_form`, changing:

```python
    elif source_type == "infor":
        if "infor_url" in form:
            common["url"] = _strip(form["infor_url"])
        if form.get("max_pages"):
            common["max_pages"] = int(form["max_pages"])
    else:
```

to:

```python
    elif source_type == "infor":
        if "infor_url" in form:
            common["url"] = _strip(form["infor_url"])
        if form.get("max_pages"):
            common["max_pages"] = int(form["max_pages"])
    elif source_type == "healthcaresource":
        if "site_id" in form:
            common["site_id"] = _strip(form["site_id"])
    else:
```

Then add `site_id` to `echo_source`'s returned `SimpleNamespace`, changing:

```python
        max_pages=form.get("max_pages", ""),
        include_keywords=_keywords(form.get("include_keywords", "")),
        exclude_keywords=_keywords(form.get("exclude_keywords", "")),
    )
```

to:

```python
        max_pages=form.get("max_pages", ""),
        site_id=form.get("site_id", ""),
        include_keywords=_keywords(form.get("include_keywords", "")),
        exclude_keywords=_keywords(form.get("exclude_keywords", "")),
    )
```

- [ ] **Step 4: Add the `healthcaresource` type option and fields to `app/web/templates/source_form.html`**

Change:

```html
      {% for t in ["greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor"] %}
```

to:

```html
      {% for t in ["greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor", "healthcaresource"] %}
```

Change:

```html
  <div id="fields-infor" class="type-fields">
    <label>URL <input type="text" name="infor_url" value="{{ source.url if source and source.type == 'infor' else '' }}"></label><br>
    <label>Max pages <input type="number" name="max_pages" value="{{ source.max_pages if source and source.type == 'infor' else 3 }}"></label>
  </div>
```

to:

```html
  <div id="fields-infor" class="type-fields">
    <label>URL <input type="text" name="infor_url" value="{{ source.url if source and source.type == 'infor' else '' }}"></label><br>
    <label>Max pages <input type="number" name="max_pages" value="{{ source.max_pages if source and source.type == 'infor' else 3 }}"></label>
  </div>
  <div id="fields-healthcaresource" class="type-fields">
    <label>Site ID <input type="text" name="site_id" value="{{ source.site_id if source and source.type == 'healthcaresource' else '' }}"></label>
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
git commit -m "feat: add healthcaresource source type to the web UI form"
```

---

### Task 5: Manual smoke test and documentation

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: a verified-working `healthcaresource` source type, documented for users and future maintainers.

**Note for whoever executes this task:** Step 1 hits a real, live third-party API (Rush Copley Medical Center's actual careers site). Keep it to one run — this is a one-time verification, not a load test.

- [ ] **Step 1: Manual smoke test against the real Rush Copley board**

In a scratch Python shell or a throwaway script, run:

```python
from app.adapters import healthcaresource
from app.config import HealthcareSource

source = HealthcareSource(
    name="Rush Copley (HealthcareSource) smoke test",
    type="healthcaresource",
    site_id="rcmc",
)
jobs = healthcaresource.fetch(source)
for j in jobs[:10]:
    print(j.title, "|", j.company, "|", j.location, "|", j.url)
print(f"\n{len(jobs)} jobs found")
```

Expected: around 117 jobs printed (the real count may have changed since this plan was written), each with a non-empty title and a `url` in the form `https://pm.healthcaresource.com/CS/rcmc/#/job/<id>`.

- [ ] **Step 2: Run the full suite one more time**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 3: Update `README.md`'s source type documentation**

In the "`sources.json`" section's field-reference table, change:

```markdown
| `infor` | `url` | For employers on Infor's Global HR / CandidateSelfService platform. `url` is the full listing page URL. `max_pages` (default 3) bounds how many pages of results are crawled per run — the board is sorted newest-first by default, so this captures the newest postings without a slow full-catalog crawl. There is no per-job link on this platform (confirmed via direct investigation): the digest links to the listing page itself, not the individual posting. |
```

to:

```markdown
| `infor` | `url` | For employers on Infor's Global HR / CandidateSelfService platform. `url` is the full listing page URL. `max_pages` (default 3) bounds how many pages of results are crawled per run — the board is sorted newest-first by default, so this captures the newest postings without a slow full-catalog crawl. There is no per-job link on this platform (confirmed via direct investigation): the digest links to the listing page itself, not the individual posting. |
| `healthcaresource` | `site_id` | For employers on the HealthcareSource/symplr talent platform (e.g. `pm.healthcaresource.com/CS/<site_id>`). Calls a directly-callable JSON API — no browser needed. Unlike `infor`, this platform has real per-job URLs and fetches every posting in one call (no pagination limit needed). |
```

- [ ] **Step 4: Add a CHANGELOG entry**

In `CHANGELOG.md`'s `[Unreleased]` → `### Added` section, add:

```markdown
- `healthcaresource` source type, for employers on the
  HealthcareSource/symplr talent platform (e.g. Rush Copley Medical
  Center). Calls a directly-callable JSON API (no browser needed) and
  fetches every posting in one call — real per-job URLs, unlike the
  `infor` source type.
```

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: document the healthcaresource source type"
```

---

## Self-Review Notes

- **Spec coverage:** every section of `docs/superpowers/specs/2026-08-13-healthcaresource-adapter-design.md` maps to a task — config schema (Task 1), API call + Job mapping (Task 2), `ADAPTERS` registration (Task 3), web UI wiring (Task 4), manual smoke test + docs (Task 5).
- **Placeholder scan:** none — every code block is complete, real content, including the exact request body and response shape captured from the live site.
- **Type consistency:** `HealthcareSource` (Task 1) is imported identically in `app/adapters/healthcaresource.py` (Task 2), `app/adapters/__init__.py` (Task 3), and `app/web/source_form.py` (Task 4). `healthcaresource.fetch`'s signature (`source: HealthcareSource, http_post=requests.post`) matches the calling convention every other adapter already uses (`orchestrator.py`, `routes_sources.py` call every adapter positionally with just `source`).
