# Job Status Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close GH #48 ("Job Listing Status" — mark a job as applied,
ignored, accepted, or rejected, tracking each status change with a
timestamp), per
`docs/superpowers/specs/2026-08-16-job-status-tracking-design.md`.

**Architecture:** `jobs` gains a denormalized `status` column (current
status) and a new append-only `job_status_history` table records every
transition (including clears) with a timestamp. A new
`POST /jobs/status` route (form fields `key`/`status`, **not** a
`/jobs/{key}/status` path segment — some job keys embed raw URLs) updates
both and redirects through the existing `flash_redirect` toast mechanism.
The Jobs page gets an inline per-row `<select>` that self-submits on
change, a native `<details>` history expander per row, and a Status
filter alongside the existing Company/Source/Removed/Emailed filters.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, vanilla JS/native HTML
(no new JS needed), hand-written CSS, pytest + httpx `TestClient`,
Playwright (`sync_api`) for e2e under `tests/web/e2e/`.

## Global Constraints

- TDD throughout: failing test → minimal implementation → passing test →
  commit, per task. Run `pytest -q` after every task.
- The four status values are exactly `applied`, `ignored`, `accepted`,
  `rejected` — no others are valid input to `set_job_status` or the
  route (empty/`None` means "no status", not a fifth value).
- `job_status_history` is append-only: never `UPDATE` or `DELETE` a row
  in it. A `status IS NULL` history row represents "cleared back to no
  status" and is itself a recorded change.
- The route is `POST /jobs/status` with `key` as a form field, never
  `POST /jobs/{key}/status` — job keys from some adapters
  (`indeed:{href}`, `linkedin:{href}`) contain raw URLs with `/` and `:`,
  which would break path routing.
- Reuse the existing `KeyError` → `HTTPException(404)` convention
  (`app/db.py` raises `KeyError` on an unknown key; the route catches it)
  — same pattern as `config.get_source`/`update_source`/`delete_source`.
- No new color tokens or per-status badge styling — render status as
  plain text/options, consistent with how `removed_at`/`emailed_at`
  render today.
- `POST /jobs/status` redirects to the bare `/jobs` (no filter/sort/page
  preservation) — matches the existing behavior of
  `/sources/{id}/delete` and `/sources/{id}/edit`, not a new gap.
- Bump `pyproject.toml`'s version (`0.14.0` → `0.15.0`) as part of this
  branch, per this repo's one-minor-bump-per-PR convention.

---

### Task 1: DB layer — status column, history table, `set_job_status`, `get_job_status_history`

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `set_job_status(conn: sqlite3.Connection, key: str, status: str | None) -> None` —
    raises `KeyError` if `key` doesn't exist. Later tasks call this by
    name with exactly these two positional args after `conn`.
  - `get_job_status_history(conn: sqlite3.Connection, keys: list[str]) -> dict[str, list[dict]]` —
    returns `{job_key: [{"status": str | None, "changed_at": str}, ...]}`,
    newest-first per key, omitting keys with no history entirely (no
    empty-list entry — callers use `.get(key, [])`).
  - `jobs.status` column (nullable `TEXT`) and `job_status_history` table,
    both created via the existing migration path.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db.py — add near the top with the other imports
import pytest
```

```python
# tests/test_db.py — append at the end of the file
def test_init_db_creates_job_status_history_table(tmp_db_path):
    conn = db.init_db(tmp_db_path)

    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "job_status_history" in tables


def test_set_job_status_updates_current_status(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    db.set_job_status(conn, "k1", "applied")

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["status"] == "applied"


def test_set_job_status_records_a_history_entry(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    db.set_job_status(conn, "k1", "applied")

    history = db.get_job_status_history(conn, ["k1"])
    assert len(history["k1"]) == 1
    assert history["k1"][0]["status"] == "applied"
    assert history["k1"][0]["changed_at"] is not None


def test_set_job_status_appends_rather_than_replacing_history(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    db.set_job_status(conn, "k1", "applied")
    db.set_job_status(conn, "k1", "rejected")

    history = db.get_job_status_history(conn, ["k1"])
    assert [h["status"] for h in history["k1"]] == ["rejected", "applied"]
    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["status"] == "rejected"


def test_set_job_status_to_none_clears_current_status_and_is_recorded(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.set_job_status(conn, "k1", "applied")

    db.set_job_status(conn, "k1", None)

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["status"] is None
    history = db.get_job_status_history(conn, ["k1"])
    assert [h["status"] for h in history["k1"]] == [None, "applied"]


def test_set_job_status_on_unknown_key_raises_key_error(tmp_db_path):
    conn = db.init_db(tmp_db_path)

    with pytest.raises(KeyError):
        db.set_job_status(conn, "does-not-exist", "applied")


def test_get_job_status_history_omits_key_with_no_changes(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    history = db.get_job_status_history(conn, ["k1"])

    assert history.get("k1", []) == []


def test_get_job_status_history_with_empty_keys_list_returns_empty_dict(tmp_db_path):
    conn = db.init_db(tmp_db_path)

    assert db.get_job_status_history(conn, []) == {}


def test_get_job_status_history_groups_by_key_for_a_batch(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1"), make_job(key="k2")], db.start_run(conn))
    db.set_job_status(conn, "k1", "applied")
    db.set_job_status(conn, "k2", "ignored")

    history = db.get_job_status_history(conn, ["k1", "k2"])

    assert set(history.keys()) == {"k1", "k2"}
    assert history["k1"][0]["status"] == "applied"
    assert history["k2"][0]["status"] == "ignored"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v -k "status"`
Expected: FAIL (`AttributeError: module 'app.db' has no attribute 'set_job_status'`)

- [ ] **Step 3: Write the implementation**

`app/db.py` — add `job_status_history` to `SCHEMA`, right after the
`jobs` table definition and before `runs`:

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    url TEXT NOT NULL,
    posted_date TEXT,
    source_name TEXT NOT NULL,
    source_id TEXT,
    summary TEXT,
    first_seen_run_id INTEGER,
    first_seen_at TEXT NOT NULL,
    removed_at TEXT,
    emailed_at TEXT
);

CREATE TABLE IF NOT EXISTS job_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL,
    status TEXT,
    changed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
```

(Only the new `job_status_history` block is inserted; `runs` and
`settings` stay exactly as they are.)

Add `"status": "TEXT"` to `_NEW_JOB_COLUMNS` so the additive migration
picks it up on existing databases:

```python
_NEW_JOB_COLUMNS = {
    "source_id": "TEXT",
    "summary": "TEXT",
    "removed_at": "TEXT",
    "emailed_at": "TEXT",
    "status": "TEXT",
}
```

Append the two new functions at the end of `app/db.py`, after
`reconcile_jobs`:

```python
def set_job_status(conn: sqlite3.Connection, key: str, status: str | None) -> None:
    now = _now()
    cur = conn.execute("UPDATE jobs SET status = ? WHERE key = ?", (status, key))
    if cur.rowcount == 0:
        raise KeyError(key)
    conn.execute(
        "INSERT INTO job_status_history (job_key, status, changed_at) VALUES (?, ?, ?)",
        (key, status, now),
    )
    conn.commit()


def get_job_status_history(conn: sqlite3.Connection, keys: list[str]) -> dict[str, list[dict]]:
    if not keys:
        return {}
    placeholders = ",".join("?" * len(keys))
    rows = conn.execute(
        f"SELECT job_key, status, changed_at FROM job_status_history "
        f"WHERE job_key IN ({placeholders}) ORDER BY changed_at DESC, id DESC",
        keys,
    ).fetchall()
    history: dict[str, list[dict]] = {}
    for job_key, status, changed_at in rows:
        history.setdefault(job_key, []).append({"status": status, "changed_at": changed_at})
    return history
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (all, including every pre-existing test in the file)

- [ ] **Step 5: Run full suite, commit**

```bash
pytest -q
git add app/db.py tests/test_db.py
git commit -m "Add job status history tracking to the DB layer"
```

---

### Task 2: `status` filter on `list_jobs`/`count_jobs`

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `set_job_status` (Task 1) to set up filtered fixtures.
- Produces: `list_jobs(..., status: str | None = None)` and
  `count_jobs(..., status: str | None = None)` — `""`/`None` means no
  filter, `"none"` means `status IS NULL`, any of the four status values
  filters to an exact match. Each `list_jobs` row dict now includes a
  `"status"` key. Task 4's route relies on this.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db.py — append
def test_list_jobs_filters_by_status(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [_job("a"), _job("b")], db.start_run(conn))
    db.set_job_status(conn, "a", "applied")

    applied = db.list_jobs(conn, status="applied")
    none_status = db.list_jobs(conn, status="none")

    assert [r["key"] for r in applied] == ["a"]
    assert [r["key"] for r in none_status] == ["b"]


def test_count_jobs_respects_status_filter(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [_job("a")], db.start_run(conn))
    db.set_job_status(conn, "a", "rejected")

    assert db.count_jobs(conn, status="rejected") == 1
    assert db.count_jobs(conn, status="applied") == 0


def test_list_jobs_returns_status_field_defaulting_to_none(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [_job("a")], db.start_run(conn))

    rows = db.list_jobs(conn)

    assert rows[0]["status"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v -k "status"`
Expected: FAIL (`TypeError: list_jobs() got an unexpected keyword argument 'status'`)

- [ ] **Step 3: Write the implementation**

`app/db.py` — extend `_job_filters_sql`:

```python
def _job_filters_sql(
    company: str | None, source_name: str | None, removed: str | None, emailed: str | None,
    status: str | None = None,
) -> tuple[str, list]:
    clauses = []
    params: list = []
    if company:
        clauses.append("LOWER(company) LIKE ?")
        params.append(f"%{company.lower()}%")
    if source_name:
        clauses.append("source_name = ?")
        params.append(source_name)
    if removed == "active":
        clauses.append("removed_at IS NULL")
    elif removed == "removed":
        clauses.append("removed_at IS NOT NULL")
    if emailed == "sent":
        clauses.append("emailed_at IS NOT NULL")
    elif emailed == "not_sent":
        clauses.append("emailed_at IS NULL")
    if status == "none":
        clauses.append("status IS NULL")
    elif status:
        clauses.append("status = ?")
        params.append(status)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params
```

`list_jobs` and `count_jobs` — add the `status` parameter and thread it
through, and add `status` to `list_jobs`'s `SELECT`/row dict:

```python
def list_jobs(
    conn: sqlite3.Connection, limit: int = 25, offset: int = 0, *,
    sort: str = "", direction: str = "",
    company: str | None = None, source_name: str | None = None,
    removed: str | None = None, emailed: str | None = None, status: str | None = None,
) -> list[dict]:
    order_column = _JOB_SORT_COLUMNS.get(sort, "first_seen_at")
    order_dir = "ASC" if direction == "asc" else "DESC"
    where_sql, params = _job_filters_sql(company, source_name, removed, emailed, status)
    query = (
        "SELECT key, title, company, location, url, posted_date, source_name, source_id, "
        "summary, first_seen_at, removed_at, emailed_at, status FROM jobs "
        f"{where_sql} ORDER BY {order_column} {order_dir}, rowid {order_dir} LIMIT ? OFFSET ?"
    )
    rows = conn.execute(query, [*params, limit, offset]).fetchall()
    return [
        {
            "key": r[0], "title": r[1], "company": r[2], "location": r[3], "url": r[4],
            "posted_date": r[5], "source_name": r[6], "source_id": r[7], "summary": r[8],
            "first_seen_at": r[9], "removed_at": r[10], "emailed_at": r[11], "status": r[12],
        }
        for r in rows
    ]


def count_jobs(
    conn: sqlite3.Connection, *,
    company: str | None = None, source_name: str | None = None,
    removed: str | None = None, emailed: str | None = None, status: str | None = None,
) -> int:
    where_sql, params = _job_filters_sql(company, source_name, removed, emailed, status)
    row = conn.execute(f"SELECT COUNT(*) FROM jobs {where_sql}", params).fetchone()
    return row[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (all, including every pre-existing test in the file)

- [ ] **Step 5: Run full suite, commit**

```bash
pytest -q
git add app/db.py tests/test_db.py
git commit -m "Add status filter to list_jobs/count_jobs"
```

---

### Task 3: `POST /jobs/status` route

**Files:**
- Modify: `app/web/routes_jobs.py`
- Test: `tests/web/test_jobs.py`

**Interfaces:**
- Consumes: `db.set_job_status` (Task 1), `flash_redirect` (existing,
  `app/web/flash.py`).
- Produces: `STATUSES: dict[str, str]` module-level constant (ordered
  `{"applied": "Applied", "ignored": "Ignored", "accepted": "Accepted",
  "rejected": "Rejected"}`) in `app/web/routes_jobs.py`. Task 4 imports
  this name for both the GET route's template context and validation —
  don't rename it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_jobs.py — add near the top with the other imports
from urllib.parse import parse_qs, urlparse
```

```python
# tests/web/test_jobs.py — append
def test_post_job_status_sets_status_and_redirects_with_flash(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    resp = client.post("/jobs/status", data={"key": "k1", "status": "applied"}, follow_redirects=False)

    assert resp.status_code == 303
    location = urlparse(resp.headers["location"])
    assert location.path == "/jobs"
    assert parse_qs(location.query)["flash"] == ["Marked as Applied."]
    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["status"] == "applied"


def test_post_job_status_clearing_redirects_with_cleared_message(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.set_job_status(conn, "k1", "applied")

    resp = client.post("/jobs/status", data={"key": "k1", "status": ""}, follow_redirects=False)

    location = urlparse(resp.headers["location"])
    assert parse_qs(location.query)["flash"] == ["Status cleared."]
    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["status"] is None


def test_post_job_status_invalid_status_returns_400(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    resp = client.post("/jobs/status", data={"key": "k1", "status": "bogus"})

    assert resp.status_code == 400
    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["status"] is None


def test_post_job_status_unknown_key_returns_404(client):
    resp = client.post("/jobs/status", data={"key": "does-not-exist", "status": "applied"})

    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_jobs.py -v -k "post_job_status"`
Expected: FAIL (404 "Not Found" — the route doesn't exist yet)

- [ ] **Step 3: Write the implementation**

`app/web/routes_jobs.py` — add imports and the new constant/route:

```python
from fastapi import APIRouter, HTTPException, Query, Request
```

```python
from app.web.flash import flash_redirect
```

```python
STATUSES = {"applied": "Applied", "ignored": "Ignored", "accepted": "Accepted", "rejected": "Rejected"}
```

(place `STATUSES` right after the existing `PAGE_SIZE = 25` line)

```python
@router.post("/jobs/status")
async def update_job_status(request: Request):
    form = dict((await request.form()).items())
    key = form.get("key", "")
    status = form.get("status", "") or None
    if status is not None and status not in STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    try:
        db.set_job_status(request.app.state.conn, key, status)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    message = f"Marked as {STATUSES[status]}." if status else "Status cleared."
    return flash_redirect("/jobs", message)
```

(add this function after the existing `jobs()` route, at the end of the
file)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_jobs.py -v`
Expected: PASS (all, including every pre-existing test in the file)

- [ ] **Step 5: Run full suite, commit**

```bash
pytest -q
git add app/web/routes_jobs.py tests/web/test_jobs.py
git commit -m "Add POST /jobs/status route for setting a job's status"
```

---

### Task 4: Jobs page UI — status column, filter, expandable history

**Files:**
- Modify: `app/web/routes_jobs.py`
- Modify: `app/web/templates/jobs.html`
- Modify: `app/web/static/style.css`
- Test: `tests/web/test_jobs.py`

**Interfaces:**
- Consumes: `db.get_job_status_history` (Task 1), `list_jobs`/`count_jobs`
  `status` filter (Task 2), `STATUSES` (Task 3), `POST /jobs/status`
  (Task 3, as the row form's `action`).
- Produces: nothing new consumed by later tasks.

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_jobs.py — append
def test_jobs_page_shows_status_select_with_current_status_selected(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.set_job_status(conn, "k1", "applied")

    resp = client.get("/jobs")

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    select = soup.select_one('form[action="/jobs/status"] select[name="status"]')
    assert select is not None
    selected = select.select_one("option[selected]")
    assert selected["value"] == "applied"


def test_jobs_page_shows_status_history_entries(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.set_job_status(conn, "k1", "applied")
    db.set_job_status(conn, "k1", "rejected")

    resp = client.get("/jobs")

    assert "Applied" in resp.text
    assert "Rejected" in resp.text
    assert "<summary>History</summary>" in resp.text


def test_jobs_page_hides_history_details_when_no_changes(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    resp = client.get("/jobs")

    assert "<summary>History</summary>" not in resp.text


def test_jobs_page_status_filter_shows_only_matching_jobs(client):
    conn = client.app.state.conn
    db.save_jobs(
        conn,
        [make_job(key="k1", title="Applied Job"), make_job(key="k2", title="Other Job")],
        db.start_run(conn),
    )
    db.set_job_status(conn, "k1", "applied")

    resp = client.get("/jobs?status=applied")

    assert "Applied Job" in resp.text
    assert "Other Job" not in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_jobs.py -v -k "status or history"`
Expected: FAIL (no status column/filter in the rendered page yet)

- [ ] **Step 3: Write the implementation**

`app/web/routes_jobs.py` — update the `jobs()` route to accept/thread the
`status` filter and attach per-row status/history data:

```python
@router.get("/jobs", response_class=HTMLResponse)
def jobs(
    request: Request, page: str = "1", sort: str = "",
    direction: str = Query("", alias="dir"),
    company: str = "", source: str = "", removed: str = "", emailed: str = "", status: str = "",
):
    conn = request.app.state.conn
    filters = {
        "company": company or None, "source_name": source or None,
        "removed": removed or None, "emailed": emailed or None, "status": status or None,
    }
    total = db.count_jobs(conn, **filters)
    pagination = paginate(total, page, PAGE_SIZE)
    rows = db.list_jobs(
        conn, limit=PAGE_SIZE, offset=pagination.offset, sort=sort, direction=direction, **filters,
    )
    history = db.get_job_status_history(conn, [row["key"] for row in rows])
    for row in rows:
        row["age_days"] = _age_days(row["first_seen_at"], row["removed_at"])
        row["safe_url"] = safe_url_scheme(row["url"])
        row["history"] = [
            {"status_label": STATUSES.get(entry["status"], "No status"), "changed_at": entry["changed_at"]}
            for entry in history.get(row["key"], [])
        ]
    source_names = db.list_job_source_names(conn)
    return templates.TemplateResponse(request, "jobs.html", {
        "jobs": rows, "pagination": pagination, "source_names": source_names, "statuses": STATUSES,
        "filters": {
            "company": company, "source": source, "removed": removed, "emailed": emailed, "status": status,
        },
    })
```

(Only the signature, `filters` dict, the new `history`
lookup/`row["history"]` line, and the template context's `"statuses"`/
`"status"` additions change; `_age_days`, `PAGE_SIZE`, and the rest of
the function body stay as they are.)

`app/web/templates/jobs.html` — add the Status filter to the filter bar,
right after the existing Emailed `<label>` and before the `<button
type="submit">`:

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

Update the "Clear filters" condition on the same line as the submit
button to include `filters.status`:

```jinja
  {% if filters.company or filters.source or filters.removed or filters.emailed or filters.status %}<a href="/jobs">Clear filters</a>{% endif %}
```

Add a `Status` header cell to `<thead>`, between `Emailed` and
`Summary`:

```jinja
    <th scope="col">Emailed</th>
    <th scope="col">Status</th>
    <th scope="col">Summary</th>
```

Add the Status `<td>` to each row, in the same position (between the
`Emailed` and `Summary` cells):

```jinja
    <td data-label="Emailed">{{ job.emailed_at or "Not sent" }}</td>
    <td data-label="Status">
      <form method="post" action="/jobs/status" class="inline-status-form">
        <input type="hidden" name="key" value="{{ job.key }}">
        <select name="status" onchange="this.form.submit()" aria-label="Status for {{ job.title }}">
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
    </td>
    <td data-label="Summary">{{ job.summary or "—" }}</td>
```

`app/web/static/style.css` — append near the other table-related rules
(after the `tr.removed td` rule):

```css
.inline-status-form {
  margin: 0;
}

.status-history {
  list-style: none;
  margin: var(--space-2) 0 0;
  padding: 0;
  font-size: 0.875rem;
  color: var(--fg-muted);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_jobs.py -v`
Expected: PASS (all, including every pre-existing test in the file)

- [ ] **Step 5: Run full suite, commit**

```bash
pytest -q
git add app/web/routes_jobs.py app/web/templates/jobs.html app/web/static/style.css tests/web/test_jobs.py
git commit -m "Add status column, filter, and history expander to the Jobs page"
```

---

### Task 5: e2e — real-browser status change

**Files:**
- Create: `tests/web/e2e/test_job_status.py`

**Interfaces:**
- Consumes: everything from Tasks 1-4, running against the real
  `live_server`.
- Produces: nothing (leaf task).

- [ ] **Step 1: Write the test**

```python
# tests/web/e2e/test_job_status.py
import os

from app import db
from app.models import Job


def test_marking_a_job_applied_shows_toast_and_history(live_server, page):
    conn = db.init_db(os.environ["CAREERSPYDER_DB_PATH"])
    job = Job(key="e2e-status-job", title="E2E Status Job", url="https://example.com/job/e2e-status-job")
    run_id = db.start_run(conn)
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])

    page.goto(live_server + "/jobs")
    row = page.locator("tr", has_text="E2E Status Job")
    row.locator('select[name="status"]').select_option("applied")

    page.wait_for_selector(".toast")
    assert page.locator(".toast").inner_text().strip().startswith("Marked as Applied.")

    row = page.locator("tr", has_text="E2E Status Job")
    row.locator("summary", has_text="History").click()
    assert "Applied" in row.locator(".status-history").inner_text()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/web/e2e/test_job_status.py -v`
Expected: FAIL if any Task 1-4 markup/behavior is wrong; otherwise PASS
immediately since Tasks 1-4 are already complete by this point in the
plan — treat any failure here as a real bug in an earlier task, not an
ordering issue.

- [ ] **Step 3: Fix any markup/behavior issues found, then re-run**

Run: `pytest tests/web/e2e/test_job_status.py -v`
Expected: PASS

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (unit + web + e2e)

- [ ] **Step 5: Commit**

```bash
git add tests/web/e2e/test_job_status.py
git commit -m "Add e2e coverage for job status changes"
```

---

### Task 6: Documentation + version bump

**Files:**
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/USAGE.md`
- Modify: `app/web/templates/guide.html`

**Interfaces:**
- Consumes: nothing (docs only).
- Produces: nothing.

- [ ] **Step 1: Bump the version**

In `pyproject.toml`, change `version = "0.14.0"` to `version = "0.15.0"`.

- [ ] **Step 2: Update CHANGELOG.md**

`CHANGELOG.md` currently has an empty `## [Unreleased]` heading directly
above `## [0.14.0] — 2026-08-16`. Insert the new entry between them
(`## [Unreleased]` stays empty, as-is):

```markdown
## [0.15.0] — 2026-08-16

### Added

- Job status tracking on the Jobs page — mark a job as Applied, Ignored,
  Accepted, or Rejected (or clear it back to no status) from an inline
  dropdown per row. Every change is timestamped and kept in a per-job
  history, viewable via an expandable "History" section on each row. A
  new Status filter narrows the table to a given status or to jobs with
  no status set (issue #48).
```

- [ ] **Step 3: Update README.md**

In the `## Web UI` section, reword the `/jobs` row — replace:

```markdown
| `/jobs` | Every job CareerSpyder has ever found — company, search name, linked title (opens in a new tab), location, dates found/removed, age, emailed status, and a summary where available. Sortable by company, title, date found, or age; filterable by company, source, and removed/emailed status. |
```

with:

```markdown
| `/jobs` | Every job CareerSpyder has ever found — company, search name, linked title (opens in a new tab), location, dates found/removed, age, emailed status, status (Applied/Ignored/Accepted/Rejected, with a per-job change history), and a summary where available. Sortable by company, title, date found, or age; filterable by company, source, removed/emailed status, and status. |
```

- [ ] **Step 4: Update docs/USAGE.md**

In the `## Web UI tour` section, reword the `Jobs (`/jobs`)` row —
replace:

```markdown
| Jobs (`/jobs`) | Every job ever found — company, search name, title/link (opens in a new tab), location, dates found/removed, age, emailed status, and a summary where available. Sortable by company, title, date found, or age; filterable by company, source, and removed/emailed status. |
```

with:

```markdown
| Jobs (`/jobs`) | Every job ever found — company, search name, title/link (opens in a new tab), location, dates found/removed, age, emailed status, status (Applied/Ignored/Accepted/Rejected, with a per-job change history), and a summary where available. Sortable by company, title, date found, or age; filterable by company, source, removed/emailed status, and status. |
```

- [ ] **Step 5: Update app/web/templates/guide.html**

In `app/web/templates/guide.html`, the Jobs row of the "Web UI tour"
table currently reads:

```html
  <tr><td><a href="/jobs">Jobs</a></td><td>Every job CareerSpyder has ever found &mdash;
    sortable by company, title, date found, or age; filterable by company, source, and
    removed/emailed status. Job titles open in a new tab.</td></tr>
```

Replace it with:

```html
  <tr><td><a href="/jobs">Jobs</a></td><td>Every job CareerSpyder has ever found &mdash;
    sortable by company, title, date found, or age; filterable by company, source,
    removed/emailed status, and status. Job titles open in a new tab. Mark a job as
    Applied/Ignored/Accepted/Rejected and view its change history.</td></tr>
```

- [ ] **Step 6: Verify and commit**

```bash
pytest -q
git add pyproject.toml CHANGELOG.md README.md docs/USAGE.md app/web/templates/guide.html
git commit -m "Update docs and bump version to 0.15.0 for #48"
```

---

### Task 7: Final full-suite verification

**Files:** none (verification only)

- [ ] **Step 1:** `pytest -q` — expect all tests passing, 0 failures.
- [ ] **Step 2:** `pytest tests/web/e2e -v` — expect all e2e passing
  (already covered by Step 1, run in isolation as a final sanity check
  given these exercise a real chromium browser).
- [ ] **Step 3:** Manually smoke-test in a real browser (see
  `AGENTS.md`'s `uvicorn app.web.main:app --reload --port 8080`):
  - On `/jobs` (with at least one job present), change a job's status via
    the dropdown — confirm a toast appears, the dropdown reflects the new
    status after the page reloads, and expanding "History" shows the
    change with a timestamp.
  - Change the status again to a different value, then clear it back to
    "—" — confirm the history accumulates all three entries in
    newest-first order.
  - Use the new Status filter to narrow the table to one status, and to
    "No status" — confirm only matching rows appear, and "Clear filters"
    resets it along with the other filters.
