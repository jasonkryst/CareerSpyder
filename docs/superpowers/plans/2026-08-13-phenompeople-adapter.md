# PhenomPeople Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `phenompeople` as a tenth CareerSpyder source type so employers
on Phenom People's career-site platform (e.g. Ascension Health at
`jobs.ascension.org`) can be scraped reliably.

**Architecture:** A new `PhenomPeopleSource` config model plus a new
`app/adapters/phenompeople.py` that calls the platform's own internal,
unauthenticated JSON search endpoint (`POST {career_site_url}/widgets`
with `ddoKey: "refineSearch"`) once per run with a generously large
`size`, so every matching job comes back in a single call — no
pagination loop needed (verified: `size=2000` cleanly returned all 198
jobs for a live 198-job facet with zero duplicates). An optional `state`
config field maps to the platform's own "State" facet
(`selected_fields: {"state": [...]}`) so results can be scoped to a
specific state rather than relying on the site's IP-geolocation-based
default sort (verified misleading: the unfiltered listing is
personalized to the requester's own location, not a stable nationwide
list).

**Tech Stack:** Same as the rest of the project — Python 3.12, Pydantic
v2, `requests`, pytest.

## Global Constraints

- Tests must not make live network calls (existing project-wide
  constraint) — `phenompeople.fetch()` takes an injectable `http_post`,
  same pattern as `healthcaresource.py`.
- The search endpoint is `POST {career_site_url}/widgets`. Verified
  directly (cookie-free, no CSRF token, no `refNum` field needed — the
  tenant is resolved from the `Host` header) against the real Ascension
  site.
- One request per run, with a fixed oversized `size` (`2000`, a module
  constant) — not configurable, not paginated. This matches
  `healthcaresource.py`'s precedent more than the paginating adapters.
- `selected_fields` is `{"state": [source.state]}` when `source.state`
  is set, else `{}` (no filter).
- There is no per-job company field in the API response — `company`
  always comes from `source.company`, same as `infor`/`talentbrew`.
- Job-detail URLs are `{career_site_url}/us/en/job/{job_id}` — verified
  the platform ignores any title-slug suffix entirely (a request with no
  slug and a request with a deliberately wrong slug both `200` and
  render the same real job page), so the adapter never generates one.
- Design spec: `docs/superpowers/specs/2026-08-13-phenompeople-adapter-design.md`.

---

### Task 1: `PhenomPeopleSource` config model

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `BaseSource` (existing).
- Produces: `PhenomPeopleSource` (pydantic model: `type:
  Literal["phenompeople"]`, `career_site_url: str` non-empty, `state:
  str | None = None`), added to the `SourceConfig` discriminated union.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py` (after the `workday` tests):

```python
def test_phenompeople_rejects_empty_career_site_url():
    with pytest.raises(ValidationError):
        config.PhenomPeopleSource(name="Ascension", type="phenompeople", career_site_url="")


def test_phenompeople_state_defaults_to_none():
    source = config.PhenomPeopleSource(
        name="Ascension", type="phenompeople", career_site_url="https://jobs.ascension.org",
    )
    assert source.state is None
```

Also add a `phenompeople` entry to `test_load_sources_parses_each_type`'s
fixture list and assertion (append `s10` after `s9`, add `"phenompeople"`
to the expected `[s.type for s in sources]` list, and assert
`sources[9].career_site_url == "https://jobs.ascension.org"` and
`sources[9].state == "Illinois"`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: module 'app.config' has no attribute 'PhenomPeopleSource'`.

- [ ] **Step 3: Add `PhenomPeopleSource` to `app/config.py`**

Add after `WorkdaySource`:

```python
class PhenomPeopleSource(BaseSource):
    type: Literal["phenompeople"]
    career_site_url: str = Field(min_length=1)
    state: str | None = None
```

Add `PhenomPeopleSource` to the `SourceConfig` union.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add PhenomPeopleSource config model"
```

---

### Task 2: `phenompeople` adapter

**Files:**
- Create: `app/adapters/phenompeople.py`
- Create: `tests/adapters/test_phenompeople.py`

**Interfaces:**
- Consumes: `Job` (existing), `PhenomPeopleSource` (Task 1).
- Produces: `phenompeople.fetch(source: PhenomPeopleSource,
  http_post=requests.post) -> list[Job]` — registered in Task 3's
  `ADAPTERS` dict.

- [ ] **Step 1: Write the failing tests** in
  `tests/adapters/test_phenompeople.py`, covering: mapping a hit to a
  `Job`, the request URL/body shape (with and without `state`), missing
  `location`/`postedDate` handled as `None`, empty `jobs` list handled,
  multiple hits mapped in order.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/adapters/test_phenompeople.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.adapters.phenompeople'`.

- [ ] **Step 3: Write `app/adapters/phenompeople.py`**

```python
import requests

from app.config import PhenomPeopleSource
from app.models import Job

_SIZE = 2000


def fetch(source: PhenomPeopleSource, http_post=requests.post) -> list[Job]:
    selected_fields = {"state": [source.state]} if source.state else {}
    resp = http_post(
        f"{source.career_site_url}/widgets",
        json={
            "ddoKey": "refineSearch",
            "from": 0,
            "size": _SIZE,
            "jobs": True,
            "counts": True,
            "selected_fields": selected_fields,
        },
        timeout=15,
    )
    resp.raise_for_status()
    hits = resp.json().get("refineSearch", {}).get("data", {}).get("jobs", [])

    jobs = []
    for hit in hits:
        job_id = hit["jobId"]
        jobs.append(Job(
            key=f"phenompeople:{job_id}",
            title=hit["title"],
            url=f"{source.career_site_url}/us/en/job/{job_id}",
            company=source.company,
            location=hit.get("location"),
            posted_date=hit.get("postedDate"),
            source_name=source.name,
        ))
    return jobs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/adapters/test_phenompeople.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/adapters/phenompeople.py tests/adapters/test_phenompeople.py
git commit -m "feat: add PhenomPeople adapter"
```

---

### Task 3: Register the adapter

**Files:**
- Modify: `app/adapters/__init__.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py`:

```python
def test_phenompeople_adapter_is_registered():
    from app.adapters import ADAPTERS
    assert "phenompeople" in ADAPTERS
```

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Register `phenompeople` in `app/adapters/__init__.py`** (import + `ADAPTERS` entry)
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Run the full suite to confirm no regression** — `pytest -q`
- [ ] **Step 6: Commit**

```bash
git add app/adapters/__init__.py tests/test_orchestrator.py
git commit -m "feat: register phenompeople adapter"
```

---

### Task 4: Web UI wiring — source form

**Files:**
- Modify: `app/web/source_form.py`
- Modify: `app/web/templates/source_form.html`
- Test: `tests/web/test_source_form_helper.py`
- Test: `tests/web/test_source_form.py`

**Context:** `career_site_url` is already used by `workday`. **Deviation
from the plan's original assumption:** reusing that same HTML input name
for `phenompeople` would be a real bug, not just a naming nicety — every
`.type-fields` div stays present in the DOM (only CSS-hidden), so a
real browser submits *all* same-named inputs, and Starlette's
`FormData.get()` returns the *last* one. Since `phenompeople`'s div
renders after `workday`'s, a plain `career_site_url` name would silently
clobber `workday` submissions with `phenompeople`'s (usually blank)
value — confirmed directly (`FormData([("x","first"),("x","second")]).get("x")
== "second"`). Followed the `infor_url` precedent instead: the HTML
input is named `phenompeople_career_site_url`, normalized back onto the
model's `career_site_url` field in both `source_from_form` and
`echo_source` (mirroring exactly how `infor_url` is normalized onto
`.url`). Verified end-to-end in a real browser: submitting a real
`workday` source after this change still saves its own
`career_site_url` untouched.

- [ ] **Step 1: Write the failing tests** — `test_parses_phenompeople_fields`
  (with and without `state`) in `test_source_form_helper.py`;
  `test_post_new_phenompeople_source_saves_and_redirects` and
  `test_post_new_phenompeople_source_with_empty_career_site_url_shows_error_and_does_not_save`
  in `test_source_form.py`.

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Wire `PhenomPeopleSource` into `app/web/source_form.py`**
  — add to `TYPE_MODELS`, add a `source_type == "phenompeople"` branch in
  `source_from_form` that sets `career_site_url` and `state` (state
  optional — only set if the form field is non-blank, else leave unset
  so the model default `None` applies), add `state` to `echo_source`'s
  `SimpleNamespace`.

- [ ] **Step 4: Add the `phenompeople` type option and fields to
  `app/web/templates/source_form.html`** — add to the type `<select>`
  list, add a `fields-phenompeople` div with `career_site_url` and
  `state` inputs.

- [ ] **Step 5: Run the tests to verify they pass**
- [ ] **Step 6: Run the full suite to confirm no regression** — `pytest -q`
- [ ] **Step 7: Commit**

```bash
git add app/web/source_form.py app/web/templates/source_form.html tests/web/test_source_form_helper.py tests/web/test_source_form.py
git commit -m "feat: add phenompeople source type to the web UI form"
```

---

### Task 5: Manual smoke test and documentation

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Note for whoever executes this task:** Step 1 hits the real, live
Ascension career site. Run it once, not repeatedly.

- [ ] **Step 1: Manual smoke test against the real Ascension site**

```python
from app.adapters import phenompeople
from app.config import PhenomPeopleSource

source = PhenomPeopleSource(
    name="Ascension (Illinois) smoke test",
    type="phenompeople",
    career_site_url="https://jobs.ascension.org",
    state="Illinois",
)
jobs = phenompeople.fetch(source)
print(f"{len(jobs)} jobs found")
keys = [j.key for j in jobs]
print(f"unique keys: {len(set(keys))} (should equal total)")
for j in jobs[:5]:
    print(j.title, "|", j.location, "|", j.url)
```

Expected: roughly 198 jobs (the real count may have shifted since this
plan was written), `unique keys == total jobs`, each printed job having
a real, resolvable `url`.

- [ ] **Step 2: Run the full suite one more time** — `pytest -q`

- [ ] **Step 3: Update `README.md`'s source type documentation** — add a
  `phenompeople` row to the field-reference table after `workday`.

- [ ] **Step 4: Add a CHANGELOG entry** under `[Unreleased]` → `### Added`.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: document the phenompeople source type"
```

---

## Self-Review Notes

- **Spec coverage:** every section of
  `docs/superpowers/specs/2026-08-13-phenompeople-adapter-design.md`
  maps to a task — config schema (Task 1), search API call + Job
  mapping (Task 2), `ADAPTERS` registration (Task 3), web UI wiring
  (Task 4), manual smoke test + docs (Task 5).
- **Type consistency:** `PhenomPeopleSource` (Task 1) is imported
  identically in `app/adapters/phenompeople.py` (Task 2),
  `app/adapters/__init__.py` (Task 3), and `app/web/source_form.py`
  (Task 4). `phenompeople.fetch`'s signature (`source:
  PhenomPeopleSource, http_post=requests.post`) matches the calling
  convention every other HTTP-based adapter already uses.
- **No pagination loop, unlike `talentbrew`/`workday`/`infor`** — this
  is deliberate, not an oversight: verified directly that one
  oversized-`size` call returns every job. Keeping this as a single call
  (rather than adding an unused `max_pages` field) avoids config surface
  the platform doesn't need.
