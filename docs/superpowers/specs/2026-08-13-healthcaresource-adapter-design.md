# HealthcareSource Adapter — Design Spec

Date: 2026-08-13
Status: Approved for planning

## Purpose

Add `healthcaresource` as a seventh CareerSpyder source type, for
employers on the HealthcareSource/symplr talent platform (e.g. Rush
Copley Medical Center at `pm.healthcaresource.com/CS/rcmc`).

## Investigation summary

Direct investigation of a real HealthcareSource board (Rush Copley
Medical Center, `site_id=rcmc`) via a live browser session, intercepting
the page's own network calls, found this platform is a much closer fit
to Greenhouse/Lever than to Infor:

- **A real, directly-callable JSON API**, no authentication required:
  `POST https://pm.healthcaresource.com/JobseekerSearchAPI/{site_id}/api/Search?size=N`.
  It's a thin proxy over Elasticsearch — the request body is raw
  Elasticsearch query DSL (`bool`/`match_all`/`sort`), captured directly
  from the site's own XHR call:
  ```json
  {
    "query": {
      "bool": {
        "must": {"match_all": {}},
        "should": {"match": {"userArea.isFeaturedJob": {"query": true, "boost": 1}}}
      }
    },
    "sort": {"title.raw": "asc"}
  }
  ```
- **No pagination needed.** `size=200` against a board with 117 total
  postings returned all 117 in one response (`hits.total.value` matched
  `hits.hits.length`). One call gets everything, same as Greenhouse/Lever.
- **A real, stable per-job identifier and a real per-job URL.** Each hit's
  `_id` is `"{clientId}_{jobId}"` (e.g. `"4730_12040"`). Clicking a job
  in the real UI navigates to `https://pm.healthcaresource.com/CS/rcmc/#/job/12040`
  — confirmed by direct browser navigation, not inferred. No iframe, no
  JS grid, no "no link exists" workaround needed this time.
- **Rich, schema.org-shaped per-job data** in each hit's `_source`:
  `title`, `datePosted`, `hiringOrganization.name` (the specific
  facility — can differ per job under one job board, e.g. Rush Copley's
  board spans "Rush Copley Medical Center", "RUSH Copley Healthplex",
  and others as distinct facilities), `jobLocation.address.addressLocalityRegion`
  (a ready-made "City, ST" string), `userArea.requisitionNumber`
  (confirmed matches the "Req #" shown in the real UI — cross-checked
  `16289` in both places for the same posting).

Given all of that, this fits the existing `greenhouse.py`/`lever.py`
adapter shape almost exactly: one HTTP call, parse JSON, build `Job`
objects. No Playwright, no injectable browser renderer, no pagination
loop.

## Config schema

```python
class HealthcareSource(BaseSource):
    type: Literal["healthcaresource"]
    site_id: str = Field(min_length=1)
```

`site_id` is the URL path segment identifying the employer's specific
career site instance (`rcmc` for Rush Copley) — the same role
`board_token` plays for `GreenhouseSource`/`LeverSource`. It's used to
build both the API URL and the job detail URL.

## Job mapping

| `Job` field | Source |
|---|---|
| `key` | `f"healthcaresource:{hit['_id']}"` — the API's own stable id, same pattern as `greenhouse:{id}`/`lever:{id}` |
| `title` | `_source.title` |
| `url` | `f"https://pm.healthcaresource.com/CS/{source.site_id}/#/job/{job_id}"`, where `job_id` is the part of `_id` after the `_` |
| `company` | `_source.hiringOrganization.name` — taken per-job from the API response (more accurate than a fixed `source.company`, since one board can span multiple facility names), falling back to `source.company` if that path is ever missing |
| `location` | `_source.jobLocation.address.addressLocalityRegion` |
| `posted_date` | `_source.datePosted` |
| `source_name` | `source.name`, same as every other adapter |

## Adapter interface and testability

Matches the existing `greenhouse.py`/`lever.py` pattern exactly —
injectable HTTP call, fixture-based tests, no live network or browser in
tests:

```python
def fetch(source: HealthcareSource, http_post=requests.post) -> list[Job]:
```

`http_post` defaults to `requests.post`; tests inject a fake that
returns a canned Elasticsearch-shaped response (a `FakeResponse` with
`.raise_for_status()` and `.json()`, same as the existing Greenhouse/Lever
test fixtures). The request body is a fixed constant (not built from
`source` beyond the URL), so tests can assert on it directly the same
way `tests/adapters/test_greenhouse.py` asserts on the called URL.

## Testing / verification plan

- Fixture-based unit tests: maps a canned multi-hit response to `Job`
  objects correctly (title, url construction from `_id`, company from
  `hiringOrganization.name`, location, posted date, key); a hit missing
  `hiringOrganization` falls back to `source.company`; the exact URL and
  request body sent are asserted, matching existing adapter test
  conventions.
- Unit tests for the config model (`HealthcareSource` field validation)
  and the web-layer wiring (form round-trip), matching every other
  source type's existing test shape.
- Manual smoke test against the real Rush Copley board before considering
  this done, confirming the real HTTP call still returns real data (this
  one **can** be part of the automated-adjacent verification, unlike
  Infor's Playwright path, since it's a plain `requests`-based call with
  no browser timing to tune — but it's still a live third-party call, so
  keep it to one run, not part of the regular test suite).

## Explicitly out of scope for this iteration

- **A `max_jobs`/pagination cap.** Unlike Infor, fetching everything in
  one call is cheap here (one small JSON request, not N Playwright page
  loads) — no reason to bound it the way `InforSource.max_pages` does.
- **Keyword/category filtering via the API's own query DSL** (the
  request body could filter server-side instead of relying on the
  existing project-wide `include_keywords`/`exclude_keywords`
  post-filtering). Not needed — the existing filtering already works
  identically for every adapter and keeping this adapter's request body
  constant/simple is preferable to special-casing it.
