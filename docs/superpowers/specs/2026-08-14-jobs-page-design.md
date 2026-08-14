# Jobs page — design spec

GitHub issue: [#28](https://github.com/jasonkryst/CareerSpyder/issues/28) "Display Jobs"

## Problem

The web UI has no page listing individual jobs. Jobs are only visible via
the digest email or by inference from `/history`'s new-job counts (also
flagged in ROADMAP.md's "Dashboard doesn't list the jobs it found"). Issue
#28 asks for a dedicated Jobs page showing, per job: company name, search
name, job title, job link, date found, emails sent in, date removed (if no
longer found), age (days found → removed or today, whichever is first),
a summary (first 250 characters), and any other important info.

## Scope decisions (confirmed with user)

- **Summary field**: populated only for `greenhouse` and `lever`, since
  their APIs already return (or can return, with one extra query param)
  a job description at zero extra HTTP cost. Every HTML-scraped adapter
  (`generic_html`, `indeed`, `linkedin`, `infor`, `healthcaresource`,
  `talentbrew`, `workday`, `phenompeople`, `findly`) leaves `summary`
  `None` — getting real description text there would mean an extra
  per-job detail-page fetch, which is out of scope for this issue.
- **Deleted sources**: when a source is removed from `sources.json`
  entirely, its still-active jobs are immediately marked removed (matches
  "no longer found" literally — nothing is checking for them anymore).
- **Version**: 0.6.0 → 0.8.0.

## Data model changes

### `app/models.py`

`Job` gets two new optional fields (defaults keep every existing
`Job(...)` call site valid):

```python
@dataclass
class Job:
    key: str
    title: str
    url: str
    company: str | None = None
    location: str | None = None
    posted_date: str | None = None
    source_name: str = ""
    source_id: str | None = None   # new
    summary: str | None = None     # new
```

`source_id` is the source config's stable `id` (a UUID that survives
renames), not its mutable `name`. This is what removal-reconciliation
matches on — matching on `source_name` would misfire if a source is
renamed. Every adapter adds one line: `source_id=source.id`.

### `app/db.py` — schema

`jobs` table gains four nullable columns: `source_id TEXT`,
`summary TEXT`, `removed_at TEXT`, `emailed_at TEXT`. This project has no
migration framework (README: "No database migration story to manage") —
`init_db` gets a small idempotent step that inspects
`PRAGMA table_info(jobs)` and runs `ALTER TABLE jobs ADD COLUMN ...` for
any of the four that are missing, so existing deployed databases upgrade
in place without a rebuild. `save_jobs`'s `INSERT` includes the two
scrape-time columns (`source_id`, `summary`); `removed_at`/`emailed_at`
start `NULL` and are only ever set by the new functions below.

New functions:

- `list_jobs(conn, limit, offset) -> list[dict]` — all jobs (active and
  removed), newest-found-first (`ORDER BY first_seen_at DESC`), full row
  including the four new columns.
- `count_jobs(conn) -> int`.
- `reconcile_jobs(conn, configured_source_ids: set[str], succeeded_source_ids: set[str], found_jobs: list[Job]) -> None`
  — one call per run, after all sources have been attempted:
  - `found_keys = {j.key for j in found_jobs}` (the **raw**, pre-keyword-filter
    set — see orchestrator note below).
  - `deleted_source_ids` = distinct `source_id` values currently on active
    (`removed_at IS NULL`) jobs, minus `configured_source_ids`.
  - Mark `removed_at = now` for every active job where
    `source_id IN succeeded_source_ids AND key NOT IN found_keys`, or
    `source_id IN deleted_source_ids`.
  - Reactivate (clear `removed_at`) every currently-removed job whose key
    is in `found_keys`.
  - Jobs with `source_id IS NULL` (rows written before this migration)
    are left untouched — there's no reliable way to reconcile them.
- `mark_emailed(conn, keys: list[str]) -> None` — sets `emailed_at = now`
  for the given job keys. Called only after a digest email actually sends
  successfully.

### `app/orchestrator.py`

`run_once` currently builds one filtered job list per source
(`apply_keyword_filters(found, ...)`) and dedupes that for new-job
detection. It now also keeps the **unfiltered** `found` list per
successful source, deduped separately, and passes that — plus the set of
source IDs that succeeded this run and the full set of currently
configured source IDs — to `db.reconcile_jobs` after the existing
new-job save. Using the raw (unfiltered) set for reconciliation means
tightening a source's `include_keywords`/`exclude_keywords` can never
make a still-live posting look "removed" just because it stopped
matching the filter.

### `app/scheduler.py`

After `emailer.send_email(...)` succeeds inside `run_and_notify`'s
existing `try` block, call
`db.mark_emailed(conn, [j.key for j in summary.new_jobs])`. If sending
fails (caught by the existing `except Exception`) or settings aren't
configured, `emailed_at` stays `NULL` — the Jobs page shows an honest
"not emailed" rather than assuming success.

### `app/textutils.py` (new)

One helper, `to_summary(html_or_text: str | None, limit: int = 250) -> str | None`:
strips HTML tags (via BeautifulSoup, already a dependency), collapses
whitespace, and truncates to `limit` characters with a trailing `…` if
truncated. Returns `None` for `None`/empty input. Used by the
`greenhouse` and `lever` adapters.

### `app/adapters/greenhouse.py`

Request URL gains `?content=true` (Greenhouse's board API only returns
the `content` field — an HTML job description — when this is set).
`summary=textutils.to_summary(item.get("content"))`.

### `app/adapters/lever.py`

Lever's postings already include `descriptionPlain` (falls back to
`description`, which is HTML, if `descriptionPlain` is absent).
`summary=textutils.to_summary(item.get("descriptionPlain") or item.get("description"))`.

### All other adapters

One-line addition: `source_id=source.id` on the constructed `Job(...)`.
No `summary` change (stays the dataclass default of `None`).

## Web UI

### `app/web/routes_jobs.py` (new)

`GET /jobs?page=1` — same shape as `routes_history.py`: `db.count_jobs`,
`app/web/pagination.py::paginate` (`PAGE_SIZE = 25`), `db.list_jobs`. The
route computes `age_days` per row (`(removed_at or now) − first_seen_at`,
in whole days, parsed via `datetime.fromisoformat`) since it's a
render-time derivation, not stored state, and passes the enriched rows to
the template.

### `app/web/templates/jobs.html` (new)

Table columns: Company, Search Name, Title (rendered as a link to the
job URL — this covers both "job title" and "job link" from the issue,
matching how `digest.py` already links titles), Location, Date found,
Removed, Age (days), Emailed, Summary. Removed rows get a muted CSS
class. Same pagination nav as `history.html`.

### `app/web/templates/base.html`

New nav link, `Jobs` (`/jobs`), placed right after `Dashboard` and before
`History`.

### `app/web/static/style.css`

One small addition: a `.removed` (or similar) row/text style so removed
jobs are visually distinguishable without a legend.

## Docs & version

- `pyproject.toml`: `0.6.0` → `0.8.0`.
- `CHANGELOG.md`: new `[0.8.0]` entry describing the Jobs page and the
  removal/emailed tracking it's built on.
- `README.md`: Web UI table gets a `/jobs` row; Features list mentions
  removal/summary/emailed tracking; project-structure blurb mentions
  `app/textutils.py` and `routes_jobs.py`.
- `docs/USAGE.md`: page table gets a `/jobs` row.
- `ROADMAP.md`: remove the "Dashboard doesn't list the jobs it found"
  item — `/jobs` now covers it.

## Testing

Per AGENTS.md's TDD convention (failing test first, then the
implementation):

- `tests/test_textutils.py` (new) — strips tags, truncates at 250 with
  ellipsis, `None`/empty input → `None`, short input passed through
  unchanged (no spurious ellipsis).
- `tests/test_db.py` — `list_jobs`/`count_jobs` (ordering, pagination);
  `reconcile_jobs` (removal on a succeeded source, reactivation on
  reappearance, removal on a deleted source, untouched `source_id IS NULL`
  rows, untouched jobs from a *failed* source); `mark_emailed`; a
  migration test that creates a `jobs` table with the pre-existing column
  set via raw `sqlite3`, then calls `db.init_db` on that same path and
  asserts the four new columns exist and old rows survive.
- `tests/test_orchestrator.py` — `source_id` propagates onto saved jobs;
  a job missing from a re-run of the same (succeeded) source gets
  `removed_at` set; a removed job reappearing gets reactivated; a source
  dropped from the `sources` list between two `run_once` calls gets its
  jobs marked removed; a *failed* source's jobs are never touched by
  reconciliation; keyword-filtered-out jobs are not marked removed
  (reconciliation uses the raw set).
- `tests/test_scheduler.py` — `mark_emailed` called with new-job keys
  after a successful send; not called when send fails or settings are
  absent.
- `tests/adapters/test_*.py` (all 11) — add a `source_id` assertion.
  `test_greenhouse.py`/`test_lever.py` additionally get: a positive case
  (description/`descriptionPlain` present → truncated `summary`) and a
  negative case (field absent → `summary is None`); greenhouse's URL
  assertion updates to include `?content=true`.
- `tests/web/test_jobs.py` (new) — empty state; populated rows show
  company/search name/title-link/dates; an active job has no removed
  date and a computed age from today; a removed job shows its removed
  date and an age frozen at removal; emailed vs. not-emailed rendering;
  pagination (second page, invalid/negative page param clamps) mirroring
  `test_history.py`'s positive/negative cases.
