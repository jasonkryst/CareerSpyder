# Workday Adapter — Design Spec

Date: 2026-08-13
Status: Approved for planning

## Purpose

Add `workday` as a ninth CareerSpyder source type, for employers on
Workday's recruiting platform (e.g. Duly Health and Care at
`dulyhealthandcare.wd1.myworkdayjobs.com/Duly`). Workday is one of the
largest and most widely-used ATS platforms, and every Workday-hosted
career site exposes an identical API shape — this is the single most
broadly reusable adapter investigated so far.

## Investigation summary

Direct investigation of a real Workday career site (Duly Health and
Care), cross-checked with plain cookie-free `curl` calls:

- **A real, directly-callable JSON API, no authentication required**:
  `POST https://{tenant}.{wd-host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs`
  — Workday's public "CXS" (Candidate Experience Search) API, confirmed
  by hooking the site's own network calls, then replaying the exact call
  directly with `curl`. Body: `{"appliedFacets": {}, "limit": N,
  "offset": N, "searchText": ""}`.
- **Both the `tenant` and `site` path segments are derivable from the
  career site URL itself** — no separate identifiers to ask for.
  `https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly` breaks down as:
  `tenant` = the first label of the hostname (`dulyhealthandcare`),
  `site` = the last path segment (`Duly`), and the API is called against
  the same origin the career site itself is served from. A single
  `career_site_url` config field is enough.
- **Clean, structured response**: `{"total": N, "jobPostings": [...]}`,
  each posting with `title`, `externalPath` (a relative URL to the job
  detail page), `locationsText`, `postedOn` (a relative string like
  "Posted Today" or "Posted 30+ Days Ago" — not a parseable date),
  and `bulletFields` (a 2-element array, `[workerSubType, requisitionID]`
  — e.g. `["Regular", "JR117797"]`, verified across many postings).
- **`total` is only trustworthy on the very first request (`offset: 0`)
  — this is a real, verified quirk, not an assumption.** Confirmed
  directly: a follow-up request at `offset: 5` (mid-range) reported
  `"total":0` despite still returning 5 real, distinct job postings with
  zero overlap with the first page. The same happened at `offset: 100`.
  An adapter that trusts `total` from every response would stop after
  one page.
- **Requesting an offset past the real end doesn't return an empty
  list — it silently wraps back to page 1.** Confirmed directly: at
  `offset: 500` (341 total postings, well past the end), the API
  returned the *exact same* first 20 postings as `offset: 0`, with
  `total` correctly reported as 341 that one time. An adapter that
  loops "until an empty page" would loop forever, re-fetching page 1
  duplicated indefinitely — this can never be used as the stop
  condition, unlike every other adapter built so far.

Given both quirks together, the only safe design is: **capture `total`
from the first (`offset: 0`) response, freeze it, and use that frozen
value alone to compute exactly how many pages to fetch** — never trust
a later response's `total`, and never rely on an empty-results signal to
stop.

## Config schema

```python
class WorkdaySource(BaseSource):
    type: Literal["workday"]
    career_site_url: str = Field(min_length=1)
    max_pages: int = 60
```

`career_site_url` is the full career site URL as given (e.g.
`https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly`) — the adapter
derives both the API URL and the tenant/site identifiers from it.
`max_pages` is a safety cap (default 60, i.e. up to 1200 postings at the
platform's default page size of 20) — defense in depth against the
frozen `total` ever being implausibly large, not the primary stop
condition (the primary one is the frozen `total` itself, per above).

## Job mapping

| `Job` field | Source |
|---|---|
| `key` | `f"workday:{requisition_id}"`, where `requisition_id` is `bulletFields[1]` (falls back to `externalPath` if `bulletFields` doesn't have a second element, so a job is never silently dropped over a missing requisition ID) |
| `title` | `title` |
| `url` | `f"{origin}{externalPath}"`, where `origin` is derived from `career_site_url` |
| `company` | `source.company` (config field — not present in posting data) |
| `location` | `locationsText` |
| `posted_date` | `postedOn` as-is (a relative string like "Posted Today", not a parsed date — matches the project's existing looseness on this field, e.g. `linkedin`/`indeed` leave it `None` entirely; here at least a human-readable string is available) |
| `source_name` | `source.name`, same as every other adapter |

## Adapter interface and testability

Matches the existing HTTP-based adapters' pattern — injectable HTTP
call, fixture-based tests, no live network or browser in tests:

```python
def fetch(source: WorkdaySource, http_post=requests.post) -> list[Job]:
```

- URL/tenant/site derivation is a small pure helper, unit tested
  directly against a handful of realistic career site URLs.
- The pagination loop is tested with a fake `http_post` returning
  canned pages, specifically covering the two verified quirks above:
  a fake that returns `total: 0` on every page after the first (must
  still fetch the correct total number of pages, proving the adapter
  doesn't trust per-page `total`), and a fake that would return
  duplicate/wrapped content if the loop ran even one page too many
  (proving the loop stops exactly at the frozen total and never
  over-fetches into the wrap-around).

## Testing / verification plan

- Fixture-based unit tests for page parsing: multiple postings, a
  posting whose `bulletFields` is missing the requisition ID (falls
  back to `externalPath` for the key).
- Unit tests for URL/tenant/site derivation against realistic URLs.
- Unit tests for the pagination loop covering both verified API quirks
  (see above) plus the `max_pages` cap.
- Unit tests for the config model and web-layer wiring, matching every
  other source type's existing test shape.
- Manual smoke test against the real Duly Health and Care site before
  considering this done: confirm the fetched count is close to the
  platform-reported total, confirm zero duplicate keys, confirm at
  least one job's URL resolves.

## Explicitly out of scope for this iteration

- **Parsing `postedOn` into a real date.** It's a relative string
  ("Posted Today", "Posted 30+ Days Ago"), not a timestamp — not worth
  the fragility of parsing "30+" as a sentinel versus a real number for
  a field the digest already treats as opaque text.
- **The platform's own keyword/facet search.** Like every other
  adapter, CareerSpyder's own `include_keywords`/`exclude_keywords`
  post-filtering covers this; the adapter always searches with
  `searchText: ""` and an empty `appliedFacets`.
- **Verifying this works against a second Workday tenant.** The API
  shape is Workday's own public, platform-wide contract (not a
  per-tenant customization the way TalentBrew's module names were), so
  this is expected to generalize — but it's only been directly verified
  against one real tenant (Duly Health and Care).
