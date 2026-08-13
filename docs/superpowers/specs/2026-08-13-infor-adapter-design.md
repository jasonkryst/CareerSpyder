# Infor Adapter — Design Spec

Date: 2026-08-13
Status: Approved for planning

## Purpose

Add `infor` as a sixth CareerSpyder source type, so job boards hosted on
Infor's Global HR / CandidateSelfService platform (e.g. Rush University
Medical Center's careers site, a primary employer target) can be scraped
like any other source — configured in `sources.json`, run daily, deduped,
included in the digest email.

## Why this needs a dedicated adapter, not `generic_html`

Direct investigation of a real Infor board (Rush University Medical
Center, `rushprod-lm01.cloud.infor.com`) via a live browser session ruled
out every simpler option:

- **No public JSON API.** Unlike Greenhouse/Lever, Infor's Global HR
  module exposes no documented board API. `pip-audit`-style "just hit an
  endpoint" isn't available here.
- **Not static HTML.** The listing page is a classic Java servlet
  frameset (`controller.servlet`) whose job content is rendered
  client-side — a plain HTTP GET returns none of the job data, so
  `generic_html` with `render_js: false` cannot work.
- **Content lives inside a same-origin iframe**, one level deep
  (`.../resources/html/content.html?...`), not in the top-level page.
  `render_js: true` alone wouldn't help either, because the project's
  existing `browser.render_html()` helper returns `page.content()` on the
  *top-level* frame only — it would capture the empty frameset shell, not
  the iframe's content.
- **Rendered by SlickGrid**, a virtualized JS data grid (`slick-row`
  classes) — nothing exists in the HTML until JavaScript populates it, so
  `render_js: false` is a non-starter regardless of the iframe issue
  above. Each row's single `.slick-cell` does contain one self-contained
  `.inforCardstackCell` card (title, posted date, location all inside
  it — confirmed via live DOM inspection, see exact structure below), so
  once the grid has rendered, extracting one page's jobs is a normal
  selector-based parse, not a multi-pane correlation problem.
- **No stable per-job identifier or URL anywhere in the listing.**
  Checked row DOM attributes and jQuery `.data()` directly — nothing.
  Clicking a title navigates the SPA to a detail view in place (no URL
  change, confirmed by inspecting the iframe src before/after) that does
  expose a real `JOB ID` (e.g. `24432`), but there is no known way to
  deep-link to it: two plausible undocumented query-parameter guesses
  (`context.session.key.PrimaryKey`, `context.session.key.JobId`) were
  tested against the real site and neither opened that job directly — one
  broke the page's rendering entirely. Opening every listing's detail view
  just to get an ID is also not viable: it would mean one full page
  navigation per job per run, on top of the pagination cost below.
- **Real pagination**, not one large payload: the Rush board has 518 jobs
  across 52 pages at the default page size of 10, sorted "Recent" (date
  posted descending) by default.

Given all of that, this needs its own adapter that drives Playwright
directly — navigate, find the iframe, wait for the grid, parse the
current page's cards, click "next," repeat up to a configurable limit —
rather than fitting into `generic_html`'s single-fetch model. (The
per-card *parsing* step, once the HTML is in hand, is actually simple —
see below — it's getting that HTML out of a paginated, iframe-nested, JS
grid that `generic_html` has no support for.)

### Real card HTML (Rush board, page 1, row 1)

```html
<div class="inforCardstackCell">
  <span class="inforCardstackImg hotJobsSpan"></span>
  <span class="inforCardstackHeading">Anesthesia Tech 1</span>
  <div class="floatRight PostedDiv">
    <label class="inforCardstackLabel PostedLbl">Posted</label>
    <label class="inforCardstackValue">08/12/2026</label>
  </div>
  <br>
  <label class="inforCardstackLabel LocationLbl">Location</label>
  <label class="inforCardstackValue">US:IL:Chicago</label>
</div>
```

Note there are two `.inforCardstackValue` labels per card (posted date
and location) — distinguish them by position: the one inside
`.PostedDiv` is the posted date, the one that's a direct sibling of
`.LocationLbl` (after the `<br>`) is the location. No `<a href>` anywhere
in the card, confirming the "no per-job link" finding above.

## Config schema

```python
class InforSource(BaseSource):
    type: Literal["infor"]
    url: str = Field(min_length=1)   # the full controller.servlet URL, per employer
    max_pages: int = 3
```

`url` is the complete listing URL as given by the employer (includes
their Infor tenant host and `context.session.key.*` query parameters —
these are board-identifying, not per-visitor session secrets, so they're
safe to store in `sources.json` the same as any other source's `url`).

`max_pages` defaults to 3 (≈30 newest postings per run at page size 10).
Crawling all 52 pages every day would be slow and mostly redundant —
dedup only cares about postings not seen in a prior run, and the board is
already sorted newest-first, so a small bounded crawl captures what
matters. Page size itself is not configurable and stays at the site's
default of 10: SlickGrid virtualizes rows once a page holds "too many" to
render into the DOM at once, and a larger page size risks silently
missing rows that never got virtualized into the snapshot. Employers who
post far more than 30 jobs/day can raise `max_pages`.

## Job mapping

| `Job` field | Source |
|---|---|
| `key` | hash of `company + title + location` (same pattern as `generic_html`/`linkedin`/`indeed` — no platform-native ID is available, see above) |
| `title` | `.inforCardstackHeading` text within the card |
| `location` | the `.inforCardstackValue` label that follows `.LocationLbl` |
| `posted_date` | the `.inforCardstackValue` label inside `.PostedDiv` |
| `company` | `source.company` (config field — not present in row data) |
| `url` | `source.url` — the listing page itself. No per-job link exists (see above); this is a deliberate, documented degradation, not an oversight. The digest still shows the job title so a user can search for it on the board. |
| `source_name` | `source.name`, same as every other adapter |

## Adapter interface and testability

Every existing adapter takes an injectable I/O parameter so tests never
launch a real browser or hit the network (project-wide constraint). This
adapter's real work — driving Playwright through an iframe and clicking
pagination — can't be expressed as a single "fetch this URL" call the way
`html_renderer` is for other adapters. Instead:

```python
def fetch(source: InforSource, frame_fetcher=default_frame_fetcher) -> list[Job]:
    """frame_fetcher(url: str, page_number: int) -> str | None

    Returns the iframe's inner HTML for the given 1-indexed page, or None
    once no more pages are available (crawl stops, whether that's because
    max_pages was reached by the caller or the site ran out of pages).
    """
```

- `default_frame_fetcher` (in `app/adapters/infor.py`) is the real
  implementation: launches Playwright, navigates to `url`, locates the
  job-content iframe via `page.frame_locator("#parentIframe")` (a stable
  `id`/`name` on the iframe element, confirmed via live inspection — not
  a positional index, which would be fragile if the site ever adds
  another iframe), waits for `.slick-row` to appear, returns that frame's
  HTML for page 1. For `page_number > 1`, it clicks
  `button.nextPage[title="Next"]` (also confirmed via live inspection)
  the needed number of times from a persistent page/browser session,
  waiting for the grid to re-render between clicks, and returns each
  subsequent page's frame HTML. If `button.nextPage` is disabled (its
  `disabled` DOM property — confirmed present on the real button when no
  further pages exist) before `page_number` is reached, returns `None`
  early. This function is **not unit tested directly** — same precedent
  as `browser.render_html()` in the existing codebase, which the v1 plan
  explicitly calls out as verified only by manual smoke test.
- The parsing logic (extracting each `.inforCardstackCell` card's title,
  posted date, and location, building `Job` objects) is a separate, pure
  function that takes one page's HTML in and returns `list[Job]` out —
  this gets full fixture-based unit tests, feeding canned card HTML per
  page, including edge cases (a card missing its posted-date or location
  block, a page with zero cards signaling end-of-results before
  `max_pages` is reached).
- `fetch()` itself just loops calling `frame_fetcher` up to `max_pages`
  times, stops early on `None`, and delegates each page's HTML to the
  parsing function — this loop *is* tested, with a fake `frame_fetcher`
  that returns canned pages and asserts the loop stops at the right place
  (both "hit max_pages" and "ran out of real pages before max_pages").

## Web UI wiring

Follows the existing pattern for adding a source type:

- `app/adapters/__init__.py`: register `"infor": infor.fetch` in
  `ADAPTERS`.
- `app/web/source_form.py`: add `"infor": InforSource` to `TYPE_MODELS`;
  `source_from_form` needs an `infor`-specific branch (`url` +
  `max_pages`, parsed as `int`); `echo_source` needs a matching
  `max_pages` field so a validation error round-trips the submitted value
  back into the form.
- `app/web/templates/source_form.html`: add `"infor"` to the type
  `<select>`, a `fields-infor` div (URL + max_pages inputs), matching the
  existing `showFieldsFor()` JS pattern.
- The existing `/sources/test-preview` endpoint needs no changes — it
  already dispatches through `ADAPTERS[source.type]` generically, so
  "Test this source" works for `infor` sources automatically once the
  adapter and form wiring exist. Note for whoever implements: previewing
  an `infor` source is slow (a real Playwright run against a real Infor
  site, potentially multiple page loads) — this is an inherent cost of
  the platform, not a bug to fix.

## Testing / verification plan

- Fixture-based unit tests for the parsing function: multi-card HTML, a
  card missing its posted-date or location block, an empty page (zero
  cards).
- Unit tests for `fetch()`'s pagination loop using a fake `frame_fetcher`:
  stops at `max_pages`, stops early when a page returns `None`, dedupes
  nothing extra (dedup is the orchestrator's job, unchanged).
- Unit tests for the config model (`InforSource` field validation,
  `max_pages` default) and the web-layer wiring (form round-trip,
  `TYPE_MODELS` entry), matching the existing test shape for other source
  types.
- Manual smoke test against the real Rush URL (or another live
  Infor-powered board) before considering this done — confirms the real
  Playwright/iframe/pagination mechanics actually work, since that part
  of the code has no automated coverage by design (see above).

## Explicitly out of scope for this iteration

- **Per-job detail data** (Department, Shift, Pay Range, Job ID) — all of
  it lives behind the detail view this adapter deliberately never opens.
  If a future need justifies the cost of one detail-page load per new
  job (not per listing), that's a separate, later change.
- **Deep-linking to individual postings** — no mechanism was found; noted
  as a known limitation, not a task to keep chasing. If Infor publishes
  documentation for this platform in the future, revisit.
- **Configurable page size** — fixed at 10 to sidestep SlickGrid's row
  virtualization; not worth the complexity of detecting/handling
  virtualized (not-yet-rendered) rows for a rarely-needed knob.
- **Full-catalog crawls** (all 52 pages) — `max_pages` exists specifically
  to avoid this; a one-time full sync, if ever wanted, would be a manual
  one-off script, not something the daily adapter does.
