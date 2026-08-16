# Table Sorting & Filters — Design Spec

Date: 2026-08-16
Status: Approved for planning

## Purpose

Closes GH #33 ("Table Updates" — "Column sorting", "Light filters").

The issue itself is two lines with no page named. Scope was clarified with
the user directly (see decisions below): all three of the app's paginated
tables — Jobs (`/jobs`), Dashboard run history (`/`, `/rows`), and Sources
(`/sources`) — get clickable column-header sorting and a small set of
dropdown/text filters, all applied server-side (so they're correct across
the full dataset, not just the currently-loaded page) and encoded in the
URL query string (bookmarkable, survives refresh, works with browser
back/forward).

## Decisions (from user clarification)

| Table | Sortable columns | Filters |
|---|---|---|
| Jobs (`/jobs`) | Company, Title, Date found, Age (days) | Company (text, substring), Search name/source (dropdown), Removed status (Active/Removed), Emailed status (Emailed/Not sent) |
| Dashboard history (`/`) | Started, Finished, New jobs | Has failures (Only runs with failed sources / Only clean runs) |
| Sources (`/sources`) | Name, Type, Company | Type (dropdown) |

All server-side; all URL-encoded (`?sort=&dir=&<filter params>`).

## Shared mechanism

New `app/web/query_params.py`:

```python
def query_url(request, path, **overrides) -> str
def sort_url(request, path, field) -> str
```

`query_url` takes the current `request.query_params`, applies key
overrides (a `None` or `""` value removes the key — used to drop `page`
whenever sort/filter changes so the user lands on page 1), and returns
`"{path}?{querystring}"` (or bare `path` if the result is empty).

`sort_url` implements a 3-state click cycle per column: not the active
sort field → `asc`; active field currently `asc` → `desc`; active field
currently `desc` → `asc`. It always drops `page` (a new sort always
starts back at page 1) and is built on top of `query_url`.

Both are registered as Jinja globals in `app/web/templating.py` so every
template can call them directly; `request` is already in template context
via FastAPI's `Jinja2Templates`.

A new Jinja macro, `app/web/templates/_sort_header.html::sort_th(request,
path, field, label)`, renders one `<th scope="col">` with a `sort_url`
link, an ARIA `aria-sort` attribute (`ascending`/`descending`, omitted
entirely when this column isn't the active sort — matches WAI-ARIA
authoring practice of not asserting `"none"` explicitly), and a small
▲/▼ text indicator. Imported with `{% from "_sort_header.html" import
sort_th %}` in `jobs.html`, `sources_list.html`, and `_history_rows.html`.

Existing pagination links (`Previous`/`Next`, currently hardcoded like
`/jobs?page={{ pagination.page - 1 }}`) switch to `query_url(request,
'<path>', page=...)` so pagination preserves whatever sort/filter is
active instead of silently dropping it.

## Jobs (`/jobs`)

**`app/db.py`:**
- `list_jobs(conn, limit=25, offset=0, *, sort="", direction="", company=None, source_name=None, removed=None, emailed=None)` —
  `sort` is looked up in a whitelist dict (`_JOB_SORT_COLUMNS`: `company`
  → `company COLLATE NOCASE`, `title` → `title COLLATE NOCASE`,
  `first_seen_at` → `first_seen_at`, `age_days` → `(julianday(COALESCE(removed_at,
  'now')) - julianday(first_seen_at))`), falling back to `first_seen_at`
  for anything not in the whitelist — this is also the SQL-injection
  guard, since `sort`/`direction` never reach the query string
  unvalidated. `direction` is `"ASC"` only when the param is exactly
  `"asc"`, else `"DESC"` — this exactly preserves today's hardcoded
  `ORDER BY first_seen_at DESC, rowid DESC` when no sort params are
  present at all (existing tests assert this ordering; must not change
  it). `rowid` stays as a same-direction tiebreaker for stability.
  Filters become `WHERE` clauses: `company` → `LOWER(company) LIKE
  ?` (`%value%`), `source_name` → exact match, `removed` → `active` means
  `removed_at IS NULL`, `removed` means `removed_at IS NOT NULL`,
  `emailed` → `sent` means `emailed_at IS NOT NULL`, `not_sent` means
  `emailed_at IS NULL`. Anything else (missing/unrecognized) is not
  filtered.
- `count_jobs(conn, *, company=None, source_name=None, removed=None, emailed=None)` —
  same filter args, shares the `WHERE`-building logic with `list_jobs` via
  a private `_job_filters_sql(...)` helper (avoids the two functions'
  filters drifting apart).
- `list_job_source_names(conn) -> list[str]` (new) — `SELECT DISTINCT
  source_name FROM jobs ORDER BY source_name COLLATE NOCASE`, used to
  populate the "Search name" filter dropdown with only sources that have
  actually produced a job (not every configured source).

**`app/web/routes_jobs.py`:** `jobs()` gains explicit query params
(`sort: str = ""`, `direction: str = Query("", alias="dir")`, `company:
str = ""`, `source: str = ""`, `removed: str = ""`, `emailed: str = ""`),
passes them through to `count_jobs`/`list_jobs`, fetches
`list_job_source_names` for the dropdown, and adds `source_names` and
`filters` (a dict mirroring the raw query values, for re-populating the
form) to the template context.

**`app/web/templates/jobs.html`:** sortable headers via `sort_th` for
Company/Title/Date found/Age (days) only — Location, Removed, Emailed,
Search name, Summary stay plain `<th>`. A `<form method="get"
action="/jobs" class="filter-bar">` above the table: text input
(`company`), two `<select>`s (`source` populated from `source_names`,
`removed`, `emailed`), a submit button, hidden `sort`/`dir` inputs (so
submitting a filter doesn't lose the active sort), and a "Clear filters"
link (`href="/jobs"`, shown only when any filter is active).

## Dashboard history (`/`, `/rows`)

**`app/db.py`:**
- `list_runs(conn, limit=50, offset=0, *, sort="", direction="", failures=None)` —
  whitelist `_RUN_SORT_COLUMNS` (`started_at`, `finished_at`,
  `new_job_count`), falling back to `id` (not `started_at`) when `sort`
  is empty/unrecognized — `id` is what today's `ORDER BY id DESC`
  actually uses, and is a better default tiebreaker than a timestamp
  string. Same direction rule as jobs (`asc` param → `ASC`, else
  `DESC`), with `id {direction}` as a secondary tiebreaker always (needed
  once sorting by the non-unique `new_job_count`). `failures="only"` →
  `WHERE failed_sources != '[]'`; `failures="clean"` → `WHERE
  failed_sources = '[]'`; anything else → no filter.
- `count_runs(conn, *, failures=None)` — shares filter SQL with
  `list_runs` via `_run_filters_sql(...)`.

**`app/web/routes_dashboard.py`:** `_dashboard_context` gains `sort`,
`direction` (`Query(..., alias="dir")`), `failures` parameters (both `/`
and `/rows` route functions declare and forward them — same shape as the
existing `page` threading).

**Where the filter form lives:** `dashboard.html`, *not*
`_history_rows.html`. `_history_rows.html`'s `#history-rows` div is
replaced wholesale on every poll/refresh (`dashboard.js`); a filter form
living there would flicker/reset mid-interaction during the 10s
auto-poll. The sortable `<th>` links do live inside
`_history_rows.html` (the table itself is what gets swapped) but that's
fine — a real link click is a full-page navigation regardless of the
polling JS.

**`app/web/templates/dashboard.html`:** new `<form method="get"
action="/" class="filter-bar">` between the existing
`.history-toolbar` and the `{% include "_history_rows.html" %}`: one
`<select name="failures">` (All / Only runs with failed sources / Only
clean runs), hidden `sort`/`dir` inputs, submit button, conditional
"Clear filters" link.

**`app/web/templates/_history_rows.html`:** `sort_th` for
Started/Finished/New jobs; Failed sources stays plain. Pagination links
become `query_url(request, '/', page=...)`.

**`app/web/static/dashboard.js`:** `refresh()` currently reads
`container.getAttribute("data-page")` to rebuild the `/rows?page=N`
fetch URL. Replaced with `window.location.search` directly — the full
current query string (page, sort, dir, failures) is already correct
because it only ever changes via a real navigation (sort click, filter
submit, pagination link), never via the polling JS itself. This also
lets the now-unused `data-page` attribute be dropped from
`_history_rows.html` entirely.

## Sources (`/sources`)

Sources aren't SQLite-backed — `config.load_sources` reads the whole
`sources.json` into a Python list on every request. Sort/filter happen
in Python in the route, before pagination slicing (still "server-side"
in the sense the user cares about: correct across the full list, not
just the current page).

**`app/web/routes_sources.py`:** `list_sources()` gains `sort: str = ""`,
`direction: str = Query("", alias="dir")`, `source_type: str =
Query("", alias="type")`. Available types for the filter dropdown come
from the currently-loaded sources themselves (`sorted({s.type for s in
all_sources})`), not the full `ADAPTERS` registry — same reasoning as
Jobs' source-name dropdown (only offer options that actually narrow the
list to something). A `_SOURCE_SORT_KEYS` dict maps `name`/`type`/`company`
to a `lambda s: (s.<attr> or "").lower()` key function; when `sort` is
empty/unrecognized, no `sorted()` call happens at all — the list stays
in file order, exactly matching today's behavior and existing tests
(`test_sources_list_second_page_shows_remaining_sources` depends on
`Source 0` staying first). When `sort` **is** given, direction defaults
to ascending (`reverse=direction == "desc"`) rather than mirroring
Jobs/History's "default to desc" rule — sources have no natural
recency-based default order the way jobs/runs do, so first click behaving
like a conventional A→Z table sort is the more intuitive default here.
Filtering by `source_type` happens before pagination, same as the other
two tables.

**`app/web/templates/sources_list.html`:** `sort_th` for Name/Type/Company;
Edit/Delete stay plain. Filter form: one `<select name="type">`, hidden
`sort`/`dir`, submit, conditional "Clear filters".

## Styling

`app/web/static/style.css`:
- `.filter-bar` — same flex/gap/wrap shape as the existing
  `.history-toolbar`, but with `flex-wrap: wrap` since it holds more
  controls and needs to reflow on narrow screens (existing
  `.history-toolbar` only ever holds two buttons, never wraps today).
- `th a { color: inherit; text-decoration: none; }` /
  `th a:hover { text-decoration: underline; }` — sortable header links
  shouldn't look like ordinary body links (default link color would
  clash with the `th`'s `--bg-elevated` header styling).

No changes to the existing `@media (max-width: 40rem)` card-table rules —
sortable headers degrade gracefully there since `.table-scroll thead` is
already visually hidden (`position: absolute; left: -9999px`) on narrow
screens; the filter forms are plain block-level forms above the table and
already reflow fine under the existing responsive rules used elsewhere
(source form, settings forms).

## Testing

TDD per this repo's convention — failing test, then implementation.
Positive and negative cases per table:

**`app/db.py` (unit, `tests/test_db.py`)**
- Positive: `list_jobs(sort="company", direction="asc")` returns
  alphabetical order; `sort="age_days"` orders correctly for a mix of
  active and removed jobs (removed job's age is fixed at removal time,
  not "now"); each filter (`company`, `source_name`, `removed`,
  `emailed`) narrows results correctly, including combined filters.
  Same shape for `list_runs`/`count_runs` with `failures`.
  `list_job_source_names` returns distinct, alphabetically-ordered names.
- Negative: unrecognized `sort` value falls back to the default column
  instead of raising `sqlite3.OperationalError`; `count_jobs`/`count_runs`
  with a filter that matches nothing returns `0`; a filter combination
  that matches nothing returns an empty list, not an error.
- Regression: calling `list_jobs()`/`list_runs()` with **no** new
  keyword args at all reproduces today's exact default ordering (guards
  the "don't change the default view" constraint).

**`tests/web/test_jobs.py`**
- Positive: `GET /jobs?sort=company&dir=asc` renders rows in that order;
  each filter individually (and in combination) narrows the visible
  rows; the filter dropdown lists distinct source names; sort links
  carry `aria-sort`; "Clear filters" link only appears when a filter is
  active.
- Negative: `GET /jobs?sort=nonsense` doesn't 500 and falls back to the
  default view; `GET /jobs?company=` (empty string) behaves identically
  to no filter at all; a filter matching zero jobs renders the empty
  table (not an error) and pagination reflects `total=0`.

**`tests/web/test_dashboard.py`**
- Positive: sorting by each of the three columns; `failures=only` /
  `failures=clean` each narrow correctly; `/rows` accepts and honors the
  same params as `/` (used by the AJAX refresh); pagination links from
  `/` preserve an active sort/filter.
- Negative: invalid `sort`/`failures` values don't error and fall back
  to the existing default view; existing default-ordering tests
  (`test_dashboard_lists_past_runs`, `test_dashboard_second_page_...`)
  stay green unmodified.

**`tests/web/test_sources_list.py`**
- Positive: sort by each of the three columns; `type` filter narrows to
  matching sources; filter dropdown only lists types actually present.
- Negative: invalid `sort`/`type` values fall back to file order /
  no filter, no error; existing
  `test_sources_list_second_page_shows_remaining_sources` (depends on
  unsorted file order) stays green unmodified.

**`tests/web/e2e/`** (new file, `test_table_sort_and_filter.py`) — real
Playwright/chromium against `live_server`, per existing e2e convention:
clicking a Jobs column header re-orders visible rows and toggles the
arrow indicator on a second click; submitting the Jobs filter form
narrows visible rows; the Dashboard's polling refresh (`dashboard.js`)
still fetches `/rows` with the current sort/filter query string attached
(regression guard for the `data-page` → `window.location.search` change)
— reuse the existing `page.route("**/rows*", ...)` mock pattern from
`test_dashboard_rows_refresh.py` but assert on the intercepted request's
query string this time.

## Documentation + version

- `CHANGELOG.md`: new `## [0.13.0]` entry under `Added` — column sorting
  and filters on Jobs/Dashboard/Sources (issue #33).
- `pyproject.toml`: `0.12.0` → `0.13.0`.
- `README.md`: update the `/`, `/jobs`, `/sources` rows in the Web UI
  table (line ~231-233) to mention sorting/filtering. Also fix a
  pre-existing stale reference on line 90 (architecture table still
  lists `/history` among the Web UI routes — that route was removed in
  #42; drop it while touching this section).
- `docs/USAGE.md`: same Web UI tour table update (mirrors README's Web
  UI section).
- `app/web/templates/guide.html`: same Web UI tour table update — this
  table is also missing a **Jobs** row entirely (pre-existing gap,
  unrelated to #33; the in-app guide never got one when Jobs shipped).
  Adding it now since this section is already being touched for the
  sort/filter copy.
- `ROADMAP.md`: no changes — nothing there references table
  sorting/filtering.

## Explicitly out of scope

- Multi-column sort (one column at a time only, matches "light" framing
  of the issue).
- Saved/named filter presets.
- Filtering Jobs by date range, or Sources by name/company substring
  (only the fields the user picked during clarification).
- Any change to `PAGE_SIZE` (25) on any of the three tables.
- Server-side sort indexes/`CREATE INDEX` — dataset sizes here are
  small (single-operator tool per `AGENTS.md`); the computed `age_days`
  SQL expression sort is O(n) but that's fine at this scale, and adding
  indexes now would be premature optimization.
