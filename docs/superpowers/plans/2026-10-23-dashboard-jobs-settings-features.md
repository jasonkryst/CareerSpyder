# Dashboard/Jobs/Settings Feature Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close GitHub issues #213 (live run-progress feedback), #222 (bulk job
status update), #220 (per-job notes), and #221 (settings-import diff/preview)
on one branch, with full test coverage and green CI.

**Architecture:** Each issue is additive to an existing route/template/db
module and follows patterns already established in this codebase (the
duplicate-marking modal, the `set_job_status` KeyError-on-miss convention,
the dashboard history-table polling). No new subsystems, no new
dependencies. #213 uses polling (not SSE) per product decision. #221 uses an
inline diff-then-confirm flow on the same page (not a separate
token-backed route) per product decision.

**Tech Stack:** FastAPI (sync route handlers + psycopg3), Jinja2 templates,
vanilla JS (no framework), PostgreSQL 17 via Alembic migrations, pytest +
httpx TestClient.

**Spec:** GitHub issues
[#213](https://github.com/jasonkryst/CareerSpyder/issues/213),
[#222](https://github.com/jasonkryst/CareerSpyder/issues/222),
[#220](https://github.com/jasonkryst/CareerSpyder/issues/220),
[#221](https://github.com/jasonkryst/CareerSpyder/issues/221).

## Global Constraints

- Every DB query touching `jobs`/`sources`/`settings` is scoped by
  `user_id`; add a case to `tests/test_tenant_isolation_db.py` for every new
  per-user mutation (AGENTS.md).
- A missing/non-owned id raises `KeyError` from `app/db.py` and the calling
  route turns it into `HTTPException(404)` — follow this exact convention
  for new single-key lookups (AGENTS.md).
- Route handlers that only do ordinary psycopg calls stay `async def` (the
  existing convention in `routes_jobs.py`/`routes_settings.py`); only
  adapter/Playwright/geocoder calls need `run_in_threadpool`.
- User-supplied free text (job notes) must render safely — Jinja2
  autoescape already covers this; never mark user text `| safe`.
- Schema changes are Alembic migrations under `alembic/versions/`,
  numbered after the latest (`0005_weekly_checkin.py` → `0006_...py`).
- Shared mutable in-memory state (the run-progress dict) needs a
  `threading.Lock`, mirroring `app/web/ratelimit.py`'s accepted
  single-process pattern.
- Tests never make live network calls or launch a real browser outside
  `tests/web/e2e/`.
- `pytest -q`, `ruff check app tests`, and `mypy` must pass before any PR.

## Review Focus

- A run that raises before completing its source loop (e.g. `db.start_run`
  fails) must not leave that user's run-progress entry stuck `running`
  forever — covered in Task 1 with a `finally`-cleanup test.
- Bulk status update must silently skip keys owned by another user (scope
  via SQL, not raise) and report only the count actually changed — covered
  in Task 2.
- Bulk status update must reject >200 keys with 400 and apply nothing —
  covered in Task 2.
- Job notes containing `<script>`/HTML must render escaped on `/jobs`, not
  raw — covered in Task 3.
- The import preview must not write to the database until "Confirm
  import" is submitted, and the existing `?force=1` scripted path must keep
  committing immediately with the same flash messages as before — covered
  in Task 4.

---

## Task 1: Live run-progress feedback (#213)

**Files:**
- Create: `app/run_progress.py`
- Modify: `app/orchestrator.py` (`run_once`)
- Modify: `app/web/routes_dashboard.py` (new `GET /run-status`)
- Modify: `app/web/templates/dashboard.html` (progress label/bar markup)
- Modify: `app/web/static/dashboard.js` (poll `/run-status` while a run is
  active)
- Test: `tests/test_run_progress.py` (new), `tests/test_orchestrator.py`,
  `tests/web/test_dashboard.py`

**Interfaces:**
- Produces (for later tasks / the route layer): `app/run_progress.py`
  exposes `start(user_id: str, total: int) -> None`,
  `update(user_id: str, source_name: str, done: int) -> None`,
  `finish(user_id: str) -> None`, `get(user_id: str) -> dict | None` where
  the dict shape is `{"source": str | None, "done": int, "total": int}`.
  `get` returns `None` when no run is in progress for that user.

- [ ] **Step 1: Write failing unit tests for the progress store**

```python
# tests/test_run_progress.py
from app import run_progress

def test_get_returns_none_when_no_run_started():
    assert run_progress.get("u1") is None

def test_start_then_update_reflects_current_source_and_done_count():
    run_progress.start("u1", total=5)
    run_progress.update("u1", "Acme Corp", done=2)
    assert run_progress.get("u1") == {"source": "Acme Corp", "done": 2, "total": 5}

def test_finish_clears_the_entry():
    run_progress.start("u1", total=5)
    run_progress.finish("u1")
    assert run_progress.get("u1") is None

def test_entries_are_isolated_per_user():
    run_progress.start("u1", total=5)
    run_progress.start("u2", total=9)
    run_progress.update("u1", "Acme", done=1)
    assert run_progress.get("u2") == {"source": None, "done": 0, "total": 9}
```

Add a `teardown`/`autouse` fixture in the same file (`run_progress._progress.clear()`
via a small reset helper, or re-import) so tests don't bleed into each
other — simplest is a private `_reset()` helper exported for tests only, or
an `autouse` fixture that calls `finish` for every id you used. Prefer
adding a tiny `app/run_progress.py` function `_clear_all() -> None` used
only by the test fixture.

- [ ] **Step 2: Run tests, confirm they fail with `ModuleNotFoundError`**

Run: `python -m pytest tests/test_run_progress.py -v`
Expected: FAIL (`app.run_progress` doesn't exist yet)

- [ ] **Step 3: Implement `app/run_progress.py`**

A module-level `dict[str, dict]` guarded by one `threading.Lock`, same shape
as `app/web/ratelimit.py`'s in-memory buckets. `start` sets
`{"source": None, "done": 0, "total": total}`; `update` mutates `source`/`done`
on the existing entry if present (no-op if the user has no entry, so a stray
call after `finish` can't resurrect a stale record); `finish` pops the key;
`get` returns a shallow copy or `None`.

- [ ] **Step 4: Run tests, confirm they pass**

Run: `python -m pytest tests/test_run_progress.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/run_progress.py tests/test_run_progress.py
git commit -m "feat: add in-memory per-user run-progress store (#213)"
```

- [ ] **Step 6: Write failing test for orchestrator progress reporting**

```python
# tests/test_orchestrator.py (add)
def test_run_once_reports_progress_per_source_and_clears_on_success(monkeypatch):
    from app import run_progress
    seen = []
    monkeypatch.setattr(run_progress, "update", lambda uid, name, done: seen.append((uid, name, done)))
    sources = [GreenhouseSource(name="A", type="greenhouse", board_token="a"),
               LeverSource(name="B", type="lever", board_token="b")]
    # fake adapters so no live network call happens; monkeypatch ADAPTERS entries
    ...
    orchestrator.run_once(conn, sources, user_id=owner_id_for(conn))
    assert seen == [(uid, "A", 0), (uid, "B", 1)]
    assert run_progress.get(uid) is None  # cleared when the run finishes


def test_run_once_clears_progress_even_when_a_step_raises(monkeypatch):
    from app import run_progress
    monkeypatch.setattr(db, "finish_run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        orchestrator.run_once(conn, [], user_id=uid)
    assert run_progress.get(uid) is None
```

Use the existing fixtures/fakes in `tests/test_orchestrator.py` (it already
fakes adapters via `ADAPTERS` monkeypatching elsewhere in that file — follow
the established pattern rather than inventing a new one) and
`tests.conftest.owner_id_for`.

- [ ] **Step 7: Run, confirm failure**

Run: `python -m pytest tests/test_orchestrator.py -k progress -v`
Expected: FAIL (no progress calls made yet)

- [ ] **Step 8: Instrument `app/orchestrator.py::run_once`**

Import `run_progress`. At the top of the `with _run_lock:` block, call
`run_progress.start(user_id, total=len(sources))`. Inside the `for source in
sources:` loop, call `run_progress.update(user_id, source.name, done=i)`
using `enumerate(sources)` (so `i` is the number of sources already
completed, 0-indexed, matching the test above). Wrap the existing body of
`run_once` (from after `start_run` through `return RunSummary(...)`) in a
`try`/`finally` where the `finally` calls `run_progress.finish(user_id)`,
so a raise from any step (not just a per-source adapter failure, which is
already caught) still clears the entry.

- [ ] **Step 9: Run, confirm pass**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: PASS, no regressions in the rest of the file

- [ ] **Step 10: Commit**

```bash
git add app/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: report per-source scrape progress from run_once (#213)"
```

- [ ] **Step 11: Write failing route test for `GET /run-status`**

```python
# tests/web/test_dashboard.py (add)
def test_run_status_reports_not_running_by_default(client):
    resp = client.get("/run-status")
    assert resp.status_code == 200
    assert resp.json() == {"running": False}

def test_run_status_reports_in_progress_run(client, admin_user_id):
    from app import run_progress
    run_progress.start(admin_user_id, total=10)
    run_progress.update(admin_user_id, "Acme Corp", done=3)
    resp = client.get("/run-status")
    assert resp.json() == {"running": True, "source": "Acme Corp", "done": 3, "total": 10}
    run_progress.finish(admin_user_id)  # don't leak into other tests

def test_run_status_does_not_see_another_users_progress(member_client, admin_user_id):
    from app import run_progress
    run_progress.start(admin_user_id, total=10)
    resp = member_client.get("/run-status")
    assert resp.json() == {"running": False}
    run_progress.finish(admin_user_id)
```

- [ ] **Step 12: Run, confirm failure (404 — route doesn't exist)**

Run: `python -m pytest tests/web/test_dashboard.py -k run_status -v`
Expected: FAIL

- [ ] **Step 13: Add `GET /run-status` to `app/web/routes_dashboard.py`**

```python
@router.get("/run-status")
def run_status(current_user: dict = Depends(require_user)):
    progress = run_progress.get(current_user["id"])
    if progress is None:
        return {"running": False}
    return {"running": True, **progress}
```

Import `from app import run_progress` at the top of the file alongside the
existing `from app import checker, db`.

- [ ] **Step 14: Run, confirm pass**

Run: `python -m pytest tests/web/test_dashboard.py -v`
Expected: PASS

- [ ] **Step 15: Commit**

```bash
git add app/web/routes_dashboard.py tests/web/test_dashboard.py
git commit -m "feat: add GET /run-status polling endpoint (#213)"
```

- [ ] **Step 16: Add a progress label to the dashboard template**

In `app/web/templates/dashboard.html`, inside `.history-toolbar` next to
`#run-now-status`, add `<span id="run-progress-label" class="muted"
aria-live="polite"></span>` (not `sr-only` — this one is meant to be
visible while a run is active; empty text renders nothing).

- [ ] **Step 17: Write a failing e2e-free JS-behavior check via an existing
  `tests/web/test_dashboard.py` static assertion**

```python
def test_dashboard_has_run_progress_label(client):
    resp = client.get("/")
    assert 'id="run-progress-label"' in resp.text
```

(This is the cheapest meaningful test for server-rendered markup; the
polling *behavior* itself is JS and is exercised manually/visually per
AGENTS.md's e2e guidance — no new Playwright test is required for a pure
polling-text update, consistent with how `dashboard.js`'s existing
`managePolling()` has no e2e test today.)

- [ ] **Step 18: Run, confirm fail then implement, confirm pass**

Run: `python -m pytest tests/web/test_dashboard.py -k progress_label -v`

- [ ] **Step 19: Wire polling into `app/web/static/dashboard.js`**

Add a `pollProgress()` that `fetch("/run-status")`s, and when
`body.running` is true sets `runProgressLabel.textContent =
"Scraping " + body.source + "… (" + body.done + "/" + body.total + ")"`
else clears it. Call it on an interval (reuse the existing `POLL_MS`
constant) started right after the `run-now` form's `fetch(...)` resolves,
and stopped (via the same `pollTimer`/`managePolling()` mechanism already
present) once `/run-status` reports `running: false` — piggyback on the
existing `managePolling()` function by also calling `pollProgress()` from
inside it, guarded by `document.getElementById("run-progress-label")`
being non-null (so this file keeps working unmodified on pages that don't
include the dashboard toolbar, per its existing `if (!container) return;`
guard).

- [ ] **Step 20: Manually verify** (no automated JS test exists for this
  file today — follow that precedent): run the app locally
  (`uvicorn app.web.main:app --reload`), click "Run now" with at least one
  slow source configured, and confirm the label updates and clears.

- [ ] **Step 21: Commit**

```bash
git add app/web/templates/dashboard.html app/web/static/dashboard.js
git commit -m "feat: show live scrape progress on the dashboard (#213)"
```

---

## Task 2: Bulk job status update (#222)

**Files:**
- Modify: `app/db.py` (new `bulk_set_status`)
- Modify: `app/web/routes_jobs.py` (new `POST /jobs/bulk-status`)
- Modify: `app/web/templates/jobs.html` (checkbox column + bulk toolbar)
- Test: `tests/test_db.py`, `tests/web/test_jobs.py`,
  `tests/test_tenant_isolation_db.py`

**Interfaces:**
- Produces: `app/db.py::bulk_set_status(conn: psycopg.Connection, user_id:
  str, keys: list[str], status: str | None) -> int` — returns the number
  of rows actually updated (keys not owned by `user_id` are silently
  excluded, not errored).

- [ ] **Step 1: Write failing db-level tests**

```python
# tests/test_db.py (add near test(s) for set_job_status)
def test_bulk_set_status_updates_all_given_keys(pg_conn):
    uid = owner_id_for(pg_conn)
    for k in ("k1", "k2", "k3"):
        db.save_jobs(pg_conn, [make_job(key=k)], db.start_run(pg_conn), user_id=uid)
    count = db.bulk_set_status(pg_conn, uid, ["k1", "k2"], "applied")
    assert count == 2
    rows = {r["key"]: r["status"] for r in db.list_jobs(pg_conn)}
    assert rows["k1"] == "applied" and rows["k2"] == "applied" and rows["k3"] is None

def test_bulk_set_status_can_clear_status(pg_conn):
    uid = owner_id_for(pg_conn)
    db.save_jobs(pg_conn, [make_job(key="k1")], db.start_run(pg_conn), user_id=uid)
    db.set_job_status(pg_conn, uid, "k1", "applied")
    count = db.bulk_set_status(pg_conn, uid, ["k1"], None)
    assert count == 1
    assert db.list_jobs(pg_conn)[0]["status"] is None

def test_bulk_set_status_records_history_for_each_updated_key(pg_conn):
    uid = owner_id_for(pg_conn)
    db.save_jobs(pg_conn, [make_job(key="k1")], db.start_run(pg_conn), user_id=uid)
    db.bulk_set_status(pg_conn, uid, ["k1"], "ignored")
    history = db.get_job_status_history(pg_conn, [(uid, "k1")])
    assert history[(uid, "k1")][0]["status"] == "ignored"

def test_bulk_set_status_ignores_empty_key_list(pg_conn):
    uid = owner_id_for(pg_conn)
    assert db.bulk_set_status(pg_conn, uid, [], "applied") == 0
```

Reuse the `make_job` helper already defined at module scope in
`tests/test_db.py` (follow whatever existing helper that file uses for
`set_job_status` tests — match its name/signature rather than
reintroducing a second one).

- [ ] **Step 2: Run, confirm `AttributeError: module 'app.db' has no
  attribute 'bulk_set_status'`**

Run: `python -m pytest tests/test_db.py -k bulk_set_status -v`

- [ ] **Step 3: Implement `bulk_set_status` in `app/db.py`**, placed right
  after `set_job_status`. Use `UPDATE jobs SET status = %s WHERE user_id =
  %s AND key = ANY(%s) RETURNING key` to get back exactly which keys were
  touched (empty `keys` short-circuits to `0` without a query), then insert
  one `job_status_history` row per returned key (same `INSERT INTO
  job_status_history ...` as `set_job_status`, via `executemany`), then
  `conn.commit()` once, returning `len(updated_keys)`.

- [ ] **Step 4: Run, confirm pass**

Run: `python -m pytest tests/test_db.py -k bulk_set_status -v`

- [ ] **Step 5: Add the non-owner case to the existing parametrized
  isolation test** in `tests/test_tenant_isolation_db.py` — add
  `lambda conn, uid: db.bulk_set_status(conn, uid, [KEY], "applied")` to the
  `mutate` parametrize list, but note `bulk_set_status` does **not** raise
  `KeyError` (it returns `0`); write it as its own test next to that
  parametrized block instead of inside it:

```python
def test_bulk_set_status_by_a_non_owner_updates_nothing(pg_conn, two_users):
    alice, bob = two_users
    _save(pg_conn, alice)
    count = db.bulk_set_status(pg_conn, bob, [KEY], "applied")
    assert count == 0
    row = pg_conn.execute(
        "SELECT status FROM jobs WHERE user_id = %s AND key = %s", (alice, KEY),
    ).fetchone()
    assert row == (None,)

def test_bulk_set_status_with_mixed_ownership_only_updates_owned_keys(pg_conn, two_users):
    alice, bob = two_users
    _save(pg_conn, alice, _job(key="shared", source_id="a"))
    _save(pg_conn, bob, _job(key="shared", source_id="b"))
    count = db.bulk_set_status(pg_conn, alice, ["shared"], "applied")
    assert count == 1
    alice_status = pg_conn.execute(
        "SELECT status FROM jobs WHERE user_id = %s AND key = 'shared'", (alice,),
    ).fetchone()[0]
    bob_status = pg_conn.execute(
        "SELECT status FROM jobs WHERE user_id = %s AND key = 'shared'", (bob,),
    ).fetchone()[0]
    assert alice_status == "applied"
    assert bob_status is None
```

- [ ] **Step 6: Run, confirm pass; commit**

Run: `python -m pytest tests/test_db.py tests/test_tenant_isolation_db.py -v`

```bash
git add app/db.py tests/test_db.py tests/test_tenant_isolation_db.py
git commit -m "feat: add db.bulk_set_status for multi-job status updates (#222)"
```

- [ ] **Step 7: Write failing route tests**

```python
# tests/web/test_jobs.py (add)
def test_post_bulk_status_updates_selected_jobs_and_flashes_count(client):
    conn = client.app.state.conn
    uid = owner_id_for(conn)
    for k in ("k1", "k2"):
        db.save_jobs(conn, [make_job(key=k)], db.start_run(conn), user_id=uid)
    resp = client.post("/jobs/bulk-status", data={"keys": ["k1", "k2"], "status": "applied"}, follow_redirects=False)
    assert resp.status_code == 303
    location = urlparse(resp.headers["location"])
    assert location.path == "/jobs"
    assert parse_qs(location.query)["flash"] == ["Updated 2 job(s)."]
    rows = {r["key"]: r["status"] for r in db.list_jobs(conn)}
    assert rows == {"k1": "applied", "k2": "applied"}

def test_post_bulk_status_rejects_invalid_status(client):
    resp = client.post("/jobs/bulk-status", data={"keys": ["k1"], "status": "bogus"})
    assert resp.status_code == 400

def test_post_bulk_status_rejects_more_than_200_keys(client):
    keys = [f"k{i}" for i in range(201)]
    resp = client.post("/jobs/bulk-status", data={"keys": keys, "status": "applied"})
    assert resp.status_code == 400

def test_post_bulk_status_with_no_keys_flashes_zero(client):
    resp = client.post("/jobs/bulk-status", data={"keys": [], "status": "applied"}, follow_redirects=False)
    assert parse_qs(urlparse(resp.headers["location"]).query)["flash"] == ["Updated 0 job(s)."]

def test_post_bulk_status_only_updates_the_callers_own_jobs(client, member_user_id_for_admin):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="mine")], db.start_run(conn), user_id=owner_id_for(conn))
    db.save_jobs(conn, [make_job(key="theirs", source_id="s2")], db.start_run(conn), user_id=member_user_id_for_admin)
    client.post("/jobs/bulk-status", data={"keys": ["mine", "theirs"], "status": "applied"})
    rows = {r["user_id"]: r["status"] for r in db.list_jobs(conn)}
    theirs_status = [r["status"] for r in db.list_jobs(conn) if r["key"] == "theirs"][0]
    assert theirs_status is None
```

- [ ] **Step 8: Run, confirm 404s / failures**

Run: `python -m pytest tests/web/test_jobs.py -k bulk_status -v`

- [ ] **Step 9: Implement `POST /jobs/bulk-status` in
  `app/web/routes_jobs.py`**, placed after `update_job_status`:

```python
@router.post("/jobs/bulk-status")
async def bulk_update_job_status(request: Request, current_user: dict = Depends(require_user)):
    form = await request.form()
    keys = _str_list_field(form, "keys")  # reuse the helper pattern from routes_settings.py, or inline via form.getlist
    status = _form_str(form, "status") or None
    if status is not None and status not in STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if len(keys) > 200:
        raise HTTPException(status_code=400, detail="Too many jobs selected (max 200).")
    with request.app.state.pool.connection() as conn:
        count = db.bulk_set_status(conn, current_user["id"], keys, status)
    return flash_redirect("/jobs", f"Updated {count} job(s).")
```

`routes_jobs.py` doesn't currently have a `_str_list_field` helper (that
one lives in `routes_settings.py`) — add a small local one (`form.getlist
("keys")`, no type assertion needed since checkbox values are always
strings) rather than importing across route modules.

- [ ] **Step 10: Run, confirm pass**

Run: `python -m pytest tests/web/test_jobs.py -v`
Expected: PASS, no regressions

- [ ] **Step 11: Commit**

```bash
git add app/web/routes_jobs.py tests/web/test_jobs.py
git commit -m "feat: add POST /jobs/bulk-status endpoint (#222)"
```

- [ ] **Step 12: Add the checkbox column and bulk toolbar to
  `app/web/templates/jobs.html`**

Add a `<th>` with a "select all on page" checkbox (`id="select-all-jobs"`)
as the first header cell, and a per-row `<td>` with `<input type="checkbox"
name="keys" value="{{ job.key }}" class="job-select" {% if job.user_id !=
current_user_id %}disabled{% endif %}>` as the first data cell (disabled —
not just hidden — for jobs the viewer doesn't own, consistent with how
other owner-only controls in this template are conditionally rendered).
Add a toolbar `<form method="post" action="/jobs/bulk-status"
id="bulk-status-form" hidden>` containing a live count span
(`#bulk-selected-count`), a `<select name="status">` built from the same
`statuses` dict already in context (plus a blank "Clear status" option),
and an "Apply to selected" submit button. Add the new JS block (inside the
existing page-local `<script>` IIFE, following the file's existing style)
that: toggles the toolbar's `hidden` attribute and updates the count
whenever any `.job-select` changes; wires `#select-all-jobs` to check/
uncheck every non-disabled `.job-select` on the page; and, before the
bulk form submits, appends one hidden `<input name="keys" value="...">`
per checked box (or relies on the checkboxes themselves being inside the
form — simpler: move the checkboxes' `name="keys"` submission by nesting
each row's checkbox *inside* `#bulk-status-form` via the HTML5 `form`
attribute: `<input type="checkbox" name="keys" value="{{ job.key }}"
form="bulk-status-form" class="job-select" ...>`, which lets the checkboxes
live in the table while submitting through the toolbar form with no JS
data-copying needed).

- [ ] **Step 13: Add/extend a template-markup test**

```python
def test_jobs_page_shows_bulk_status_toolbar_markup(client):
    resp = client.get("/jobs")
    assert 'id="bulk-status-form"' in resp.text
    assert 'id="select-all-jobs"' in resp.text

def test_jobs_page_checkbox_disabled_for_jobs_not_owned_by_viewer(client, member_user_id_for_admin):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="theirs", source_id="s2")], db.start_run(conn), user_id=member_user_id_for_admin)
    resp = client.get("/jobs?user=" + member_user_id_for_admin)  # admin viewing another user's jobs
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    cb = soup.select_one('input.job-select[value="theirs"]')
    assert cb is not None and cb.has_attr("disabled")
```

- [ ] **Step 14: Run, confirm pass; manually verify in the browser**

Run: `python -m pytest tests/web/test_jobs.py -v`
Then run the app locally, select a few rows on `/jobs`, apply a status,
and confirm the toolbar hides again and the page reflects the change after
redirect.

- [ ] **Step 15: Commit**

```bash
git add app/web/templates/jobs.html tests/web/test_jobs.py
git commit -m "feat: add bulk job-status toolbar to /jobs (#222)"
```

---

## Task 3: Per-job notes field (#220)

**Files:**
- Create: `alembic/versions/0006_job_notes.py`
- Modify: `app/db.py` (`list_jobs` SELECT + result dict, new
  `set_job_notes`)
- Modify: `app/web/routes_jobs.py` (new `POST /jobs/notes`)
- Modify: `app/web/templates/jobs.html` (Notes column, edit-icon button,
  modal, JS wiring — mirror the `duplicate-modal` pattern exactly)
- Test: `tests/test_migrations.py` (if it enumerates columns — check first;
  otherwise skip), `tests/test_db.py`, `tests/web/test_jobs.py`,
  `tests/test_tenant_isolation_db.py`

**Interfaces:**
- Produces: `app/db.py::set_job_notes(conn: psycopg.Connection, user_id:
  str, key: str, notes: str) -> None` — raises `KeyError(key)` on a miss,
  identical convention to `set_job_status`. `list_jobs` rows gain a
  `"notes"` key (`str | None`).

- [ ] **Step 1: Write the migration**

```python
# alembic/versions/0006_job_notes.py
"""add notes to jobs

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('notes', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'notes')
```

- [ ] **Step 2: Run the migration test suite**

Run: `python -m pytest tests/test_migrations.py -v`
Expected: PASS (it exercises upgrade/downgrade generically; confirm it
doesn't need a per-column update — read the file first; if it enumerates
every column explicitly, add `notes` there too)

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/0006_job_notes.py
git commit -m "feat: add jobs.notes column (#220)"
```

- [ ] **Step 4: Write failing db-level tests**

```python
# tests/test_db.py (add)
def test_set_job_notes_stores_text(pg_conn):
    uid = owner_id_for(pg_conn)
    db.save_jobs(pg_conn, [make_job(key="k1")], db.start_run(pg_conn), user_id=uid)
    db.set_job_notes(pg_conn, uid, "k1", "interviewed 2026-10-05")
    rows = {r["key"]: r["notes"] for r in db.list_jobs(pg_conn)}
    assert rows["k1"] == "interviewed 2026-10-05"

def test_set_job_notes_can_clear_to_empty_string(pg_conn):
    uid = owner_id_for(pg_conn)
    db.save_jobs(pg_conn, [make_job(key="k1")], db.start_run(pg_conn), user_id=uid)
    db.set_job_notes(pg_conn, uid, "k1", "something")
    db.set_job_notes(pg_conn, uid, "k1", "")
    rows = {r["key"]: r["notes"] for r in db.list_jobs(pg_conn)}
    assert rows["k1"] == ""

def test_set_job_notes_unknown_key_raises_keyerror(pg_conn):
    with pytest.raises(KeyError):
        db.set_job_notes(pg_conn, owner_id_for(pg_conn), "nope", "x")

def test_list_jobs_defaults_notes_to_none(pg_conn):
    uid = owner_id_for(pg_conn)
    db.save_jobs(pg_conn, [make_job(key="k1")], db.start_run(pg_conn), user_id=uid)
    assert db.list_jobs(pg_conn)[0]["notes"] is None
```

- [ ] **Step 5: Run, confirm failure**

Run: `python -m pytest tests/test_db.py -k job_notes -v`

- [ ] **Step 6: Implement.** Add `jobs.notes` to `list_jobs`'s `SELECT`
  column list and its result-dict construction (append at the end so
  existing positional-index unpacking elsewhere is undisturbed). Add
  `set_job_notes` right after `set_job_duplicate`/`clear_job_duplicate`,
  same shape as `set_job_status` minus the history insert:

```python
def set_job_notes(conn: psycopg.Connection, user_id: str, key: str, notes: str) -> None:
    cur = conn.execute(
        "UPDATE jobs SET notes = %s WHERE user_id = %s AND key = %s", (notes, user_id, key),
    )
    if cur.rowcount == 0:
        raise KeyError(key)
    conn.commit()
```

- [ ] **Step 7: Run, confirm pass**

Run: `python -m pytest tests/test_db.py -v`
Expected: PASS, no regressions (check other `list_jobs` consumers/tests
that assert on the full result dict shape, e.g. anything that does
`assert row == {...}` rather than checking individual keys, and update
them to include `"notes": None`)

- [ ] **Step 8: Add the non-owner case**

```python
# tests/test_tenant_isolation_db.py — add to the existing parametrize list:
lambda conn, uid: db.set_job_notes(conn, uid, KEY, "x"),
# ids=[..., "notes"]
```

Also add a dedicated assertion (the shared parametrized test's final SELECT
only checks `status, removed_at, is_duplicate`, which doesn't prove notes
stayed clear) right after it:

```python
def test_set_job_notes_by_a_non_owner_raises_and_leaves_notes_unset(pg_conn, two_users):
    alice, bob = two_users
    _save(pg_conn, alice)
    with pytest.raises(KeyError):
        db.set_job_notes(pg_conn, bob, KEY, "x")
    notes = pg_conn.execute(
        "SELECT notes FROM jobs WHERE user_id = %s AND key = %s", (alice, KEY),
    ).fetchone()[0]
    assert notes is None
```

- [ ] **Step 9: Run, confirm pass; commit**

Run: `python -m pytest tests/test_db.py tests/test_tenant_isolation_db.py -v`

```bash
git add app/db.py tests/test_db.py tests/test_tenant_isolation_db.py
git commit -m "feat: add db.set_job_notes and include notes in list_jobs (#220)"
```

- [ ] **Step 10: Write failing route tests**

```python
# tests/web/test_jobs.py (add)
def test_post_job_notes_saves_and_redirects_with_flash(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn), user_id=owner_id_for(conn))
    resp = client.post("/jobs/notes", data={"key": "k1", "notes": "called recruiter"}, follow_redirects=False)
    assert resp.status_code == 303
    assert db.list_jobs(conn)[0]["notes"] == "called recruiter"

def test_post_job_notes_json_path_returns_ok(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn), user_id=owner_id_for(conn))
    resp = client.post("/jobs/notes", data={"key": "k1", "notes": "x"}, headers={"Accept": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

def test_post_job_notes_unknown_key_returns_404(client):
    resp = client.post("/jobs/notes", data={"key": "nope", "notes": "x"})
    assert resp.status_code == 404

def test_post_job_notes_missing_key_returns_400(client):
    resp = client.post("/jobs/notes", data={"notes": "x"})
    assert resp.status_code == 400

def test_jobs_page_escapes_html_in_notes(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn), user_id=owner_id_for(conn))
    db.set_job_notes(conn, owner_id_for(conn), "k1", "<script>alert(1)</script>")
    resp = client.get("/jobs")
    assert "<script>alert(1)</script>" not in resp.text
    assert "&lt;script&gt;" in resp.text
```

- [ ] **Step 11: Run, confirm failure**

Run: `python -m pytest tests/web/test_jobs.py -k job_notes -v`

- [ ] **Step 12: Implement `POST /jobs/notes`** in `routes_jobs.py`, after
  `update_location_override`, mirroring `update_job_status`'s dual
  JSON/redirect response:

```python
@router.post("/jobs/notes")
async def update_job_notes(request: Request, current_user: dict = Depends(require_user)):
    form = dict((await request.form()).items())
    key = _form_str(form, "key")
    if not key:
        raise HTTPException(status_code=400, detail="Missing job key")
    notes = _form_str(form, "notes")
    try:
        with request.app.state.pool.connection() as conn:
            db.set_job_notes(conn, current_user["id"], key, notes)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    if _wants_json(request):
        return JSONResponse({"ok": True, "message": "Notes saved.", "notes": notes})
    return flash_redirect("/jobs", "Notes saved.")
```

- [ ] **Step 13: Run, confirm pass**

Run: `python -m pytest tests/web/test_jobs.py -v`

- [ ] **Step 14: Commit**

```bash
git add app/web/routes_jobs.py tests/web/test_jobs.py
git commit -m "feat: add POST /jobs/notes endpoint (#220)"
```

- [ ] **Step 15: Add the Notes column, edit button, and modal to
  `app/web/templates/jobs.html`**

Add a `<th scope="col">Notes</th>` after the Summary header, and a matching
`<td data-label="Notes">` showing `{{ job.notes[:60] ~ "…" if job.notes and
job.notes|length > 60 else (job.notes or "—") }}` plus — only when
`job.user_id == current_user_id` — a `notes-btn icon-btn` button with
`data-key`, `data-title`, and `data-notes` attributes, mirroring the
`duplicate-btn` markup exactly. Add a `<dialog id="notes-modal" ...>` with
a `<textarea id="notes-input" name="notes">` and Save/Cancel buttons,
structurally identical to `#duplicate-modal`. Add the JS block (same IIFE,
same `postJson` helper already defined) wiring `.notes-btn` clicks to open
the modal pre-filled, submit via `postJson("/jobs/notes", ...)`, and update
the row's Notes cell text (truncated the same way) and the button's
`data-notes` on success.

- [ ] **Step 16: Add a markup test and run everything**

```python
def test_jobs_page_shows_notes_column_and_edit_button(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn), user_id=owner_id_for(conn))
    resp = client.get("/jobs")
    assert 'id="notes-modal"' in resp.text
    assert 'class="notes-btn icon-btn"' in resp.text
```

Run: `python -m pytest tests/web/test_jobs.py -v`
Then run the app locally and exercise the modal manually (open, type,
save, reload, confirm persisted and truncated display works).

- [ ] **Step 17: Commit**

```bash
git add app/web/templates/jobs.html tests/web/test_jobs.py
git commit -m "feat: add per-job notes modal to /jobs (#220)"
```

---

## Task 4: Settings-import diff/preview (#221)

**Files:**
- Modify: `app/config.py` (new `diff_import`)
- Modify: `app/web/routes_settings.py` (`import_settings` becomes
  preview-then-confirm; keep `?force=1` as the immediate-commit escape
  hatch)
- Modify: `app/web/templates/settings_data.html` (diff display, confirm
  form, cancel link; drop the now-redundant blind `data-confirm-*` guard
  on the upload form)
- Test: `tests/test_config.py` (unit tests for `diff_import`),
  `tests/web/test_settings.py` (update ~10 existing import tests to pass
  `force=1`; add new preview/confirm tests)

**Interfaces:**
- Produces: `app/config.py::diff_import(existing: list[SourceConfig], new:
  list[SourceConfig]) -> dict` returning `{"added": list[SourceConfig],
  "updated": list[tuple[SourceConfig, SourceConfig]]` (old, new pairs),
  `"unchanged": list[SourceConfig]}`, matched by `.id`. (No `"removed"`
  key: `db.import_sources` only ever upserts, it never deletes a source
  missing from the file, so a `"removed"` section would promise a deletion
  that will not happen — this plan deliberately omits it rather than
  implement the issue's conditional "only if full-replace" branch, since
  the backend has no full-replace mode to match it to.)

- [ ] **Step 1: Write failing unit tests for `diff_import`**

```python
# tests/test_config.py (add)
from app.config import LeverSource, GreenhouseSource, diff_import

def test_diff_import_new_id_is_added():
    new = [LeverSource(id="n1", name="New", type="lever", board_token="n")]
    result = diff_import([], new)
    assert [s.id for s in result["added"]] == ["n1"]
    assert result["updated"] == []
    assert result["unchanged"] == []

def test_diff_import_same_id_same_content_is_unchanged():
    s = GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    result = diff_import([s], [s.model_copy()])
    assert [x.id for x in result["unchanged"]] == ["s1"]
    assert result["added"] == result["updated"] == []

def test_diff_import_same_id_different_content_is_updated():
    old = GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    new = old.model_copy(update={"name": "Acme Renamed"})
    result = diff_import([old], [new])
    assert len(result["updated"]) == 1
    got_old, got_new = result["updated"][0]
    assert got_old.name == "Acme" and got_new.name == "Acme Renamed"

def test_diff_import_existing_source_missing_from_file_is_not_reported():
    old = GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    result = diff_import([old], [])
    assert result == {"added": [], "updated": [], "unchanged": []}
```

- [ ] **Step 2: Run, confirm `ImportError`**

Run: `python -m pytest tests/test_config.py -k diff_import -v`

- [ ] **Step 3: Implement `diff_import` in `app/config.py`**, placed after
  `SourcesFile`:

```python
def diff_import(existing: list, new: list) -> dict:
    existing_by_id = {s.id: s for s in existing}
    added, updated, unchanged = [], [], []
    for source in new:
        old = existing_by_id.get(source.id)
        if old is None:
            added.append(source)
        elif old.model_dump() == source.model_dump():
            unchanged.append(source)
        else:
            updated.append((old, source))
    return {"added": added, "updated": updated, "unchanged": unchanged}
```

- [ ] **Step 4: Run, confirm pass; commit**

Run: `python -m pytest tests/test_config.py -v`

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add diff_import helper for settings-import preview (#221)"
```

- [ ] **Step 5: Update the ~10 existing `/settings/data/import` tests in
  `tests/web/test_settings.py` to keep testing the commit path**

Every existing test that does
`client.post("/settings/data/import", files={"file": (...)}, ...)` and
asserts an immediate flash/DB write (search for
`test_post_import_settings_*` and `test_post_import_settings_with_*`) must
add `data={"force": "1"}` to its `client.post(...)` call so it keeps
exercising the immediate-commit path. Do this for every one of them now,
run the suite, and confirm they still fail (no `force` handling exists
yet) before implementing — this *is* the red step for the escape hatch.

Run: `python -m pytest tests/web/test_settings.py -k import -v`
Expected: FAIL (these tests currently pass against old behavior; after
adding `force=1` to each `client.post(...)` they should still assert the
exact same outcomes once Step 6 is implemented — right now, before Step 6,
either they still pass by coincidence of old code ignoring the extra form
field, or fail; note which, since `force=1` is a no-op against the
*current* handler and these tests are expected to keep passing unmodified
until the default behavior changes under them)

- [ ] **Step 6: Rewrite `import_settings` in `app/web/routes_settings.py`**

```python
@router.post("/settings/data/import")
async def import_settings(request: Request, current_user: dict = Depends(require_user)):
    form = await request.form()
    force = request.query_params.get("force") == "1"
    confirmed = form.get("confirmed") == "1"

    if confirmed:
        raw = (form.get("sources_json") or "").encode("utf-8")
    else:
        upload = form.get("file")
        if not isinstance(upload, UploadFile) or not upload.filename:
            return templates.TemplateResponse(
                request, "settings_data.html", {"error": "Choose a file to import."}, status_code=400,
            )
        raw = await upload.read()
        if len(raw) > _IMPORT_MAX_BYTES:
            return templates.TemplateResponse(
                request, "settings_data.html",
                {"error": "Import file is too large (max 1 MB)."}, status_code=413,
            )

    try:
        data = json.loads(raw)
        sources = SourcesFile.model_validate(data).sources
    except json.JSONDecodeError as exc:
        return templates.TemplateResponse(
            request, "settings_data.html", {"error": f"Import failed: {exc}"}, status_code=400,
        )
    except ValidationError as exc:
        return templates.TemplateResponse(
            request, "settings_data.html",
            {"error": f"Import failed: {fmt_validation_error(exc)}"}, status_code=400,
        )

    parsed_preferences = _parse_preferences_import(data)

    if not force and not confirmed:
        with request.app.state.pool.connection() as conn:
            existing_sources = db.list_sources(conn, current_user["id"])
            existing_settings = db.get_settings(conn, current_user["id"])
        diff = diff_import(existing_sources, sources)
        pref_diff = _preference_diff(existing_settings, parsed_preferences)
        return templates.TemplateResponse(request, "settings_data.html", {
            "preview": {
                "diff": diff, "pref_diff": pref_diff,
                "sources_json": raw.decode("utf-8"),
                "added_count": len(diff["added"]), "updated_count": len(diff["updated"]),
                "unchanged_count": len(diff["unchanged"]),
            },
        })

    with request.app.state.pool.connection() as conn:
        count = db.import_sources(conn, current_user["id"], sources)
        if parsed_preferences is not None:
            (email_days, resend_jobs, email_to, hide_not_interested_on_map, digest_max,
             digest_excl, send_weekly_checkin) = parsed_preferences
            db.save_preferences(
                conn, current_user["id"], email_days, resend_jobs, email_to, hide_not_interested_on_map,
                digest_max_per_company=digest_max, digest_exclude_statuses=digest_excl,
                send_weekly_checkin=send_weekly_checkin,
            )
    redirect_message = f"Imported {count} source(s)."
    if parsed_preferences is not None:
        redirect_message = f"Imported {count} source(s) and preferences."
    return flash_redirect("/settings/data", redirect_message)
```

Add a small private helper right above it:

```python
_PREFERENCE_LABELS = {
    "email_days": "Check days", "resend_jobs": "Resend jobs",
    "email_to": "Digest recipients", "hide_not_interested_on_map": "Hide Not Interested on map",
    "digest_max_per_company": "Max jobs per company", "digest_exclude_statuses": "Excluded statuses",
    "send_weekly_checkin": "Weekly check-in email",
}

def _preference_diff(existing_settings, parsed) -> list[dict]:
    if parsed is None:
        return []
    email_days, resend_jobs, email_to, hide_not_interested_on_map, digest_max, digest_excl, send_weekly_checkin = parsed
    new = {
        "email_days": email_days, "resend_jobs": resend_jobs, "email_to": email_to,
        "hide_not_interested_on_map": hide_not_interested_on_map,
        "digest_max_per_company": digest_max, "digest_exclude_statuses": digest_excl,
        "send_weekly_checkin": send_weekly_checkin,
    }
    old = existing_settings or {}
    changes = []
    for key, label in _PREFERENCE_LABELS.items():
        old_value = old.get(key) if existing_settings is not None else None
        if old_value != new[key]:
            changes.append({"label": label, "old": old_value, "new": new[key]})
    return changes
```

- [ ] **Step 7: Run the migrated existing tests, confirm pass (force path)**

Run: `python -m pytest tests/web/test_settings.py -k import -v`
Expected: PASS — every test now passes `force=1` and the handler commits
immediately exactly as before, same flash messages, same DB writes.

- [ ] **Step 8: Write failing tests for the new preview/confirm flow**

```python
def test_post_import_without_force_shows_preview_and_does_not_write(client, admin_user_id):
    import json
    payload = json.dumps({"sources": [{"id": "new", "name": "New", "type": "lever", "board_token": "new"}]}).encode()
    resp = client.post("/settings/data/import", files={"file": ("settings.json", payload, "application/json")})
    assert resp.status_code == 200
    assert "New" in resp.text
    assert "Added" in resp.text
    with client.app.state.pool.connection() as conn:
        assert db.list_sources(conn, admin_user_id) == []  # nothing written yet

def test_post_import_confirm_step_writes_the_previewed_sources(client, admin_user_id):
    import json
    payload = json.dumps({"sources": [{"id": "new", "name": "New", "type": "lever", "board_token": "new"}]}).encode()
    preview = client.post("/settings/data/import", files={"file": ("settings.json", payload, "application/json")})
    resp = client.post(
        "/settings/data/import",
        data={"confirmed": "1", "sources_json": payload.decode()},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    with client.app.state.pool.connection() as conn:
        assert [s.id for s in db.list_sources(conn, admin_user_id)] == ["new"]

def test_post_import_preview_shows_updated_and_unchanged_sources(client, admin_user_id):
    import json
    from app import config
    existing = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    with client.app.state.pool.connection() as conn:
        db.add_source(conn, admin_user_id, existing)
    payload = json.dumps({"sources": [
        {"id": "s1", "name": "Acme Renamed", "type": "greenhouse", "board_token": "acme"},
    ]}).encode()
    resp = client.post("/settings/data/import", files={"file": ("settings.json", payload, "application/json")})
    assert "Acme Renamed" in resp.text
    assert "Updated" in resp.text

def test_post_import_preview_shows_preference_changes(client, admin_user_id):
    import json
    payload = json.dumps({"sources": [], "preferences": {"email_days": ["tue"], "resend_jobs": True, "email_to": ["new@x.test"]}}).encode()
    resp = client.post("/settings/data/import", files={"file": ("settings.json", payload, "application/json")})
    assert "new@x.test" in resp.text

def test_post_import_invalid_json_still_errors_at_preview_time(client):
    resp = client.post("/settings/data/import", files={"file": ("settings.json", b"not json", "application/json")})
    assert resp.status_code == 400
```

- [ ] **Step 9: Run, confirm failure, then confirm pass against Step 6's
  implementation**

Run: `python -m pytest tests/web/test_settings.py -k "preview or confirm" -v`

- [ ] **Step 10: Update
  `test_settings_data_import_form_has_confirm_guard`** (around line 653)
  — the blind JS confirm on the upload form is superseded by the diff
  preview itself; change the test to assert the guard is gone from the
  *upload* form (`import_form.get("data-confirm-title") is None`) rather
  than present, and rename it to
  `test_settings_data_import_form_has_no_blind_confirm_guard` (the diff
  preview page is the real confirmation step now).

- [ ] **Step 11: Update `app/web/templates/settings_data.html`**

Remove `data-confirm-title`/`data-confirm-message` from `#import-form`.
After the existing import `<form>` block, add:

```jinja
{% if preview %}
<div class="card">
  <h2>Review import</h2>
  <p>{{ preview.added_count }} to add, {{ preview.updated_count }} to update,
     {{ preview.unchanged_count }} unchanged.</p>
  {% if preview.diff.added %}
  <h3>Added</h3>
  <ul>{% for s in preview.diff.added %}<li>{{ s.name }}</li>{% endfor %}</ul>
  {% endif %}
  {% if preview.diff.updated %}
  <h3>Updated</h3>
  <ul>{% for old, new in preview.diff.updated %}<li>{{ old.name }} &rarr; {{ new.name }}</li>{% endfor %}</ul>
  {% endif %}
  {% if preview.pref_diff %}
  <h3>Preference changes</h3>
  <ul>{% for c in preview.pref_diff %}<li>{{ c.label }}: {{ c.old }} &rarr; {{ c.new }}</li>{% endfor %}</ul>
  {% endif %}
  <form method="post" action="/settings/data/import">
    <input type="hidden" name="confirmed" value="1">
    <input type="hidden" name="sources_json" value="{{ preview.sources_json }}">
    <button type="submit" class="btn-primary">Confirm import</button>
    <a href="/settings/data">Cancel</a>
  </form>
</div>
{% endif %}
```

(Jinja2 autoescapes the hidden `value` attribute, so embedding the raw
JSON text is safe without manual escaping.)

- [ ] **Step 12: Run the full settings test file, confirm all pass**

Run: `python -m pytest tests/web/test_settings.py -v`

- [ ] **Step 13: Commit**

```bash
git add app/web/routes_settings.py app/web/templates/settings_data.html tests/web/test_settings.py
git commit -m "feat: show a diff preview before committing a settings import (#221)"
```

---

## Task 5: Docs, version bump, and issue cross-linking

**Files:**
- Modify: `pyproject.toml` (`version`)
- Modify: `CHANGELOG.md`
- Modify: `docs/issue-tiers.md`
- Modify: `app/web/templates/base.html` or wherever `app_version` originates
  if it needs no change (verify only)

**Interfaces:** none (docs/version only).

- [ ] **Step 1: Bump `pyproject.toml`'s `version` to `2.0.0`** (per
  explicit instruction — a major bump marking this feature batch, not
  semver-driven by breaking changes).

- [ ] **Step 2: Add a `## [2.0.0] — 2026-10-23` entry to `CHANGELOG.md`**
  under `## [Unreleased]`, with an `### Added` section listing all four
  issues with links, one bullet each, in the same style as the existing
  `## [1.14.0]`/`## [1.13.0]` entries (feature name, issue link, one or two
  sentences on behavior and any notable trade-off — e.g. #221's note that
  import never deletes sources missing from the file, so no "removed"
  section exists in the diff).

- [ ] **Step 3: Update `docs/issue-tiers.md`** — remove the rows for
  #213, #220, #221, #222 from the "Open" table (they're now closed), and
  bump the "Last reviewed" date and the referenced version in the header.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml CHANGELOG.md docs/issue-tiers.md
git commit -m "chore: v2.0.0 — close #213, #220, #221, #222"
```

---

## Task 6: Whole-branch verification

- [ ] **Step 1: Run the full non-e2e suite**

Run: `python -m pytest -q --ignore=tests/web/e2e`
Expected: all green

- [ ] **Step 2: Run `ruff check app tests`**

Expected: no findings

- [ ] **Step 3: Run `mypy`**

Expected: no errors

- [ ] **Step 4: Run the e2e suite** (slower; launches real Chromium)

Run: `python -m pytest -q tests/web/e2e`
Expected: all green, confirming the new jobs.html/dashboard.html/
settings_data.html markup didn't break any JS-driven e2e flow

- [ ] **Step 5: Manually smoke-test all four features** against a local
  `uvicorn` run with a real (even if tiny) source config: run-now progress
  label, bulk status toolbar, notes modal, import preview+confirm+cancel+
  force escape hatch.

- [ ] **Step 6: Push the branch and open the PR**, body listing `Closes
  #213`, `Closes #220`, `Closes #221`, `Closes #222`.
