# TalentBrew Adapter — Design Spec

Date: 2026-08-13
Status: Approved for planning

## Purpose

Add `talentbrew` as an eighth CareerSpyder source type, for employers on
Radancy's TalentBrew career-site platform (e.g. Northwestern Medicine at
`jobs.nm.org`). TalentBrew is a large, widely-used platform, so this is
worth a proper adapter rather than a one-off `generic_html` config.

## Investigation summary

Direct investigation of a real TalentBrew site (Northwestern Medicine,
`jobs.nm.org`) via a live browser session, cross-checked with plain
cookie-free `curl`/`requests` calls, found:

- **The site is genuinely server-rendered** — a cookie-free `curl` with
  no JS returned the full job listing HTML, including every job's
  `data-job-id`, title, and location. Confirms `generic_html` with
  `render_js: false` *could* parse a single page.
- **But the visible `/search-jobs/{keyword}/{id}/{page}` URL is not a
  reliable pagination mechanism.** Two problems, verified directly:
  - The keyword segment doesn't actually filter results — a blank
    keyword and a "Radiation Therapist" keyword search returned the same
    kind of broad, mixed result set. The numeric segment in that URL
    (`27763` in the URL originally investigated) is not a search filter
    either — it's the employer's TalentBrew tenant ID, visible in an
    embedded JSON blob on the page (`"OrganizationID":27763,"TenantID":27763`)
    and present in every job's own URL regardless of what was searched.
  - Under the page's **default sort ("Relevancy")**, sequential pages are
    **not stable or non-overlapping**. A same-URL fetch repeated 3x
    back-to-back is identical (so a single page is stable), but walking
    `/search-jobs//1`, `/search-jobs//2`, ... sequentially produced real
    duplicate `data-job-id` values between adjacent pages, wildly
    inconsistent page sizes (25, 24, 6, 12, 16, 5, 18, ...), and only
    reached 432 unique jobs after 46 overlapping pages before the 47th
    came back empty — an unreliable and wasteful way to paginate.
- **There is a real, working, deterministic pagination path** — an
  internal AJAX endpoint the page's own "Next" button calls,
  `GET {base_url}/search-jobs/results`, discovered by hooking the
  browser's own network calls and confirmed by replaying it directly
  with `requests`:
  - Returns `{"filters": ..., "results": "<section ...>...</section>",
    "hasJobs": true, "hasContent": ...}` — an HTML fragment **wrapped in
    JSON**, not a plain HTML page. `generic_html` has no mechanism for
    this shape today.
  - Setting `SortCriteria=3` (Title A-Z) instead of the page's default
    `0` (Relevancy) makes pagination deterministic: verified page 1 and
    page 2 share **zero** overlapping job IDs, and results are
    alphabetically continuous across the page boundary (page 1 ends
    "Nuclear Med Tech...", page 2 begins "OR EVS Technician...").
  - The returned fragment's wrapping `<section>` carries
    `data-total-pages="57"` and `data-total-results="1401"` — the true
    page count, so the adapter can fetch exactly that many pages instead
    of guessing or looping to a cap. Verified: page 57 (the reported
    last page) returned exactly 1 job (56 × 25 + 1 = 1401, matching
    `data-total-results` exactly), and page 58 returned zero.
  - The endpoint requires a specific set of query parameters beyond just
    `CurrentPage` — most are empty/constant, but two look
    site-configurable rather than universal: `SearchResultsModuleName`
    ("Search Results") and `SearchFiltersModuleName` ("Search Filters"),
    the CMS-configured names of the page's search modules. These are
    captured as constants for Northwestern Medicine; a different
    TalentBrew-powered site could plausibly use different module names,
    which would need re-discovering the same way (hook the browser's
    network calls on that site) if this adapter is pointed at a second
    employer and it doesn't work out of the box.
- **Real per-job data**: each card carries `data-job-id` (a stable
  numeric ID) on its `<a>`, a real relative `href` to the job detail page
  (`/job/{location-slug}/{title-slug}/{tenantId}/{jobId}`), and a
  `.job-location` span. No posted-date is exposed in the list view.

## Config schema

```python
class TalentBrewSource(BaseSource):
    type: Literal["talentbrew"]
    base_url: str = Field(min_length=1)
    max_pages: int = 60
```

`base_url` is just the site's origin (e.g. `https://jobs.nm.org`) — the
adapter builds both the results-API URL and each job's absolute URL from
it. `max_pages` is a safety cap (default 60, comfortably above
Northwestern Medicine's real 57), since the adapter normally stops based
on the API's own reported `data-total-pages` — the cap only matters if
that value is ever missing or implausibly large.

No `keywords` field: like every other adapter, CareerSpyder's own
`include_keywords`/`exclude_keywords` post-filtering (already applied
uniformly by the orchestrator) is what scopes results, rather than
relying on the platform's own — already demonstrated unreliable — search
filtering.

## Job mapping

| `Job` field | Source |
|---|---|
| `key` | `f"talentbrew:{job_id}"`, where `job_id` is the card link's `data-job-id` attribute |
| `title` | the card's `h2` text |
| `url` | `f"{source.base_url}{href}"`, where `href` is the card link's own `href` attribute (already a complete relative path to the job detail page) |
| `company` | `source.company` (config field — not present in the card data) |
| `location` | the card's `.job-location` text |
| `posted_date` | always `None` — not exposed in the list view |
| `source_name` | `source.name`, same as every other adapter |

## Adapter interface and testability

Matches the existing HTTP-based adapters' pattern — injectable HTTP
call, fixture-based tests, no live network or browser in tests:

```python
def fetch(source: TalentBrewSource, http_get=requests.get) -> list[Job]:
```

- Constant request parameters (everything except `CurrentPage`) live in
  a module-level dict, same pattern as `healthcaresource.py`'s
  `_SEARCH_BODY` constant.
- The page-parsing logic (extract `data-total-pages` from the wrapping
  `<section>`, parse each `.search-job-list-data li` card into a `Job`)
  is exercised with fixture JSON envelopes containing canned HTML
  fragments — no live network or browser.
- The pagination loop (`fetch()` itself) is tested with a fake
  `http_get` returning different canned pages/`data-total-pages` values,
  asserting the loop stops at the reported total, stops early on an
  empty page, and respects `max_pages` as a hard cap.

## Testing / verification plan

- Fixture-based unit tests for page parsing: multiple cards, a card
  missing its location, `data-total-pages` extraction.
- Unit tests for the pagination loop: stops at the reported total pages,
  stops early if a page unexpectedly returns zero cards, respects
  `max_pages` when it's lower than the reported total.
- Unit tests for the config model and web-layer wiring, matching every
  other source type's existing test shape.
- Manual smoke test against the real Northwestern Medicine site before
  considering this done: confirm total job count roughly matches
  `data-total-results`, confirm zero duplicate keys across all fetched
  pages, confirm at least one specific known job's URL resolves.

## Explicitly out of scope for this iteration

- **Verifying this works against a second TalentBrew-powered employer.**
  The hardcoded `SearchResultsModuleName`/`SearchFiltersModuleName`
  constants are a known, documented risk — if this adapter is pointed at
  a different TalentBrew site and it returns empty/errors, that's the
  first thing to re-check (re-run the same network-hooking investigation
  against the new site).
- **The platform's own keyword/location search.** CareerSpyder's
  existing post-filtering covers this; not worth relying on a
  server-side search that was already shown to be unreliable for the
  investigated site.
- **Posted-date extraction.** Not exposed in the list view; would
  require opening each job's detail page, which isn't worth the request
  volume for a field the digest can live without (same tradeoff already
  accepted by the `linkedin`/`indeed` adapters).
