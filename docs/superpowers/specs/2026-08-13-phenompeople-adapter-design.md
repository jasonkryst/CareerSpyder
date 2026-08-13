# PhenomPeople Adapter — Design Spec

Date: 2026-08-13
Status: Approved for planning

## Purpose

Add `phenompeople` as a tenth CareerSpyder source type, for employers on
Phenom People's career-site platform (e.g. Ascension Health at
`jobs.ascension.org`, requested via
`https://jobs.ascension.org/us/en/illinois`).

## Investigation summary

Direct investigation of the real Ascension career site
(`jobs.ascension.org`), via a live browser session with network-request
hooking, cross-checked with plain cookie-free `requests`/`urllib` calls,
found:

- **The site is a Phenom People "CareerConnect" deployment** — confirmed
  by `cdn.phenompeople.com` asset URLs and the page's own widget
  bootstrapping calls, all POSTed to a same-origin `/widgets` endpoint.
- **The requested URL (`/us/en/illinois`) is a marketing landing page**,
  not a job search results page — it shows hospital/facility cards, not
  a job list. The real job search lives at `/us/en/search-results`, with
  results narrowed to a specific state via a "State" facet in the page's
  sidebar (verified: Illinois shows "198 Jobs" as a facet count on the
  live site).
- **The default (unfiltered) search-results page is geo-personalized to
  the visitor's own IP location**, sorted "Most relevant" — from an
  Illinois-based investigation session, the *unfiltered* listing
  happened to return only Illinois jobs near the visitor, which would be
  actively misleading to rely on: a production scraper's outbound IP
  won't reliably be in Illinois. The adapter must apply the real `state`
  facet filter explicitly rather than depend on geo-personalization.
- **There is a real, directly-callable, unauthenticated JSON API** for
  job search — `POST {career_site_url}/widgets` with a body shaped like:
  ```json
  {
    "ddoKey": "refineSearch",
    "from": 0,
    "size": 2000,
    "jobs": true,
    "counts": true,
    "selected_fields": {"state": ["Illinois"]}
  }
  ```
  Verified directly, with **no cookies, no CSRF token, and no `refNum`
  field** (the tenant is resolved server-side from the `Host` header,
  i.e. the domain in `career_site_url`) — a cookie-free `urllib`/
  `requests` call reproduces the exact same job list the browser
  fetched when checking the "Illinois" state-facet checkbox.
  Response shape: `{"refineSearch": {"status": 200, "hits": N,
  "totalHits": M, "data": {"jobs": [...]}}}`.
- **A single request with a generously large `size` returns every
  matching job at once — no pagination loop is needed.** Verified:
  `size=2000` against a 198-job Illinois facet returned all 198 in one
  response with zero duplicates; `size=2000` against the unfiltered
  (nationwide, 3366-job) search also returned cleanly. This matches the
  `healthcaresource` adapter's precedent (a single oversized `size` call
  rather than paginating) more closely than `talentbrew`/`workday`/
  `infor`'s paging loops.
- **Per-job JSON fields** (from a real Illinois hit): `jobId` (numeric
  string, e.g. `"457323"`), `title`, `location` (e.g. `"Bartlett,
  Illinois, 60103"`), `postedDate` (ISO-8601 string), plus many
  ML/facet-internal fields not needed here (`ml_skills`,
  `multi_category_array`, etc.). There is **no company/employer-name
  field** on the job record itself (only a free-text `address` block
  mixing facility name and street address) — same situation as
  `infor`/`talentbrew`, so `company` comes from the source config, not
  the API response.
- **No canonical job-detail-page URL or slug field is present in the
  API response.** The real site builds its own link as
  `/us/en/job/{jobId}/{Title-With-Dashes}`, but this was verified
  directly to be **cosmetic only**: `GET
  https://jobs.ascension.org/us/en/job/457323` (no slug at all) and
  `GET .../457323/totally-wrong-slug` both return `200` with the same
  real, fully-rendered job page (title text present in both response
  bodies). The adapter therefore builds URLs as
  `{career_site_url}/us/en/job/{jobId}` — no slug generation, no edge
  cases from special characters in titles.

## Config schema

```python
class PhenomPeopleSource(BaseSource):
    type: Literal["phenompeople"]
    career_site_url: str = Field(min_length=1)
    state: str | None = None
```

`career_site_url` is the site's origin (e.g.
`https://jobs.ascension.org`) — the adapter builds both the search API
URL and each job's detail-page URL from it. `state` is an optional
"State" facet value (e.g. `"Illinois"`) matching the platform's own
facet UI; when omitted, the search is unfiltered (nationwide/sitewide).
No `keywords` field: like every other adapter, CareerSpyder's own
`include_keywords`/`exclude_keywords` post-filtering already covers
narrowing by title/description text.

No `max_pages`/pagination-cap field is needed — the adapter always
issues exactly one request with a fixed, generously large `size`
(module constant, matching `healthcaresource.py`'s `size=1000`
precedent — this adapter uses `2000`, verified to comfortably exceed
any observed facet count without erroring).

## Job mapping

| `Job` field | Source |
|---|---|
| `key` | `f"phenompeople:{job_id}"`, where `job_id` is the hit's `jobId` field |
| `title` | the hit's `title` field |
| `url` | `f"{source.career_site_url}/us/en/job/{job_id}"` |
| `company` | `source.company` (config field — not present in the API response) |
| `location` | the hit's `location` field |
| `posted_date` | the hit's `postedDate` field (raw ISO-8601 string, unparsed) |
| `source_name` | `source.name`, same as every other adapter |

## Adapter interface and testability

Matches the existing HTTP-based adapters' pattern — injectable HTTP
call, fixture-based tests, no live network in tests:

```python
def fetch(source: PhenomPeopleSource, http_post=requests.post) -> list[Job]:
```

- The request body's constant fields (`ddoKey`, `jobs`, `counts`,
  `from`, `size`) live in the function; only `selected_fields` varies
  with `source.state`.
- Fixture-based tests exercise: mapping a hit to a `Job`, building the
  `selected_fields` body correctly when `state` is set vs. omitted,
  building the request URL from `career_site_url`, and handling a hit
  missing `location`/`postedDate` gracefully (`None`).

## Testing / verification plan

- Fixture-based unit tests for the single-call fetch: job mapping,
  request-body shape (with and without `state`), empty-results handling.
- Unit tests for the config model (rejects empty `career_site_url`,
  `state` optional/defaults to `None`) and web-layer wiring, matching
  every other source type's existing test shape.
- Manual smoke test against the real Ascension site before considering
  this done: confirm the Illinois-filtered job count roughly matches the
  live facet count, confirm zero duplicate keys, confirm at least one
  job's URL resolves to a real posting.

## Explicitly out of scope for this iteration

- **Verifying this works against a different Phenom People-powered
  employer.** The request shape (no `refNum` needed, `Host`-based tenant
  resolution) is expected to generalize since it was verified to work
  with zero site-specific auth/identifiers beyond the origin URL, but
  this has only been confirmed against Ascension's deployment.
- **Any facet other than `state`** (city, category, job type, shift,
  commute type, brand are all available on the real site's sidebar but
  not wired into this adapter — `include_keywords`/`exclude_keywords`
  post-filtering covers narrowing beyond state for now).
- **Posted-date parsing/normalization.** Stored as the raw ISO-8601
  string the API returns, same tradeoff already accepted by
  `healthcaresource`.
