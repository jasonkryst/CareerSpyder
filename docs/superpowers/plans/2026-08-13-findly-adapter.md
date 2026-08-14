# Findly Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `findly` as an eleventh CareerSpyder source type so employers
on the Findly/Radancy career-site platform (e.g. Advocate Health at
`careers.aah.org`) can be scraped reliably.

**Architecture:** A new `FindlySource` config model plus a new
`app/adapters/findly.py` that calls the platform's own shared,
cross-tenant, unauthenticated JSON search API
(`GET https://jobsapi-internal.m-cloud.io/api/job`), paginating with a
fixed page size of 500 via an `offset`/`Limit` query-param loop, capped
by `max_pages` — the same paginate-until-a-short-page shape as
`talentbrew`/`workday`, not the single-oversized-call shape of
`phenompeople`/`healthcaresource`, because this platform's `Limit` is
capped at 500 (verified: `Limit=510`+ silently returns zero results).
Each returned record already carries an absolute, ready-to-use
`url` field, so the adapter does not reconstruct the platform's SEO-slug
algorithm.

**Tech Stack:** Same as the rest of the project — Python 3.12, Pydantic
v2, `requests`, pytest.

## Global Constraints

- Tests must not make live network calls (existing project-wide
  constraint) — `findly.fetch()` takes an injectable `http_get`, same
  pattern as `workday.py`/`talentbrew.py`.
- The search endpoint is `GET https://jobsapi-internal.m-cloud.io/api/job`
  with query params `Organization` (the tenant ID, `source.org_id`),
  `Limit` (fixed at `500`, a module constant — verified as the largest
  value that returns real results), `offset` (1-indexed start row,
  `page * 500 + 1`), and `sortfield=open_date`/`sortorder=descending`.
  Verified directly with `curl` against the real AAH tenant
  (`Organization=2297`): no cookies, no `Origin`/`Referer` header, no
  special User-Agent needed. **The sort params are not optional**: a
  live smoke test without them produced 210 duplicate job keys (~8% of
  2,733 total) because the API's default ordering shifts between
  paginated requests; adding the explicit sort (the same default the
  platform's own JS widget applies) eliminated all duplicates on
  re-run.
- Stop paginating as soon as a page returns fewer than 500 records (covers
  both the true-last-page case and an empty page) — do **not** rely on
  the response's `totalHits` to decide when to stop; it's redundant here
  (verified consistent across pages, unlike `workday`'s API) but the
  short-page check is simpler and matches `talentbrew`/`infor`'s existing
  stop condition.
- Each record's own `url` field is already an absolute, resolvable
  job-detail URL (verified live) — use it directly, never reconstruct
  `CWS.seo_url`'s slug algorithm.
- `company` comes from the record's own `company_name` field, falling
  back to `source.company` only when that field is blank — this platform
  *does* carry a company name per record, unlike `infor`/`talentbrew`/
  `phenompeople`.
- `location` is the record's `location_type` field when non-empty (e.g.
  `"Remote"`); otherwise built from whichever of `primary_city`/
  `primary_state` are present, joined with `", "`; `None` if neither is
  present.
- `posted_date` is the record's raw `open_date` string, unparsed (same
  tradeoff as every other adapter).
- `career_site_url` is captured on the config model for documentation
  only — the adapter itself never reads it (job URLs come pre-built from
  the API). Per user request: capture more context on the saved source,
  not less.
- Design spec: `docs/superpowers/specs/2026-08-13-findly-adapter-design.md`.

---

### Task 1: `FindlySource` config model

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `BaseSource` (existing).
- Produces: `FindlySource` (pydantic model: `type: Literal["findly"]`,
  `org_id: str` non-empty, `career_site_url: str` non-empty, `max_pages:
  int = 20`), added to the `SourceConfig` discriminated union.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py` (after the `phenompeople` tests):

```python
def test_findly_rejects_empty_org_id():
    with pytest.raises(ValidationError):
        config.FindlySource(
            name="Advocate Health", type="findly", org_id="",
            career_site_url="https://careers.aah.org",
        )


def test_findly_rejects_empty_career_site_url():
    with pytest.raises(ValidationError):
        config.FindlySource(name="Advocate Health", type="findly", org_id="2297", career_site_url="")


def test_findly_max_pages_defaults_to_twenty():
    source = config.FindlySource(
        name="Advocate Health", type="findly", org_id="2297",
        career_site_url="https://careers.aah.org",
    )
    assert source.max_pages == 20
```

Also add a `findly` entry to `test_load_sources_parses_each_type`'s
fixture list and assertions (append `s11` after `s10`, add `"findly"` to
the expected `[s.type for s in sources]` list, and assert
`sources[10].org_id == "2297"`, `sources[10].career_site_url ==
"https://careers.aah.org"`, and `sources[10].max_pages == 10`):

```python
{
    "id": "s11", "name": "Advocate Health (Findly)", "type": "findly",
    "org_id": "2297", "career_site_url": "https://careers.aah.org", "max_pages": 10,
},
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: module 'app.config' has no attribute 'FindlySource'`.

- [ ] **Step 3: Add `FindlySource` to `app/config.py`**

Add after `PhenomPeopleSource`:

```python
class FindlySource(BaseSource):
    type: Literal["findly"]
    org_id: str = Field(min_length=1)
    career_site_url: str = Field(min_length=1)
    max_pages: int = 20
```

Add `FindlySource` to the `SourceConfig` union.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add FindlySource config model"
```

---

### Task 2: `findly` adapter

**Files:**
- Create: `app/adapters/findly.py`
- Create: `tests/adapters/test_findly.py`

**Interfaces:**
- Consumes: `Job` (existing), `FindlySource` (Task 1).
- Produces: `findly.fetch(source: FindlySource, http_get=requests.get)
  -> list[Job]` — registered in Task 3's `ADAPTERS` dict.

- [ ] **Step 1: Write the failing tests**

Create `tests/adapters/test_findly.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/adapters/test_findly.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.adapters.findly'`.

- [ ] **Step 3: Write `app/adapters/findly.py`**

```python
import requests

from app.config import FindlySource
from app.models import Job

_API_URL = "https://jobsapi-internal.m-cloud.io/api/job"
_PAGE_SIZE = 500


def _location(record: dict) -> str | None:
    location_type = record.get("location_type")
    if location_type:
        return location_type
    parts = [p for p in (record.get("primary_city"), record.get("primary_state")) if p]
    return ", ".join(parts) if parts else None


def fetch(source: FindlySource, http_get=requests.get) -> list[Job]:
    all_jobs: list[Job] = []
    for page in range(source.max_pages):
        offset = page * _PAGE_SIZE + 1
        resp = http_get(
            _API_URL,
            params={
                "Organization": source.org_id, "Limit": _PAGE_SIZE, "offset": offset,
                "sortfield": "open_date", "sortorder": "descending",
            },
            timeout=15,
        )
        resp.raise_for_status()
        records = resp.json().get("queryResult") or []

        for record in records:
            all_jobs.append(Job(
                key=f"findly:{record['id']}",
                title=record["title"],
                url=record["url"],
                company=record.get("company_name") or source.company,
                location=_location(record),
                posted_date=record.get("open_date"),
                source_name=source.name,
            ))

        if len(records) < _PAGE_SIZE:
            break

    return all_jobs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/adapters/test_findly.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/adapters/findly.py tests/adapters/test_findly.py
git commit -m "feat: add Findly adapter"
```

---

### Task 3: Register the adapter

**Files:**
- Modify: `app/adapters/__init__.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py`:

```python
def test_findly_adapter_is_registered():
    from app.adapters import ADAPTERS
    assert "findly" in ADAPTERS
```

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Register `findly` in `app/adapters/__init__.py`** — add
  `findly,` as the first entry in the `from app.adapters import (...)`
  block (the existing imports are alphabetized, and `findly` sorts
  before `generic_html`), and add `"findly": findly.fetch,` to the
  `ADAPTERS` dict.
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Run the full suite to confirm no regression** — `pytest -q`
- [ ] **Step 6: Commit**

```bash
git add app/adapters/__init__.py tests/test_orchestrator.py
git commit -m "feat: register findly adapter"
```

---

### Task 4: Web UI wiring — source form

**Files:**
- Modify: `app/web/source_form.py`
- Modify: `app/web/templates/source_form.html`
- Test: `tests/web/test_source_form_helper.py`
- Test: `tests/web/test_source_form.py`

**Context:** `career_site_url` is already used by `workday`, and
`phenompeople` already worked around the resulting name collision (every
`.type-fields` div stays present in the DOM, only CSS-hidden, so a real
browser submits *all* same-named inputs and Starlette's
`FormData.get()` returns the *last* one) by naming its HTML input
`phenompeople_career_site_url` instead. `findly` hits the exact same
collision, so follow the same precedent: the HTML input is named
`findly_career_site_url`, normalized back onto the model's
`career_site_url` field in both `source_from_form` and `echo_source`.
`org_id` is a new field name with no existing collision, so it keeps a
plain `org_id` HTML input name.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_source_form_helper.py` (after the `phenompeople`
tests):

```python
def test_parses_findly_fields():
    form = {
        "type": "findly", "name": "Advocate Health (Findly)",
        "org_id": "2297", "findly_career_site_url": "https://careers.aah.org",
        "max_pages": "10", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.type == "findly"
    assert source.org_id == "2297"
    assert source.career_site_url == "https://careers.aah.org"
    assert source.max_pages == 10


def test_findly_max_pages_falls_back_to_default_when_field_blank():
    form = {
        "type": "findly", "name": "Advocate Health (Findly)",
        "org_id": "2297", "findly_career_site_url": "https://careers.aah.org",
        "max_pages": "", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.max_pages == 20
```

Add to `tests/web/test_source_form.py` (after the `phenompeople` tests):

```python
def test_post_new_findly_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "findly", "name": "Advocate Health (Findly)",
        "org_id": "2297", "findly_career_site_url": "https://careers.aah.org",
        "max_pages": "10", "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["type"] == "findly"
    assert saved[0]["org_id"] == "2297"
    assert saved[0]["career_site_url"] == "https://careers.aah.org"
    assert saved[0]["max_pages"] == 10


def test_post_new_findly_source_with_empty_org_id_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "findly", "name": "Advocate Health (Findly)", "org_id": "",
        "findly_career_site_url": "https://careers.aah.org",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    with open(client.app.state.sources_path) as f:
        assert json.load(f)["sources"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Wire `FindlySource` into `app/web/source_form.py`**

Add `FindlySource` to the `from app.config import (...)` block (the
existing imports are alphabetized; `FindlySource` sorts before
`GenericHtmlSource`) and to `TYPE_MODELS`:

```python
"findly": FindlySource,
```

Add a branch in `source_from_form` (after the `phenompeople` branch):

```python
elif source_type == "findly":
    if "org_id" in form:
        common["org_id"] = _strip(form["org_id"])
    if "findly_career_site_url" in form:
        common["career_site_url"] = _strip(form["findly_career_site_url"])
    if form.get("max_pages"):
        common["max_pages"] = int(form["max_pages"])
```

Update `echo_source`: extend the `career_site_url` ternary to also check
`findly`, and add `org_id` to the returned `SimpleNamespace`:

```python
career_site_url = (
    form.get("phenompeople_career_site_url", "")
    if form.get("type") == "phenompeople"
    else form.get("findly_career_site_url", "")
    if form.get("type") == "findly"
    else form.get("career_site_url", "")
)
```

```python
org_id=form.get("org_id", ""),
```

- [ ] **Step 4: Add the `findly` type option and fields to
  `app/web/templates/source_form.html`**

Add `"findly"` to the type `<select>` list (after `"phenompeople"`):

```html
{% for t in ["greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor", "healthcaresource", "talentbrew", "workday", "phenompeople", "findly"] %}
```

Add a `fields-findly` div after `fields-phenompeople`:

```html
<div id="fields-findly" class="type-fields">
  <label>Org ID <input type="text" name="org_id" value="{{ source.org_id if source and source.type == 'findly' else '' }}"></label><br>
  <label>Career site URL <input type="text" name="findly_career_site_url" value="{{ source.career_site_url if source and source.type == 'findly' else '' }}"></label><br>
  <label>Max pages <input type="number" name="max_pages" value="{{ source.max_pages if source and source.type == 'findly' else 20 }}"></label>
</div>
```

- [ ] **Step 5: Run the tests to verify they pass**
- [ ] **Step 6: Run the full suite to confirm no regression** — `pytest -q`
- [ ] **Step 7: Commit**

```bash
git add app/web/source_form.py app/web/templates/source_form.html tests/web/test_source_form_helper.py tests/web/test_source_form.py
git commit -m "feat: add findly source type to the web UI form"
```

---

### Task 5: Manual smoke test and documentation

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Note for whoever executes this task:** Step 1 hits the real, live
Advocate Health career site. Run it once, not repeatedly.

- [ ] **Step 1: Manual smoke test against the real Advocate Health site**

```python
from app.adapters import findly
from app.config import FindlySource

source = FindlySource(
    name="Advocate Health (Findly) smoke test",
    type="findly",
    org_id="2297",
    career_site_url="https://careers.aah.org",
    max_pages=20,
)
jobs = findly.fetch(source)
print(f"{len(jobs)} jobs found")
keys = [j.key for j in jobs]
print(f"unique keys: {len(set(keys))} (should equal total)")
for j in jobs[:5]:
    print(j.title, "|", j.location, "|", j.url)
```

Expected: roughly 2,736 jobs (the real count may have shifted since this
plan was written), `unique keys == total jobs`, each printed job having
a real, resolvable `url`.

- [ ] **Step 2: Run the full suite one more time** — `pytest -q`

- [ ] **Step 3: Update `README.md`'s source type documentation** — add a
  `findly` row to the field-reference table after `phenompeople`:

```
| `findly` | `org_id`, `career_site_url` | For employers on the Findly/Radancy career-site platform (e.g. Advocate Health at `careers.aah.org`, WordPress sites running the "CWS" plugin). Calls the platform's shared, cross-tenant, unauthenticated JSON API (`jobsapi-internal.m-cloud.io/api/job`) — no cookies or site-specific auth needed, just the numeric `org_id` tenant identifier (found in the target site's `cws_opts` JS object). Paginates in fixed pages of 500 (the platform's own cap — larger `Limit` values silently return zero results) up to `max_pages` (default 20). Each record already carries an absolute, resolvable job-detail `url`, so no slug reconstruction is needed. `career_site_url` is captured for documentation only; the adapter doesn't read it. |
```

- [ ] **Step 4: Add a CHANGELOG entry** under `[Unreleased]` → `### Added`:

```
- `findly` source type, for employers on the Findly/Radancy career-site
  platform (e.g. Advocate Health). Calls the platform's shared,
  cross-tenant JSON API directly (no browser needed), paginating in
  fixed pages of 500 up to a configurable `max_pages`.
```

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: document the findly source type"
```

---

## Self-Review Notes

- **Spec coverage:** every section of
  `docs/superpowers/specs/2026-08-13-findly-adapter-design.md` maps to a
  task — config schema (Task 1), search API call + pagination + Job
  mapping (Task 2), `ADAPTERS` registration (Task 3), web UI wiring
  (Task 4), manual smoke test + docs (Task 5).
- **Type consistency:** `FindlySource` (Task 1) is imported identically
  in `app/adapters/findly.py` (Task 2), `app/adapters/__init__.py` (Task
  3), and `app/web/source_form.py` (Task 4). `findly.fetch`'s signature
  (`source: FindlySource, http_get=requests.get`) matches the calling
  convention `workday`/`talentbrew` already use for paginated GET-style
  adapters (note: `workday`/`healthcaresource`/`phenompeople` use
  `http_post` since their APIs are POST-based; `findly`'s is GET-based,
  matching `talentbrew`/`infor`'s `http_get` naming instead).
- **Pagination shape deliberately differs from `phenompeople`** — this
  is not an oversight: `phenompeople`'s platform accepts an oversized
  `size` in one call, but `findly`'s platform caps `Limit` at 500
  (verified: 510+ returns zero results), so a real offset loop is
  required, same shape as `workday`/`talentbrew`.
- **Deviation found during Task 5's live smoke test, folded back into
  Task 2:** the original plan's request params (`Organization`,
  `Limit`, `offset` only) produced 210 duplicate job keys (~8% of
  2,733) on the real AAH site — the API's default order isn't stable
  across paginated requests. Fixed by always sending
  `sortfield=open_date&sortorder=descending`; verified a clean re-run
  (2,733 jobs, 2,733 unique keys) before considering Task 2/5 done. Both
  this plan and the design spec were updated in place to reflect the
  params as actually shipped, rather than left describing the
  pre-fix behavior.
