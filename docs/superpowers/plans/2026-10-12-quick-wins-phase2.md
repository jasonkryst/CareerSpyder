# Implementation Plan — Quick-Wins Phase 2 (v1.10.0)

**Branch:** `feat/quick-wins-phase2`  
**Base:** `origin/master` (e424c52 — Feat/quick wins phase1 #229)  
**Target version:** 1.10.0  
**Issues:** #218, #215, #224, #214, #219

---

## Spec

`docs/superpowers/specs/2026-08-09-careerspyder-design.md`

---

## Global Constraints

(All inherited from the design spec and AGENTS.md — implementers must read
AGENTS.md before touching any file.)

1. **`SMTP_PASSWORD` is container env only.** Never write to DB, pydantic model, or template.
2. **Tests must not make live network calls or launch a real browser.** Adapter `fetch()` tests use injectable `http_get`/`html_renderer`.
3. **All DB queries that read user data must scope by `user_id`** (omitting is a privacy bug).
4. **psycopg3 placeholder syntax is `%s`**, NOT `?`.
5. **One shared `Jinja2Templates` instance** from `app/web/templating.py`. Never instantiate another.
6. **Scraped/user-supplied text must be safe in HTML.** Jinja2 autoescape covers templates; any raw HTML assembly needs manual escaping.
7. **Every response carries baseline security headers** via `SecurityHeadersMiddleware` — don't add routes that bypass it.
8. **`sources.json` atomic writes only** — always via `save_sources`, never direct `open(path, "w")`.
9. **One failing source must not abort others** — per-source try/except in orchestrator.
10. **Digest sent only when ≥1 new job or ≥1 failed source** — `build_digest` returns `None` on clean run.

---

## Task 1 — #218: Keyword filters also match company and location

**Issue:** `apply_keyword_filters` in `app/filters.py` currently checks `job.title` only.
The fix is to also check `job.company` and `job.location` so a search for "Google"
finds jobs at Google regardless of title.

### Files to create/modify

- **`app/filters.py`** — extend both include and exclude branches to check
  `title OR company OR location` (all lowercased, None-safe).
- **`tests/test_filters.py`** — add tests:
  - `test_include_keyword_matches_company` — include "google", job has company="Google Inc", title="SWE" → included.
  - `test_include_keyword_matches_location` — include "seattle", job has location="Seattle, WA" → included.
  - `test_exclude_keyword_matches_company` — exclude "facebook", job has company="Facebook" → excluded.
  - `test_exclude_keyword_matches_location` — exclude "remote", job has location="Remote" → excluded.
  - `test_keyword_filter_still_matches_title` — regression: existing title-match behavior unchanged.
  - `test_none_company_and_location_do_not_raise` — job with company=None, location=None and an include keyword → no exception.

### Exact implementation

```python
# app/filters.py
from app.models import Job


def _fields(j: Job) -> str:
    """Return a single lowercased string combining title, company, and location."""
    parts = [j.title, j.company or "", j.location or ""]
    return " ".join(parts).lower()


def apply_keyword_filters(jobs: list[Job], include: list[str], exclude: list[str]) -> list[Job]:
    result = jobs
    if include:
        needles = [k.lower() for k in include]
        result = [j for j in result if any(n in _fields(j) for n in needles)]
    if exclude:
        needles = [k.lower() for k in exclude]
        result = [j for j in result if not any(n in _fields(j) for n in needles)]
    return result
```

### Commit message

```
feat: expand keyword filters to match company and location (issue #218)
```

---

## Task 2 — #215: Relative timestamps with |timeago Jinja2 filter

**Issue:** All dates in the UI render as raw ISO-8601 strings. A `|timeago` filter
should convert a datetime string to a human-readable relative string like
"3 hours ago", "2 days ago", "just now" and display an `<abbr title="<iso>">` 
so the full timestamp is accessible on hover.

### Files to create/modify

- **`app/web/templating.py`** — register a `timeago` Jinja2 filter.
- **`app/web/templates/_history_rows.html`** — apply `|timeago` to `started_at` and `finished_at` `<time>` cells.
- **`app/web/templates/jobs.html`** — apply `|timeago` to the `first_seen_at` column (if displayed).
- **`tests/test_timeago.py`** (NEW) — unit tests for the filter function itself:
  - `test_just_now` — input within 60 seconds → "just now".
  - `test_minutes_ago` — 90 seconds → "1 minute ago".
  - `test_hours_ago` — 7200 seconds → "2 hours ago".
  - `test_days_ago` — 3 days → "3 days ago".
  - `test_weeks_ago` — 14 days → "2 weeks ago".
  - `test_months_ago` — 60 days → "2 months ago".
  - `test_none_returns_empty` — `None` input → empty string `""`.
  - `test_invalid_string_returns_value` — unparseable string → returns the raw string unchanged (graceful degradation).

### Exact implementation

The filter function lives in a new module `app/web/timeago.py` and is registered
in `templating.py`. The template renders the result inside a `<time datetime>` element
so screen readers and search crawlers get the ISO date.

```python
# app/web/timeago.py
from datetime import UTC, datetime


def timeago(value: str | None) -> str:
    if value is None:
        return ""
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return str(value)
    now = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        m = seconds // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if seconds < 86400:
        h = seconds // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    if seconds < 7 * 86400:
        d = seconds // 86400
        return f"{d} day{'s' if d != 1 else ''} ago"
    if seconds < 30 * 86400:
        w = seconds // (7 * 86400)
        return f"{w} week{'s' if w != 1 else ''} ago"
    m = seconds // (30 * 86400)
    return f"{m} month{'s' if m != 1 else ''} ago"
```

In `templating.py`, add after the `templates` instance is created:

```python
from app.web.timeago import timeago as _timeago_fn
templates.env.filters["timeago"] = _timeago_fn
```

In `_history_rows.html`, change:
```html
<time datetime="{{ run.started_at }}">{{ run.started_at }}</time>
```
to:
```html
<abbr title="{{ run.started_at }}"><time datetime="{{ run.started_at }}">{{ run.started_at | timeago }}</time></abbr>
```
(same pattern for `finished_at`).

### Commit message

```
feat: add |timeago Jinja2 filter for relative timestamps (issue #215)
```

---

## Task 3 — #224: Pagination jump-to-page input

**Issue:** When there are many pages, users must click Prev/Next repeatedly.
A "Jump to page" input lets them type a page number and go directly.

The jump form must:
- Submit as `GET` with `page=<N>` appended to the current URL.
- Preserve all existing query parameters (sort, dir, filters) as hidden `<input>` elements.
- Appear only when `total_pages > 2` (less than 3 pages and Prev/Next is sufficient).
- Accept only positive integers (client-side `type="number" min="1"` plus server-side clamping already in `paginate()`).

### Files to create/modify

The pagination nav is duplicated across three templates — update all three:

- **`app/web/templates/_history_rows.html`** — add jump-to-page in the `<nav aria-label="Pagination">` block.
- **`app/web/templates/jobs.html`** — same in its `<nav aria-label="Pagination">` block.
- **`app/web/templates/sources.html`** — same.

All three nav blocks follow the same `Previous | Page N of M | Next` pattern.
The jump form is appended after the `Next` link but inside the `<nav>`.

### Exact markup pattern (each paginated template)

```html
<nav aria-label="Pagination">
  {% if pagination.has_prev %}<a href="{{ query_url(request, BASE_PATH, page=pagination.page - 1) }}">Previous</a>{% endif %}
  <span>Page {{ pagination.page }} of {{ pagination.total_pages }}</span>
  {% if pagination.has_next %}<a href="{{ query_url(request, BASE_PATH, page=pagination.page + 1) }}">Next</a>{% endif %}
  {% if pagination.total_pages > 2 %}
  <form method="get" action="BASE_PATH" class="pagination-jump">
    {% for key, val in request.query_params.multi_items() %}
    {% if key != "page" %}<input type="hidden" name="{{ key }}" value="{{ val }}">{% endif %}
    {% endfor %}
    <label>Go to page
      <input type="number" name="page" min="1" max="{{ pagination.total_pages }}"
             value="{{ pagination.page }}" style="width:4em">
    </label>
    <button type="submit">Go</button>
  </form>
  {% endif %}
</nav>
```

Replace `BASE_PATH` with the route's actual path (`/`, `/jobs`, `/sources`).

### Tests

- **`tests/web/test_dashboard.py`** (existing) — add:
  - `test_pagination_jump_shown_when_many_pages` — seed 60 runs, GET `/`, assert `pagination-jump` in response.
  - `test_pagination_jump_hidden_when_two_pages` — seed 40 runs, GET `/`, assert `pagination-jump` NOT in response (total_pages == 2 with PAGE_SIZE=25 → only 2 pages, not > 2).
- **`tests/web/test_sources_list.py`** — add:
  - `test_pagination_jump_shown_for_sources_when_many_pages` — seed 55 sources, GET `/sources`, assert `pagination-jump` in response.
- **`tests/web/test_jobs.py`** (existing) — add:
  - `test_pagination_jump_shown_for_jobs_when_many_pages` — seed 60 jobs, GET `/jobs`, assert `pagination-jump` in response.

### Commit message

```
feat: add jump-to-page input to pagination controls (issue #224)
```

---

## Task 4 — #214: Dashboard stat cards

**Issue:** The dashboard has no at-a-glance stats. Add a row of stat cards at the top
showing: total jobs, jobs added this week, sources configured, total scrape runs.

### Files to create/modify

- **`app/db.py`** — add `dashboard_stats(conn, user_id: str | None) -> dict`:
  - `total_jobs: int` — COUNT(*) from `jobs` scoped by user_id (None = all).
  - `new_this_week: int` — COUNT(*) from `jobs` where `first_seen_at >= now() - interval '7 days'`.
  - `total_sources: int` — COUNT(*) from `sources` scoped by user_id.
  - `total_runs: int` — COUNT(*) from `runs` where `kind = 'scrape'` scoped by user_id.
  - Admins pass `user_id=None` to aggregate across all users.
- **`app/web/routes_dashboard.py`** — call `db.dashboard_stats(conn, filter_user_id)` in `_dashboard_context()` and add `"stats"` to the context dict.
- **`app/web/templates/dashboard.html`** — add a `<div class="stat-cards">` block with 4 cards before the history toolbar.

### Exact DB function signature

```python
def dashboard_stats(conn: psycopg.Connection, user_id: str | None) -> dict:
    """Return aggregate stats for the dashboard header cards."""
```

### Exact template markup

```html
<div class="stat-cards">
  <div class="stat-card">
    <span class="stat-value">{{ stats.total_jobs }}</span>
    <span class="stat-label">Total jobs</span>
  </div>
  <div class="stat-card">
    <span class="stat-value">{{ stats.new_this_week }}</span>
    <span class="stat-label">New this week</span>
  </div>
  <div class="stat-card">
    <span class="stat-value">{{ stats.total_sources }}</span>
    <span class="stat-label">Sources</span>
  </div>
  <div class="stat-card">
    <span class="stat-value">{{ stats.total_runs }}</span>
    <span class="stat-label">Scrape runs</span>
  </div>
</div>
```

### Tests

- **`tests/test_db.py`** (existing) — add:
  - `test_dashboard_stats_all_zeros_on_empty_db` — fresh DB → all four counters are 0.
  - `test_dashboard_stats_counts_jobs_for_user` — insert 2 jobs for user A, 1 for user B, call with user_id=A → total_jobs=2.
  - `test_dashboard_stats_none_user_id_aggregates_all` — insert 2 jobs for user A, 1 for user B, call with user_id=None → total_jobs=3.
  - `test_dashboard_stats_new_this_week_excludes_old` — insert 1 job with `first_seen_at` 8 days ago → new_this_week=0.
  - `test_dashboard_stats_total_sources` — add 2 sources for a user → total_sources=2.
  - `test_dashboard_stats_total_runs_only_scrape` — finish 2 scrape runs and 1 url_check run → total_runs=2.
- **`tests/web/test_dashboard.py`** (existing) — add:
  - `test_dashboard_renders_stat_cards` — GET `/`, assert `"stat-cards"` in response text and `"Total jobs"` in response text.

### Commit message

```
feat: add stat cards to dashboard header (issue #214)
```

---

## Task 5 — #219: Run history source count + links to failed sources

**Issue:** The run history table shows a flat list of failed source names but no
count of how many sources were scraped total. Users want "2 / 15 failed" with
links to the source edit pages.

### Scope (confirmed by user)

- Add `source_count` to `runs` table: how many sources were attempted per run.
- Add `source_id` to each entry in the `failed_sources` JSON array so failed
  sources can be linked to their `/sources/{id}/edit` page.
- Show "N / M failed" in the dashboard table where N = failed count and M = source_count.
- Failed source names become links to `/sources/{source_id}/edit` when `source_id` is present.

### Files to create/modify

**Database (Alembic migration)**

- **`alembic/versions/0004_run_source_count.py`** — adds `source_count INTEGER DEFAULT 0`
  column to `runs` table. Must be backward-compatible (existing rows get DEFAULT 0).

Migration template:
```python
"""add source_count to runs

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('runs', sa.Column('source_count', sa.Integer(), nullable=False, server_default='0'))

def downgrade() -> None:
    op.drop_column('runs', 'source_count')
```

**`app/db.py`**

- `finish_run(conn, run_id, new_job_count, failed_sources, *, source_count: int = 0)` — add `source_count` parameter, include in UPDATE.
- `_deserialize_failed_sources` — must handle both old `{"name": ..., "url": ...}` and
  new `{"name": ..., "url": ..., "source_id": ...}` entries gracefully (source_id is optional).
- `list_runs` — include `source_count` in SELECT and returned dict.

**`app/models.py`**

- `FailedSource` — add optional field `source_id: str | None = None`.

**`app/orchestrator.py`**

- Pass `source_id` when building `FailedSource` objects:
  ```python
  failed_sources.append(FailedSource(name=source.name, url=get_source_url(source), source_id=source.id))
  ```
- Count sources attempted and pass to `finish_run`:
  ```python
  db.finish_run(conn, run_id, len(new_jobs), failed_sources, source_count=len(sources))
  ```

**`app/web/templates/_history_rows.html`**

- Replace the failed-sources list with a "N / M failed" summary where N = `run.failed_sources|length` and M = `run.source_count`. When N > 0, render the source links.
- Failed source name becomes an `<a href="/sources/{{ fs.source_id }}/edit">` when `fs.source_id` is present, otherwise plain text (backward-compatible with old runs).

Markup change:
```html
<td data-label="Failed sources">
  {% set fail_count = run.failed_sources | length %}
  {% if run.source_count %}
    <span>{{ fail_count }} / {{ run.source_count }} failed</span>
  {% elif fail_count %}
    <span>{{ fail_count }} failed</span>
  {% endif %}
  {% if fail_count %}
  <ul class="failed-sources-list">
    {% for fs in run.failed_sources %}
    <li>
      {% if fs.source_id %}<a href="/sources/{{ fs.source_id }}/edit">{{ fs.name }}</a>
      {% elif fs.url %}{{ external_link(fs.url, fs.name) }}
      {% else %}{{ fs.name }}{% endif %}
    </li>
    {% endfor %}
  </ul>
  {% endif %}
</td>
```

### Tests

- **`tests/test_db.py`** — add:
  - `test_finish_run_stores_source_count` — call `finish_run(..., source_count=5)`, read back run, assert `source_count == 5`.
  - `test_finish_run_default_source_count_zero` — call without `source_count`, assert `source_count == 0`.
  - `test_list_runs_includes_source_count` — finish a run with source_count=3, list_runs returns dict with `source_count == 3`.
  - `test_deserialize_failed_sources_handles_missing_source_id` — JSON without source_id → no KeyError, `source_id` is None or absent.
- **`tests/web/test_dashboard.py`** — add:
  - `test_run_history_shows_source_count_fraction` — finish run with source_count=10 and 2 failed sources, GET `/`, assert "2 / 10 failed" in response.
  - `test_run_history_failed_source_links_to_edit` — finish run with failed source that has source_id, GET `/`, assert `/sources/{id}/edit` link in response.

### Commit message

```
feat: track source count per run and link failed sources to edit pages (issue #219)
```

---

## Task 6 — Docs, version, and close-out

### Files to modify

1. **`pyproject.toml`** — bump `version = "1.9.0"` → `"1.10.0"`.
2. **`CHANGELOG.md`** — move `## [Unreleased]` section contents to `## [1.10.0] — 2026-10-12` and open a new empty `## [Unreleased]`. Add entries for all 5 issues.
3. **`docs/issue-tiers.md`** — mark issues #218, #215, #224, #214, #219 as resolved (add `✅` or `[resolved]` annotation per file's convention).
4. **`ROADMAP.md`** — remove any entries for #218, #215, #224, #214, #219 if present; note v1.10.0 ships.

### CHANGELOG entries to add (under `## [1.10.0] — 2026-10-12 > ### Added`)

```
- **Keyword filters now match company and location (issue #218).** `apply_keyword_filters` previously checked only job title. Include and exclude keywords now also match against company name and job location, so a filter for "Google" finds postings at Google Inc regardless of title.
- **Relative timestamps (issue #215).** All dates in the dashboard and jobs list now render as human-readable relative times ("3 hours ago", "2 days ago") with the full ISO timestamp shown on hover via `<abbr title>`.
- **Jump-to-page pagination (issue #224).** All paginated views (dashboard, jobs, sources) gain a "Go to page" input when there are more than 2 pages, letting users jump directly to a page without clicking Prev/Next repeatedly.
- **Dashboard stat cards (issue #214).** A row of four stat cards at the top of the dashboard shows total jobs, jobs added this week, sources configured, and total scrape runs. Admins see aggregate counts across all users.
- **Run history source count and links (issue #219).** The run history table now shows "N / M failed" (failed count / total sources attempted). Failed source names link directly to their edit pages.
```

### Commit message

```
chore: bump to v1.10.0, update CHANGELOG and docs for quick-wins phase 2
```

---

## Pre-flight conflict scan

| Tasks sharing a file | Producer | Consumer | Status |
|---|---|---|---|
| Tasks 1 & 6 | Task 1 touches `app/filters.py` | Task 6 only touches docs/pyproject | No conflict |
| Tasks 4 & 5 & 6 | Tasks 4+5 touch `app/db.py` | Task 6 only touches docs/pyproject | No conflict |
| Tasks 4 & 5 | Task 4 adds `dashboard_stats()` to `app/db.py`; Task 5 adds `source_count` param to `finish_run()` | Different functions, no interdependency | No conflict |
| Tasks 3, 4 | Both touch `tests/web/test_dashboard.py` | Task 3 adds 2 tests, Task 4 adds 1 test | Sequential execution avoids conflict |
| Tasks 2, 4 | Task 2 adds filter to `app/web/templating.py`; Task 4 touches `app/web/routes_dashboard.py` | Different files | No conflict |
| Task 5 | Adds `source_count` to `finish_run` → `app/orchestrator.py` uses `finish_run` | Must update orchestrator in same task | Handled: both in Task 5 |

**Ruling:** Tasks are independent except `test_dashboard.py` shared between Tasks 3 and 4. Execute sequentially (default SDD behavior). Task 5 must include `orchestrator.py` and `_history_rows.html` in the same commit with `db.py` to keep the codebase consistent.
