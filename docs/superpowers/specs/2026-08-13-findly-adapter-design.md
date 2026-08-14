# Findly Adapter — Design Spec

Date: 2026-08-13
Status: Approved for planning

## Purpose

Add `findly` as an eleventh CareerSpyder source type, for employers on
the Findly/Radancy career-site platform (e.g. Advocate Health at
`careers.aah.org`, requested via
`https://careers.aah.org/job-search-results/`).

## Investigation summary

Direct investigation of the real Advocate Health career site
(`careers.aah.org`), via the raw page HTML, its loaded JS bundles, and
plain cookie-free `curl` calls against the discovered API, found:

- **The site is WordPress running the "CWS" plugin**
  (`wp-content/plugins/cws/js/cws.jobs.js`), which is Findly/Radancy's
  career-site widget — confirmed by `cdn-static.findly.com`,
  `*.site.findly.com` asset URLs, and `findly-connect-lightbox` CSS
  classes baked into the plugin JS. This is a shared, cross-tenant
  platform (like `healthcaresource`), not an AAH-specific integration,
  so the adapter should generalize to other hospital systems on the
  same platform.
- **There is a real, directly-callable, unauthenticated JSON API** for
  job search — `GET https://jobsapi-internal.m-cloud.io/api/job` with
  query params `Organization` (tenant ID), `Limit` (page size), and
  `offset` (1-indexed start row). Verified with plain `curl`: no
  cookies, no CSRF token, no `Origin`/`Referer` header needed, works
  with a bare `requests`-style default User-Agent.
- **The tenant ID (`Organization`) is not derivable from the career
  site's own URL** — it's a numeric ID (`2297` for AAH) embedded in an
  inline `cws_opts` JS object on the page (`wp-content/cache/minify/...`
  bundles), the same shape of problem `healthcaresource`'s `site_id`
  solves. The adapter config therefore needs an explicit `org_id` field
  a user must look up from the target site's page source, documented in
  the plan.
- **`Limit` is capped somewhere at or below 500** — verified by binary
  search: `Limit=500` returns 500 results, `Limit=510` and above
  silently returns zero results (not an error, just an empty
  `queryResult`). The adapter uses a fixed page size of 500.
- **`offset` pagination has zero overlap between pages** and
  **`totalHits` stays consistent across every page** (unlike the
  `workday` adapter, which has a documented quirk where `total` is only
  trustworthy on the first response) — verified directly: page 1
  (`offset=1`, 500 results) and page 2 (`offset=501`, 500 results) share
  zero job IDs; `totalHits` read `2736` identically from both an early
  and a late page. The adapter can safely stop on a short/empty page
  rather than needing to snapshot `totalHits` up front.
- **Each job record already includes a ready-to-use absolute detail-page
  URL** in its own `url` field (e.g.
  `https://careers.aah.org/job/23633616/public-safety-officer-1st-shift-st-lukes-med-center-milwaukee-wi/`)
  — verified this resolves with a live HTTP 200. The adapter uses this
  field directly rather than reconstructing the platform's own SEO-slug
  algorithm (`CWS.seo_url` in `cws.js`, which lowercases the title +
  city/state and hyphenates it — reproducible, but unnecessary busywork
  given the API hands back the real URL).
- **Without an explicit sort, the API's default result ordering is
  unstable across paginated requests.** Discovered via a live manual
  smoke test (post-implementation): fetching all ~2,733 AAH jobs with no
  `sortfield`/`sortorder` params produced 210 duplicate job keys (~8%)
  — the same job landing on two different pages because the underlying
  order shifted between requests. Adding `sortfield=open_date&
  sortorder=descending` (the same default the platform's own JS widget
  applies client-side, per `cws.jobs.js`'s `default_sortfield`/
  `default_sortorder`) eliminated all duplicates on a live re-run (2,733
  jobs, 2,733 unique keys). This is the same class of problem
  `talentbrew` hit with its default "Relevancy" sort — the adapter must
  always pass an explicit, deterministic sort.
- **Per-job JSON fields** (from a real hit): `id` (numeric), `title`,
  `url` (absolute, see above), `company_name` (e.g. `"Advocate Aurora
  Health"` — present on the record itself, unlike `phenompeople`/
  `infor`/`talentbrew`), `primary_city`, `primary_state`,
  `location_type` (empty string for a normal in-person posting; else a
  label like `"Remote"`/`"Nationwide"`/`"Statewide"`/`"Onsite"`),
  `open_date` (ISO-8601 string), plus many ATS-internal fields not
  needed here (`scout_orgid`, `ats_portalid`, `custom_fields`, etc).

## Config schema

```python
class FindlySource(BaseSource):
    type: Literal["findly"]
    org_id: str = Field(min_length=1)
    career_site_url: str = Field(min_length=1)
    max_pages: int = 20
```

`org_id` is the platform tenant ID (e.g. `"2297"`) and is the only field
the adapter actually needs to call the API — the search endpoint lives
on a domain shared across every Findly tenant, not on the employer's own
site. `career_site_url` (e.g. `https://careers.aah.org`) is **not**
used by the adapter (job URLs come pre-built from the API response) but
is captured purely so the saved source is self-documenting — per user
request, favoring more recorded context over a minimal schema, matching
how `workday`/`phenompeople` already store a full site URL rather than
just a bare tenant slug. `max_pages` caps pagination at 20 pages of 500
(10,000 jobs), comfortably above AAH's current ~2,736.

## Job mapping

| `Job` field | Source |
|---|---|
| `key` | `f"findly:{job['id']}"` |
| `title` | the record's `title` field |
| `url` | the record's own `url` field (already absolute) |
| `company` | the record's `company_name`, falling back to `source.company` if blank |
| `location` | `location_type` if non-empty (e.g. `"Remote"`); else `"{primary_city}, {primary_state}"` built from whichever of the two are present; `None` if neither |
| `posted_date` | the record's `open_date` field (raw ISO-8601 string, unparsed) |
| `source_name` | `source.name`, same as every other adapter |

## Adapter interface and testability

Matches the existing HTTP-based adapters' pattern — injectable HTTP
call, fixture-based tests, no live network in tests:

```python
def fetch(source: FindlySource, http_get=requests.get) -> list[Job]:
```

- Page size (`500`) lives as a module constant, matching
  `phenompeople.py`'s `_SIZE` precedent.
- Loop: `offset = page * 500 + 1` for `page` in `range(max_pages)`;
  stop as soon as a page returns fewer than 500 results (covers both
  the true-last-page case and an empty page), same stop condition
  `talentbrew`/`infor` already use.
- Fixture-based tests exercise: mapping a record to a `Job` (including
  the `location_type` vs. city/state branching, and the `company_name`
  fallback to `source.company`), pagination stopping on a short page,
  pagination stopping at `max_pages`, and request URL/params
  (`Organization`, `Limit`, `offset`) built correctly per page.

## Testing / verification plan

- Fixture-based unit tests for pagination (short page ends loop,
  `max_pages` caps it, offsets computed correctly) and job mapping
  (location branching, company fallback, missing `open_date`).
- Unit tests for the config model (rejects empty `org_id`/
  `career_site_url`, `max_pages` defaults to `20`) and web-layer wiring,
  matching every other source type's existing test shape.
- Manual smoke test against the real AAH site before considering this
  done: confirm the fetched job count roughly matches `totalHits`
  (~2,736), confirm zero duplicate keys, confirm at least one job's URL
  resolves to a real posting.

## Explicitly out of scope for this iteration

- **Verifying this works against a different Findly-powered employer.**
  The request shape (org-ID-only, no site-specific auth) is expected to
  generalize since the API domain and param names are platform-wide,
  not AAH-specific, but this has only been confirmed against AAH's
  deployment.
- **Any facet/filter other than the default (unfiltered, all open
  jobs).** The real widget supports keyword/location/category facets;
  `include_keywords`/`exclude_keywords` post-filtering covers narrowing
  for now, same tradeoff as every other adapter.
- **Posted-date parsing/normalization.** Stored as the raw ISO-8601
  string the API returns, same tradeoff already accepted by
  `healthcaresource`/`phenompeople`.
