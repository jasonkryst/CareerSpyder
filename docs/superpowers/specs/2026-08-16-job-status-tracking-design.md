# Job Status Tracking — Design Spec

Date: 2026-08-16
Status: Approved for planning

## Purpose

Closes GH #48 ("Job Listing Status" — "Mark a job as applied for, ignored,
accepted, rejected. Track each status change with a timestamp").

The issue body is terse; scope was clarified directly with the user — see
Decisions below.

## Decisions (from user clarification)

| Question | Decision |
|---|---|
| History depth | Full history log — every status transition is recorded with its own timestamp, not just a single "current status changed at" value |
| Where to set status | Inline `<select>` per row on the Jobs table |
| Status filter | Yes — add a Status filter to the existing Jobs filter bar |
| Default / clear | Jobs start with no status (`NULL`); the dropdown includes a way to clear back to "no status" |
| History visibility | Expandable per row (not just recorded silently) |

## Data model (`app/db.py`)

`jobs` gains one nullable column, added through the existing additive
migration path (`_NEW_JOB_COLUMNS` / `_migrate_jobs_table`):

```
status TEXT   -- 'applied' | 'ignored' | 'accepted' | 'rejected' | NULL
```

This is the *current* status, kept denormalized on the row so `list_jobs`/
`count_jobs` can filter and render it without a join — same reasoning as
the existing `removed_at`/`emailed_at` columns.

New table, added to `SCHEMA` (`CREATE TABLE IF NOT EXISTS`, consistent with
`jobs`/`runs`/`settings`):

```sql
CREATE TABLE IF NOT EXISTS job_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL,
    status TEXT,
    changed_at TEXT NOT NULL
);
```

Append-only audit trail. `status IS NULL` represents "cleared back to no
status" — clearing is itself a recorded change, per the issue's "track
each status change" requirement. No foreign key (this schema doesn't use
them elsewhere; `sources.json`, not this table, is authoritative for
whether a source still exists, and jobs already outlive their source via
`removed_at`).

### New functions

- `set_job_status(conn, key: str, status: str | None) -> None` — updates
  `jobs.status`, inserts one `job_status_history` row with the same
  timestamp. Raises `KeyError` if `key` doesn't match any row (checked via
  the `UPDATE` statement's `rowcount`), mirroring `config.get_source`/
  `update_source`'s miss behavior so the route can reuse the existing
  `KeyError` → `404` convention from `AGENTS.md`.
- `get_job_status_history(conn, keys: list[str]) -> dict[str, list[dict]]`
  — one batched `WHERE job_key IN (...)` query (same shape as
  `get_new_jobs`), returns `{job_key: [{"status": ..., "changed_at": ...}, ...]}`
  ordered newest-first per key. Called once per Jobs page render with the
  current page's keys — avoids N+1 queries for the expandable history.

### Filtering

`_job_filters_sql`, `list_jobs`, `count_jobs` gain a `status` parameter,
same shape as `removed`/`emailed`:

- `""` (absent) → no filter (all jobs)
- `"none"` → `status IS NULL`
- `"applied"` / `"ignored"` / `"accepted"` / `"rejected"` → `status = ?`

## Route (`app/web/routes_jobs.py`)

```
POST /jobs/status
```

Form fields: `key` (the job's primary key) and `status` (one of `""`,
`applied`, `ignored`, `accepted`, `rejected`).

**Not** `/jobs/{key}/status` — several adapters build job keys directly
from URLs (`indeed:{href}`, `linkedin:{href}` — see `app/adapters/`),
which contain `/` and `:`. A path segment would break FastAPI routing or
require encode/decode handling neither introduced nor needed elsewhere in
this codebase. A form field carries the key as an opaque string with zero
extra handling.

```python
_STATUSES = {"applied", "ignored", "accepted", "rejected"}
_STATUS_LABELS = {"applied": "Applied", "ignored": "Ignored",
                   "accepted": "Accepted", "rejected": "Rejected"}

@router.post("/jobs/status")
async def update_job_status(request: Request):
    form = dict((await request.form()).items())
    key = form.get("key", "")
    status = form.get("status", "") or None
    if status is not None and status not in _STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    try:
        db.set_job_status(request.app.state.conn, key, status)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    message = f"Marked as {_STATUS_LABELS[status]}." if status else "Status cleared."
    return flash_redirect("/jobs", message)
```

Redirects to the bare `/jobs` (no filter/sort/page preservation) — this
matches the existing behavior of `POST /sources/{id}/delete` and
`/sources/{id}/edit`, which also drop back to the unfiltered list. Not a
regression introduced by this feature; consistent with what's already
there.

The `jobs()` GET route gains a `status: str = ""` query param, threaded
into the `filters` dict alongside the existing four, and computes
`history = db.get_job_status_history(conn, [row["key"] for row in rows])`
once per render, attaching `row["history"] = history.get(row["key"], [])`
to each row dict before passing to the template (same shape as the
existing `row["age_days"]`/`row["safe_url"]` post-processing).

## UI (`jobs.html`)

New "Status" column, containing:

```jinja
<form method="post" action="/jobs/status" class="inline-status-form">
  <input type="hidden" name="key" value="{{ job.key }}">
  <select name="status" onchange="this.form.submit()">
    <option value="" {% if not job.status %}selected{% endif %}>&mdash;</option>
    {% for value, label in statuses.items() %}
    <option value="{{ value }}" {% if job.status == value %}selected{% endif %}>{{ label }}</option>
    {% endfor %}
  </select>
</form>
{% if job.history %}
<details>
  <summary>History</summary>
  <ul class="status-history">
    {% for entry in job.history %}
    <li>{{ entry.status_label }} &mdash; {{ entry.changed_at }}</li>
    {% endfor %}
  </ul>
</details>
{% endif %}
```

- `<details>/<summary>` is native HTML — no JS needed, matches this
  codebase's "no frontend build step" ethos and the existing pattern of
  reaching for plain markup before adding a script (e.g. the pagination
  nav, the filter bar).
- The inline `onchange="this.form.submit()"` needs no new JS file, same
  spirit as the filter bar's plain `<form method="get">`. (If CSP or
  inline-script policy becomes a concern later, this can move to
  `nav.js`-style delegation, but nothing in this codebase currently
  restricts inline handlers.)
- `statuses` (an ordered `{value: label}` dict) and each row's
  `entry.status_label`/`"No status"` fallback come from the route, not
  computed in the template — keeps `_STATUS_LABELS` as the single source
  of truth.
- No new color tokens or per-status badge styling — the existing design
  system has `--success`/`--error` pairs only, and inventing four new
  status colors is speculative beyond what the issue asks for. Plain text
  is consistent with how `removed_at`/`emailed_at` are rendered today.

New "Status" filter `<select>` in the filter bar, same style as the
existing Company/Source/Removed/Emailed controls:

```jinja
<label>Status
  <select name="status">
    <option value="">All</option>
    <option value="none" {% if filters.status == "none" %}selected{% endif %}>No status</option>
    {% for value, label in statuses.items() %}
    <option value="{{ value }}" {% if filters.status == value %}selected{% endif %}>{{ label }}</option>
    {% endfor %}
  </select>
</label>
```

## Testing

TDD per `AGENTS.md`. Positive and negative cases:

**`tests/test_db.py`**
- Positive: `set_job_status` updates `jobs.status` and inserts a matching
  `job_status_history` row; setting a second status appends a second
  history row (both preserved, ordered by `changed_at`); setting `None`
  after a status records a `NULL`-status history row and clears
  `jobs.status`.
- Positive: `list_jobs`/`count_jobs` with `status="applied"` /
  `status="none"` return the expected subset; `get_job_status_history`
  returns per-key grouped, newest-first results for a batch of keys,
  including a key with no history (empty list, not a `KeyError`).
- Negative: `set_job_status` on an unknown key raises `KeyError`.

**`tests/web/test_jobs.py`**
- Positive: `POST /jobs/status` with a valid key/status redirects (303)
  with the expected `flash` message; the job's row on a follow-up `GET
  /jobs` shows the new status selected and a new `<li>` in its history;
  clearing (`status=""`) shows "Status cleared." and the row reverts to
  no status while history still shows the prior entries.
- Positive: `GET /jobs?status=applied` returns only jobs with that status;
  `GET /jobs?status=none` returns only jobs with no status.
- Negative: `POST /jobs/status` with an invalid `status` value → `400`,
  job's status unchanged.
- Negative: `POST /jobs/status` with an unknown `key` → `404`.

**e2e (`tests/web/e2e/`)** — one representative scenario: change a job's
status via the dropdown, confirm the toast and the new history entry
appear, matching the existing e2e style added for #45/#46.

## Documentation + version

- `pyproject.toml`: `0.14.0` → `0.15.0`.
- `CHANGELOG.md`: new `## [0.15.0]` entry under `Added` — job status
  tracking (applied/ignored/accepted/rejected) with a full change history
  and a Jobs page filter (issue #48).
- `docs/USAGE.md`: extend the `/jobs` row (~line 34) to mention status
  and its filter, mirrored into `README.md`'s Web UI table and
  `app/web/templates/guide.html`'s Jobs row — same three-place pattern
  used for the toast/external-link doc update.

## Explicitly out of scope

- Per-status color coding / badges — no new design tokens invented beyond
  what the existing plain-text row rendering already does.
- Editing or deleting past history entries — the log is append-only by
  design; a mis-set status is corrected by setting a new status, which is
  itself recorded.
- Surfacing status in the digest email — the issue is about tracking
  status on the Jobs page, not about changing what the scheduled digest
  reports.
- Bulk status changes (multi-select rows) — issue describes marking
  individual jobs.
- Preserving Jobs page filters/sort/page across a status-change redirect
  — matches existing behavior of the other Jobs/Sources mutating routes,
  not a new gap introduced here.
