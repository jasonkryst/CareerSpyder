# Themed Confirm Modal, Guide Overflow, Dashboard Run History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close GH #40 (native `confirm()` → themed modal), #41 (Guide page horizontal overflow), and #42 (Dashboard "Run now" fix + past-runs table), per
`docs/superpowers/specs/2026-08-16-modal-overflow-dashboard-design.md`.

**Architecture:** Three independent-ish fixes landing in one branch: (1) a
two-line CSS fix for #41, (2) a `force` bypass on the shared
`run_and_notify` scheduler function plus a merge of the Dashboard and
History pages/routes/JS for #42, and (3) a new generic, site-wide
`<dialog>`-based confirm-modal component wired into the two forms that
need it (import, delete) for #40. No new dependencies, no build step —
same server-rendered Jinja2 + vanilla-JS approach as the rest of the app.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, SQLite (`sqlite3`), vanilla
JS (no framework), hand-written CSS with custom properties, pytest +
httpx `TestClient` for unit/integration tests, Playwright (`sync_api`,
already installed — chromium confirmed working) for e2e tests under
`tests/web/e2e/`.

## Global Constraints

- TDD throughout: write the failing test, watch it fail, then write the
  minimal implementation, then watch it pass, then commit — per task.
- Tests must not make live network calls; the e2e tests use the existing
  in-process `live_server`/Playwright fixtures in `tests/web/e2e/conftest.py`,
  never a real external site.
- Templates render through the single shared `Jinja2Templates` instance in
  `app/web/templating.py` — never instantiate a new one.
- Don't touch `SMTP_PASSWORD` handling, `sources.json` write-locking, or
  the per-source `try/except` in `app/orchestrator.py::run_once` — out of
  scope for all three issues.
- Run `pytest -q` (fast, no network/browser) after every task; run the
  Playwright e2e suite (`pytest tests/web/e2e -v`) after any task that
  touches JS/templates that e2e tests cover (Tasks 3, 5, 6, 8).
- Bump `pyproject.toml`'s version (`0.11.0` → `0.12.0`) as part of this
  branch, per this repo's one-minor-bump-per-PR convention.

---

### Task 1: Fix Guide page horizontal overflow (#41)

**Files:**
- Modify: `app/web/static/style.css:332-339` (the `code` rule), `app/web/static/style.css:213-217` (the `main` rule)
- Test: `tests/web/test_base.py`, `tests/web/e2e/test_card_tables.py` (new e2e case)

**Interfaces:**
- Consumes: nothing new.
- Produces: N/A — CSS-only, no new selectors or JS hooks for later tasks.

- [ ] **Step 1: Write the failing unit test**

Append to `tests/web/test_base.py`:

```python
def test_style_css_wraps_long_unbroken_text(client):
    resp = client.get("/static/style.css")

    assert resp.status_code == 200
    assert "overflow-wrap: anywhere" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_base.py::test_style_css_wraps_long_unbroken_text -v`
Expected: FAIL (`overflow-wrap: anywhere` not found in `resp.text`)

- [ ] **Step 3: Write the CSS fix**

In `app/web/static/style.css`, change:

```css
code {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 0.25rem;
  padding: 0.1rem 0.3rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.875em;
}
```

to:

```css
code {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 0.25rem;
  padding: 0.1rem 0.3rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.875em;
  overflow-wrap: anywhere;
}
```

And change:

```css
main {
  max-width: 60rem;
  margin: 0 auto;
  padding: var(--space-5) var(--space-4);
}
```

to:

```css
main {
  max-width: 60rem;
  margin: 0 auto;
  padding: var(--space-5) var(--space-4);
  overflow-wrap: break-word;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/web/test_base.py::test_style_css_wraps_long_unbroken_text -v`
Expected: PASS

- [ ] **Step 5: Add an e2e no-overflow regression test for the Guide page**

Append to `tests/web/e2e/test_card_tables.py`:

```python
def test_no_horizontal_overflow_on_guide_at_narrow_viewport(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/guide")

    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    inner_width = page.evaluate("window.innerWidth")
    assert scroll_width <= inner_width
```

- [ ] **Step 6: Run the new e2e test to verify it passes**

Run: `pytest tests/web/e2e/test_card_tables.py::test_no_horizontal_overflow_on_guide_at_narrow_viewport -v`
Expected: PASS (chromium is already installed in this environment — confirmed working)

- [ ] **Step 7: Run the full fast suite**

Run: `pytest -q`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add app/web/static/style.css tests/web/test_base.py tests/web/e2e/test_card_tables.py
git commit -m "Fix long URLs overflowing the Guide page (#41)"
```

---

### Task 2: Fix "Run now" silently no-op-ing on unconfigured days (#42, root cause)

**Files:**
- Modify: `app/scheduler.py:25-28`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `app.scheduler.run_and_notify(conn, sources_path: str, tz: str = "UTC", force: bool = False) -> None`. Task 3's `POST /run-now` handler calls this with `force=True`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scheduler.py`:

```python
def test_run_and_notify_force_bypasses_day_gate(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn, email_days="")
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": []})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary) as mock_run_once, \
         patch("app.scheduler.digest.build_digest", return_value=None):
        scheduler.run_and_notify(conn, sources_path, force=True)

    mock_run_once.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scheduler.py::test_run_and_notify_force_bypasses_day_gate -v`
Expected: FAIL with `TypeError: run_and_notify() got an unexpected keyword argument 'force'`

- [ ] **Step 3: Add the `force` parameter**

In `app/scheduler.py`, change:

```python
def run_and_notify(conn, sources_path: str, tz: str = "UTC") -> None:
    settings = db.get_settings(conn)
    if settings is not None and _today_code(tz) not in (settings["email_days"] or "").split(","):
        return
```

to:

```python
def run_and_notify(conn, sources_path: str, tz: str = "UTC", force: bool = False) -> None:
    settings = db.get_settings(conn)
    if not force and settings is not None and _today_code(tz) not in (settings["email_days"] or "").split(","):
        return
```

- [ ] **Step 4: Run the new test and the full scheduler suite**

Run: `pytest tests/test_scheduler.py -v`
Expected: all PASS, including the existing
`test_run_and_notify_skips_entire_run_when_no_days_selected` (unaffected —
it calls `run_and_notify` without `force`, still defaults to `False`)

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "Let 'Run now' bypass the configured-days gate meant for the cron job (#42)"
```

---

### Task 3: Merge Dashboard with History — routes, templates, JS, nav (#42)

**Files:**
- Create: `app/web/static/dashboard.js`
- Modify: `app/web/routes_dashboard.py`, `app/web/templates/dashboard.html`, `app/web/templates/_history_rows.html`, `app/web/templates/base.html`, `app/web/templates/guide.html`, `app/web/main.py`
- Delete: `app/web/routes_history.py`, `app/web/templates/history.html`, `app/web/static/history.js`
- Test: `tests/web/test_dashboard.py` (replaces `tests/web/test_history.py`), `tests/web/test_base.py`, `tests/web/e2e/test_card_tables.py`, `tests/web/e2e/test_keyboard_navigation.py`, rename `tests/web/e2e/test_history_refresh.py` → `tests/web/e2e/test_dashboard_rows_refresh.py`
- Delete: `tests/web/test_history.py`

**Interfaces:**
- Consumes: `run_and_notify(..., force=True)` from Task 2.
- Produces: `GET /` (paginated dashboard), `GET /rows` (AJAX partial, replaces `/history/rows`), unchanged `POST /run-now` (303 redirect, now `force=True`). Template ids `run-now-form`, `run-now-status`, `refresh-history`, `history-status`, `history-rows` (the last three carried over unchanged from the old History page). Static file `app/web/static/dashboard.js` (replaces `history.js`).

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_dashboard.py` (replacing its current contents entirely):

```python
from app import db


def test_dashboard_loads_with_no_runs_yet(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "CareerSpyder" in resp.text


def test_dashboard_run_now_button_is_primary(client):
    resp = client.get("/")

    assert 'class="btn-primary"' in resp.text


def test_run_now_triggers_background_task_and_redirects(client):
    resp = client.post("/run-now", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_run_now_forces_a_run_regardless_of_configured_days(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.web.routes_dashboard.run_and_notify",
        lambda *args, **kwargs: calls.append(kwargs),
    )

    client.post("/run-now", follow_redirects=False)

    assert calls == [{"force": True}]


def test_dashboard_lists_past_runs(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_job_count=3, failed_sources=["Bad Co"])

    resp = client.get("/")

    assert resp.status_code == 200
    assert "3" in resp.text
    assert "Bad Co" in resp.text


def test_dashboard_table_has_no_legacy_inline_attributes(client):
    resp = client.get("/")

    assert 'border="1"' not in resp.text
    assert 'cellpadding="4"' not in resp.text


def test_dashboard_table_has_scoped_headers_and_scroll_wrapper(client):
    resp = client.get("/")

    assert 'scope="col"' in resp.text
    assert 'class="table-scroll"' in resp.text


def test_dashboard_second_page_shows_older_runs(client):
    conn = client.app.state.conn
    for i in range(30):
        run_id = db.start_run(conn)
        db.finish_run(conn, run_id, new_job_count=i, failed_sources=[])

    page1 = client.get("/?page=1")
    page2 = client.get("/?page=2")

    assert "Page 1 of 2" in page1.text
    assert "Page 2 of 2" in page2.text


def test_dashboard_invalid_page_param_clamps_instead_of_erroring(client):
    resp = client.get("/?page=not-a-number")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_dashboard_negative_page_param_clamps_to_first_page(client):
    resp = client.get("/?page=-3")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_dashboard_table_cells_have_data_labels(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_job_count=3, failed_sources=["Bad Co"])

    resp = client.get("/")

    assert 'data-label="Started"' in resp.text
    assert 'data-label="Finished"' in resp.text
    assert 'data-label="New jobs"' in resp.text
    assert 'data-label="Failed sources"' in resp.text


def test_rows_endpoint_returns_fragment_without_page_chrome(client):
    resp = client.get("/rows")

    assert resp.status_code == 200
    assert 'id="history-rows"' in resp.text
    assert 'aria-label="Main"' not in resp.text
    assert "<html" not in resp.text


def test_rows_endpoint_paginates_like_dashboard_page(client):
    conn = client.app.state.conn
    for i in range(30):
        run_id = db.start_run(conn)
        db.finish_run(conn, run_id, new_job_count=i, failed_sources=[])

    page1 = client.get("/rows?page=1")
    page2 = client.get("/rows?page=2")

    assert "Page 1 of 2" in page1.text
    assert "Page 2 of 2" in page2.text


def test_rows_endpoint_invalid_page_param_clamps(client):
    resp = client.get("/rows?page=not-a-number")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_rows_reflects_run_status_change(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)

    in_progress = client.get("/rows")
    assert 'data-label="Finished">in progress' in in_progress.text

    db.finish_run(conn, run_id, new_job_count=2, failed_sources=[])
    finished = client.get("/rows")
    assert 'data-label="Finished">in progress' not in finished.text


def test_dashboard_includes_refresh_button_and_status_region(client):
    resp = client.get("/")

    assert 'id="refresh-history"' in resp.text
    assert 'id="history-status"' in resp.text
    assert 'aria-live="polite"' in resp.text
    assert 'id="history-rows"' in resp.text
    assert 'id="run-now-form"' in resp.text


def test_dashboard_js_is_served(client):
    resp = client.get("/static/dashboard.js")

    assert resp.status_code == 200
    assert "history-rows" in resp.text


def test_history_routes_removed(client):
    assert client.get("/history").status_code == 404
    assert client.get("/history/rows").status_code == 404
```

Delete `tests/web/test_history.py` (every case above is its equivalent, now
targeting `/` and `/rows`):

```bash
git rm tests/web/test_history.py
```

Update `tests/web/test_base.py` — `/history` won't exist anymore, so
change:

```python
def test_nav_marks_current_page_with_aria_current(client):
    resp = client.get("/history")

    assert 'href="/history" aria-current="page"' in resp.text
    assert 'href="/" aria-current="page"' not in resp.text
```

to:

```python
def test_nav_marks_current_page_with_aria_current(client):
    resp = client.get("/jobs")

    assert 'href="/jobs" aria-current="page"' in resp.text
    assert 'href="/" aria-current="page"' not in resp.text
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/web/test_dashboard.py tests/web/test_base.py -v`
Expected: FAIL — `/rows` and `force=True` don't exist yet, dashboard.js
isn't served, etc.

- [ ] **Step 3: Rewrite `app/web/routes_dashboard.py`**

```python
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db
from app.scheduler import run_and_notify
from app.web.pagination import paginate
from app.web.templating import templates

router = APIRouter()

PAGE_SIZE = 25


def _dashboard_context(request: Request, page: str) -> dict:
    total = db.count_runs(request.app.state.conn)
    pagination = paginate(total, page, PAGE_SIZE)
    runs = db.list_runs(request.app.state.conn, limit=PAGE_SIZE, offset=pagination.offset)
    return {"runs": runs, "pagination": pagination}


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, page: str = "1"):
    return templates.TemplateResponse(request, "dashboard.html", _dashboard_context(request, page))


@router.get("/rows", response_class=HTMLResponse)
def dashboard_rows(request: Request, page: str = "1"):
    return templates.TemplateResponse(request, "_history_rows.html", _dashboard_context(request, page))


@router.post("/run-now")
def run_now(request: Request, background_tasks: BackgroundTasks):
    background_tasks.add_task(
        run_and_notify, request.app.state.conn, request.app.state.sources_path, force=True,
    )
    return RedirectResponse(url="/", status_code=303)
```

- [ ] **Step 4: Rewrite `app/web/templates/dashboard.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>CareerSpyder</h1>
<div class="history-toolbar">
  <form method="post" action="/run-now" id="run-now-form">
    <button type="submit" class="btn-primary">Run now</button>
  </form>
  <span id="run-now-status" class="sr-only" aria-live="polite"></span>
  <button type="button" id="refresh-history">Refresh</button>
  <span id="history-status" class="sr-only" aria-live="polite"></span>
</div>
{% include "_history_rows.html" %}
{% endblock %}
```

- [ ] **Step 5: Update `_history_rows.html`'s pagination links**

In `app/web/templates/_history_rows.html`, change:

```html
<nav aria-label="Pagination">
  {% if pagination.has_prev %}<a href="/history?page={{ pagination.page - 1 }}">Previous</a>{% endif %}
  <span>Page {{ pagination.page }} of {{ pagination.total_pages }}</span>
  {% if pagination.has_next %}<a href="/history?page={{ pagination.page + 1 }}">Next</a>{% endif %}
</nav>
```

to:

```html
<nav aria-label="Pagination">
  {% if pagination.has_prev %}<a href="/?page={{ pagination.page - 1 }}">Previous</a>{% endif %}
  <span>Page {{ pagination.page }} of {{ pagination.total_pages }}</span>
  {% if pagination.has_next %}<a href="/?page={{ pagination.page + 1 }}">Next</a>{% endif %}
</nav>
```

- [ ] **Step 6: Create `app/web/static/dashboard.js`**

```javascript
(function () {
  var container = document.getElementById("history-rows");
  var refreshButton = document.getElementById("refresh-history");
  var status = document.getElementById("history-status");
  var runForm = document.getElementById("run-now-form");
  var runStatus = document.getElementById("run-now-status");
  if (!container) return;

  var POLL_MS = 10000;
  var pollTimer = null;

  function hasInProgressRun() {
    var cells = container.querySelectorAll('td[data-label="Finished"]');
    for (var i = 0; i < cells.length; i++) {
      if (cells[i].textContent.trim() === "in progress") return true;
    }
    return false;
  }

  function refresh() {
    var page = container.getAttribute("data-page") || "1";
    return fetch("/rows?page=" + encodeURIComponent(page))
      .then(function (resp) { return resp.text(); })
      .then(function (html) {
        var wrapper = document.createElement("div");
        wrapper.innerHTML = html;
        var next = wrapper.firstElementChild;
        container.replaceWith(next);
        container = next;
        if (status) status.textContent = "Updated";
        managePolling();
      });
  }

  function managePolling() {
    if (hasInProgressRun()) {
      if (!pollTimer) pollTimer = setInterval(refresh, POLL_MS);
    } else if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  if (refreshButton) refreshButton.addEventListener("click", refresh);

  if (runForm) {
    runForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var button = runForm.querySelector("button[type=submit]");
      if (button) button.disabled = true;
      if (runStatus) runStatus.textContent = "Starting run…";
      fetch(runForm.getAttribute("action"), { method: "POST" })
        .then(refresh)
        .then(function () {
          if (runStatus) runStatus.textContent = "Run started";
          if (button) button.disabled = false;
        });
    });
  }

  managePolling();
})();
```

Delete the old JS: `git rm app/web/static/history.js`

- [ ] **Step 7: Update `app/web/templates/base.html`**

Remove the History nav link — change:

```html
      <a href="/" {% if request.url.path == "/" %}aria-current="page"{% endif %}>Dashboard</a>
      <a href="/jobs" {% if request.url.path == "/jobs" %}aria-current="page"{% endif %}>Jobs</a>
      <a href="/history" {% if request.url.path == "/history" %}aria-current="page"{% endif %}>History</a>
      <a href="/sources" {% if request.url.path.startswith("/sources") %}aria-current="page"{% endif %}>Sources</a>
```

to:

```html
      <a href="/" {% if request.url.path == "/" %}aria-current="page"{% endif %}>Dashboard</a>
      <a href="/jobs" {% if request.url.path == "/jobs" %}aria-current="page"{% endif %}>Jobs</a>
      <a href="/sources" {% if request.url.path.startswith("/sources") %}aria-current="page"{% endif %}>Sources</a>
```

Point the script tag at the renamed JS file — change:

```html
  <script src="/static/history.js" defer></script>
```

to:

```html
  <script src="/static/dashboard.js" defer></script>
```

- [ ] **Step 8: Update `app/web/templates/guide.html`'s references to History**

Change the "Getting started" steps:

```html
  <li>Go to the <a href="/">Dashboard</a> and click <strong>Run now</strong> to trigger an
    immediate scrape.</li>
  <li>Check <a href="/history">History</a> for the run's result, or wait for the digest email
    if new jobs were found.</li>
```

to:

```html
  <li>Go to the <a href="/">Dashboard</a> and click <strong>Run now</strong> to trigger an
    immediate scrape.</li>
  <li>The Dashboard also shows past runs below the Run now button — check there for the
    result, or wait for the digest email if new jobs were found.</li>
```

And the "Web UI tour" table — change:

```html
  <tr><td><a href="/">Dashboard</a></td><td>Last run time and new-job count, plus a
    <strong>Run now</strong> button.</td></tr>
  <tr><td><a href="/history">History</a></td><td>Table of past runs &mdash; start/finish time,
    new job count, failed source names.</td></tr>
```

to:

```html
  <tr><td><a href="/">Dashboard</a></td><td>A <strong>Run now</strong> button (always
    triggers an immediate scrape) at the top, plus a paginated, auto-refreshing table of
    past runs &mdash; start/finish time, new job count, failed source names.</td></tr>
```

- [ ] **Step 9: Update `app/web/main.py`**

Change:

```python
from app.web.routes_dashboard import router as dashboard_router
from app.web.routes_guide import router as guide_router
from app.web.routes_history import router as history_router
from app.web.routes_jobs import router as jobs_router
from app.web.routes_settings import router as settings_router
from app.web.routes_sources import router as sources_router
```

to:

```python
from app.web.routes_dashboard import router as dashboard_router
from app.web.routes_guide import router as guide_router
from app.web.routes_jobs import router as jobs_router
from app.web.routes_settings import router as settings_router
from app.web.routes_sources import router as sources_router
```

And change:

```python
app.include_router(dashboard_router)
app.include_router(jobs_router)
app.include_router(history_router)
app.include_router(sources_router)
```

to:

```python
app.include_router(dashboard_router)
app.include_router(jobs_router)
app.include_router(sources_router)
```

Delete the old route module and template:

```bash
git rm app/web/routes_history.py app/web/templates/history.html
```

- [ ] **Step 10: Run the unit/integration tests**

Run: `pytest tests/web/test_dashboard.py tests/web/test_base.py tests/web/test_guide.py -v`
Expected: all PASS

Run: `pytest -q`
Expected: all PASS (no other file references `/history`, `history.js`,
or `routes_history` — confirmed by repo-wide search during planning)

- [ ] **Step 11: Update the e2e tests**

Rename and rewrite `tests/web/e2e/test_history_refresh.py`:

```bash
git mv tests/web/e2e/test_history_refresh.py tests/web/e2e/test_dashboard_rows_refresh.py
```

Replace its contents with:

```python
def test_refresh_button_swaps_table_content(live_server, page):
    page.goto(live_server + "/")

    page.route("**/rows*", lambda route: route.fulfill(
        status=200,
        content_type="text/html",
        body='<div id="history-rows" data-page="1"><div class="table-scroll"><table>'
             '<tr><th scope="col">Started</th></tr>'
             '<tr><td data-label="Started">MOCKED-ROW</td></tr>'
             '</table></div><nav aria-label="Pagination"><span>Page 1 of 1</span></nav></div>',
    ))

    page.click("#refresh-history")
    page.wait_for_selector("text=MOCKED-ROW")

    assert "MOCKED-ROW" in page.inner_text("#history-rows")


def test_status_region_announces_update_after_refresh(live_server, page):
    page.goto(live_server + "/")

    page.route("**/rows*", lambda route: route.fulfill(
        status=200,
        content_type="text/html",
        body='<div id="history-rows" data-page="1"><div class="table-scroll"><table></table></div>'
             '<nav aria-label="Pagination"><span>Page 1 of 1</span></nav></div>',
    ))

    page.click("#refresh-history")
    page.wait_for_function("document.getElementById('history-status').textContent === 'Updated'")


def test_auto_poll_starts_while_in_progress_and_stops_once_finished(live_server, page):
    call_count = {"n": 0}

    def handler(route):
        call_count["n"] += 1
        if call_count["n"] == 1:
            body = ('<div id="history-rows" data-page="1"><div class="table-scroll"><table>'
                     '<tr><th scope="col">Finished</th></tr>'
                     '<tr><td data-label="Finished">in progress</td></tr>'
                     '</table></div><nav aria-label="Pagination"><span>Page 1 of 1</span></nav></div>')
        else:
            body = ('<div id="history-rows" data-page="1"><div class="table-scroll"><table>'
                     '<tr><th scope="col">Finished</th></tr>'
                     '<tr><td data-label="Finished">2026-08-16T00:00:00+00:00</td></tr>'
                     '</table></div><nav aria-label="Pagination"><span>Page 1 of 1</span></nav></div>')
        route.fulfill(status=200, content_type="text/html", body=body)

    page.route("**/rows*", handler)
    page.goto(live_server + "/")

    page.click("#refresh-history")
    page.wait_for_function(
        "document.querySelector('td[data-label=\"Finished\"]')?.textContent.trim() === 'in progress'"
    )

    page.wait_for_function(
        "document.querySelector('td[data-label=\"Finished\"]')?.textContent.trim() !== 'in progress'",
        timeout=15000,
    )
    assert call_count["n"] >= 2


def test_manual_refresh_works_when_nothing_is_in_progress(live_server, page):
    page.goto(live_server + "/")

    page.route("**/rows*", lambda route: route.fulfill(
        status=200,
        content_type="text/html",
        body='<div id="history-rows" data-page="1"><div class="table-scroll"><table>'
             '<tr><th scope="col">Finished</th></tr>'
             '<tr><td data-label="Finished">2026-08-16T00:00:00+00:00</td></tr>'
             '</table></div><nav aria-label="Pagination"><span>Page 1 of 1</span></nav></div>',
    ))

    page.click("#refresh-history")
    page.wait_for_function("document.getElementById('history-status').textContent === 'Updated'")
```

Replace the entire contents of `tests/web/e2e/test_card_tables.py` with
the following (this supersedes the whole file, including the
`test_no_horizontal_overflow_on_guide_at_narrow_viewport` function Task 1
appended to it — that function is repeated verbatim at the end below, so
nothing is lost):

```python
import time


def _seed_one_run(live_server, page):
    page.goto(live_server + "/")
    page.click('button:has-text("Run now")')
    page.wait_for_url(live_server + "/")

    for _ in range(20):
        page.goto(live_server + "/")
        if page.query_selector(".table-scroll td"):
            return
        time.sleep(0.25)
    raise AssertionError("run did not appear in the dashboard table in time")


def test_dashboard_table_is_grid_at_desktop_width(live_server, page):
    page.goto(live_server + "/")

    thead_display = page.eval_on_selector(
        '.table-scroll thead, .table-scroll tr:first-child',
        "el => getComputedStyle(el).display",
    )
    assert thead_display != "none"


def test_dashboard_table_becomes_cards_at_narrow_width(live_server, page):
    _seed_one_run(live_server, page)

    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/")

    label_content = page.eval_on_selector(
        '.table-scroll td',
        "el => getComputedStyle(el, '::before').content",
    )
    assert label_content not in (None, "none", '""')


def test_no_horizontal_overflow_on_dashboard_at_narrow_viewport(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/")

    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    inner_width = page.evaluate("window.innerWidth")
    assert scroll_width <= inner_width


def test_no_horizontal_overflow_on_guide_at_narrow_viewport(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/guide")

    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    inner_width = page.evaluate("window.innerWidth")
    assert scroll_width <= inner_width
```

Update `tests/web/e2e/test_keyboard_navigation.py` — change:

```python
def test_tab_order_reaches_run_now_button_after_skip_link_and_nav(live_server, page):
    page.goto(live_server + "/")

    # skip-link, then the 6 nav links (Dashboard/Jobs/History/Sources/Settings/Guide), then Run now
    for _ in range(8):
        page.keyboard.press("Tab")

    assert page.evaluate("document.activeElement.textContent.trim()") == "Run now"
```

to:

```python
def test_tab_order_reaches_run_now_button_after_skip_link_and_nav(live_server, page):
    page.goto(live_server + "/")

    # skip-link, then the 5 nav links (Dashboard/Jobs/Sources/Settings/Guide), then Run now
    for _ in range(7):
        page.keyboard.press("Tab")

    assert page.evaluate("document.activeElement.textContent.trim()") == "Run now"
```

- [ ] **Step 12: Run the full e2e suite**

Run: `pytest tests/web/e2e -v`
Expected: all PASS

- [ ] **Step 13: Commit**

```bash
git add -A
git commit -m "Merge Dashboard with History: paginated run table + Run now at top (#42)"
```

---

### Task 4: Build the generic themed confirm-modal component (#40)

**Files:**
- Create: `app/web/static/confirm-modal.js`
- Modify: `app/web/templates/base.html`, `app/web/static/style.css`
- Test: `tests/web/test_base.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: markup contract any form can opt into —
  `<form data-confirm-title="..." data-confirm-message="...">` — plus DOM
  ids `#confirm-modal`, `#confirm-modal-title`, `#confirm-modal-message`,
  `#confirm-modal-confirm`, `#confirm-modal-cancel`. Tasks 5 and 6 consume
  this contract; Task 5/6's e2e tests consume the button ids.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_base.py`:

```python
def test_confirm_modal_markup_present_on_every_page(client):
    resp = client.get("/")

    assert 'id="confirm-modal"' in resp.text
    assert 'id="confirm-modal-title"' in resp.text
    assert 'id="confirm-modal-message"' in resp.text
    assert 'id="confirm-modal-confirm"' in resp.text
    assert 'id="confirm-modal-cancel"' in resp.text


def test_confirm_modal_js_is_served(client):
    resp = client.get("/static/confirm-modal.js")

    assert resp.status_code == 200
    assert "showModal" in resp.text
    assert "data-confirm-message" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_base.py::test_confirm_modal_markup_present_on_every_page tests/web/test_base.py::test_confirm_modal_js_is_served -v`
Expected: FAIL (markup/file don't exist yet)

- [ ] **Step 3: Create `app/web/static/confirm-modal.js`**

```javascript
(function () {
  var dialog = document.getElementById("confirm-modal");
  if (!dialog || typeof dialog.showModal !== "function") return;

  var titleEl = document.getElementById("confirm-modal-title");
  var messageEl = document.getElementById("confirm-modal-message");
  var confirmBtn = document.getElementById("confirm-modal-confirm");
  var cancelBtn = document.getElementById("confirm-modal-cancel");
  var pendingForm = null;

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.dataset.confirmed === "true") {
      delete form.dataset.confirmed;
      return;
    }
    var message = form.getAttribute("data-confirm-message");
    if (!message) return;

    event.preventDefault();
    pendingForm = form;
    titleEl.textContent = form.getAttribute("data-confirm-title") || "Please confirm";
    messageEl.textContent = message;
    dialog.showModal();
  });

  confirmBtn.addEventListener("click", function () {
    dialog.close();
    if (pendingForm) {
      var form = pendingForm;
      pendingForm = null;
      form.dataset.confirmed = "true";
      if (form.requestSubmit) {
        form.requestSubmit();
      } else {
        form.submit();
      }
    }
  });

  cancelBtn.addEventListener("click", function () {
    dialog.close();
    pendingForm = null;
  });

  dialog.addEventListener("cancel", function () {
    pendingForm = null;
  });
})();
```

- [ ] **Step 4: Add the modal markup and script tag to `app/web/templates/base.html`**

Change:

```html
  <main id="main">
    {% block content %}{% endblock %}
  </main>
  <footer>
    <p>{{ app_name }} v{{ app_version }}</p>
  </footer>
</body>
</html>
```

to:

```html
  <main id="main">
    {% block content %}{% endblock %}
  </main>
  <footer>
    <p>{{ app_name }} v{{ app_version }}</p>
  </footer>
  <dialog id="confirm-modal" class="modal">
    <h2 id="confirm-modal-title">Please confirm</h2>
    <p id="confirm-modal-message"></p>
    <div class="modal-actions">
      <button type="button" id="confirm-modal-cancel">Cancel</button>
      <button type="button" id="confirm-modal-confirm" class="btn-primary">Confirm</button>
    </div>
  </dialog>
</body>
</html>
```

Add the script tag — change:

```html
  <script src="/static/dashboard.js" defer></script>
```

to:

```html
  <script src="/static/dashboard.js" defer></script>
  <script src="/static/confirm-modal.js" defer></script>
```

- [ ] **Step 5: Style the modal in `app/web/static/style.css`**

Append to the end of the file:

```css
dialog.modal {
  border: none;
  border-radius: var(--radius);
  padding: var(--space-5);
  background: var(--bg-elevated);
  color: var(--fg);
  box-shadow: var(--shadow);
  max-width: 28rem;
  width: calc(100% - var(--space-4) * 2);
}

dialog.modal::backdrop {
  background: rgba(0, 0, 0, 0.5);
}

dialog.modal .modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-4);
}
```

- [ ] **Step 6: Run the tests**

Run: `pytest tests/web/test_base.py -v`
Expected: all PASS

Run: `pytest -q`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add app/web/static/confirm-modal.js app/web/templates/base.html app/web/static/style.css tests/web/test_base.py
git commit -m "Add a generic themed confirm-modal component (#40)"
```

---

### Task 5: Wire the import-settings form to the confirm modal (#40)

**Files:**
- Modify: `app/web/templates/settings_data.html`
- Test: `tests/web/test_settings.py`, `tests/web/e2e/test_import_confirmation.py`

**Interfaces:**
- Consumes: `data-confirm-title`/`data-confirm-message` contract from Task 4.
- Produces: nothing new for later tasks.

- [ ] **Step 1: Update the failing unit test**

In `tests/web/test_settings.py`, change:

```python
def test_settings_data_import_form_has_confirm_guard(client):
    resp = client.get("/settings/data")

    assert 'id="import-form"' in resp.text
    assert "confirm(" in resp.text
```

to:

```python
def test_settings_data_import_form_has_confirm_guard(client):
    resp = client.get("/settings/data")

    assert 'id="import-form"' in resp.text
    assert 'data-confirm-message="Importing will replace your entire source list. Continue?"' in resp.text
    assert "confirm(" not in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_settings.py::test_settings_data_import_form_has_confirm_guard -v`
Expected: FAIL (`data-confirm-message` not present; `confirm(` still present)

- [ ] **Step 3: Update `app/web/templates/settings_data.html`**

Change:

```html
<div class="card">
<h2>Export/Import settings</h2>
<p><a href="/settings/data/export">Export settings</a></p>
<form method="post" action="/settings/data/import" enctype="multipart/form-data" id="import-form">
  <label>Import settings <input type="file" name="file" accept="application/json"></label>
  <button type="submit">Import</button>
</form>
<p>Importing replaces the entire source list with the contents of the uploaded
file. Preferences (check days, resend, recipients) are only replaced if the
file includes a <code>preferences</code> section.</p>
</div>
<script>
(function () {
  var form = document.getElementById("import-form");
  if (!form) return;
  form.addEventListener("submit", function (event) {
    if (!confirm("Importing will replace your entire source list. Continue?")) {
      event.preventDefault();
    }
  });
})();
</script>
{% endblock %}
```

to:

```html
<div class="card">
<h2>Export/Import settings</h2>
<p><a href="/settings/data/export">Export settings</a></p>
<form method="post" action="/settings/data/import" enctype="multipart/form-data" id="import-form"
      data-confirm-title="Import settings"
      data-confirm-message="Importing will replace your entire source list. Continue?">
  <label>Import settings <input type="file" name="file" accept="application/json"></label>
  <button type="submit">Import</button>
</form>
<p>Importing replaces the entire source list with the contents of the uploaded
file. Preferences (check days, resend, recipients) are only replaced if the
file includes a <code>preferences</code> section.</p>
</div>
{% endblock %}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/web/test_settings.py -v`
Expected: all PASS

- [ ] **Step 5: Update the e2e test**

In `tests/web/e2e/test_import_confirmation.py`, replace the whole file:

```python
import json


def test_confirming_modal_allows_import_to_proceed(live_server, page):
    page.goto(live_server + "/settings/data")

    payload = json.dumps({"sources": []}).encode()
    page.set_input_files('input[name="file"]', {
        "name": "settings.json", "mimeType": "application/json", "buffer": payload,
    })
    page.click('#import-form button[type="submit"]')
    page.wait_for_selector("#confirm-modal[open]")
    page.click("#confirm-modal-confirm")
    page.wait_for_url("**/settings/data?imported=0")


def test_dismissing_modal_cancels_import(live_server, page):
    page.goto(live_server + "/settings/data")

    payload = json.dumps({"sources": []}).encode()
    page.set_input_files('input[name="file"]', {
        "name": "settings.json", "mimeType": "application/json", "buffer": payload,
    })
    page.click('#import-form button[type="submit"]')
    page.wait_for_selector("#confirm-modal[open]")
    page.click("#confirm-modal-cancel")

    page.wait_for_timeout(300)
    assert page.url.endswith("/settings/data")
    assert "imported" not in page.url
```

- [ ] **Step 6: Run the e2e test**

Run: `pytest tests/web/e2e/test_import_confirmation.py -v`
Expected: both PASS

- [ ] **Step 7: Commit**

```bash
git add app/web/templates/settings_data.html tests/web/test_settings.py tests/web/e2e/test_import_confirmation.py
git commit -m "Replace native confirm() on settings import with the themed modal (#40)"
```

---

### Task 6: Add a delete confirmation to the Sources page using the same modal (#40 bonus)

**Files:**
- Modify: `app/web/templates/sources_list.html`
- Test: `tests/web/test_sources_list.py`
- Create: `tests/web/e2e/test_delete_confirmation.py`

**Interfaces:**
- Consumes: `data-confirm-title`/`data-confirm-message` contract from Task 4.
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing unit test**

Append to `tests/web/test_sources_list.py`:

```python
def test_delete_form_has_confirm_guard(client):
    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme (Greenhouse)", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.get("/sources")

    assert 'data-confirm-title="Delete source"' in resp.text
    assert "Delete &quot;Acme (Greenhouse)&quot;? This can't be undone." in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_sources_list.py::test_delete_form_has_confirm_guard -v`
Expected: FAIL (`data-confirm-title` not present)

- [ ] **Step 3: Update `app/web/templates/sources_list.html`**

Change:

```html
    <td data-label="Delete">
      <form method="post" action="/sources/{{ s.id }}/delete" style="display:inline">
        <button type="submit">Delete</button>
      </form>
    </td>
```

to:

```html
    <td data-label="Delete">
      <form method="post" action="/sources/{{ s.id }}/delete" style="display:inline"
            data-confirm-title="Delete source"
            data-confirm-message="Delete &quot;{{ s.name }}&quot;? This can't be undone.">
        <button type="submit">Delete</button>
      </form>
    </td>
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/web/test_sources_list.py -v`
Expected: all PASS. (Jinja2 autoescapes `{{ s.name }}`, so an
apostrophe/quote in a source name can't break out of the attribute —
double-check with a source named e.g. `O'Brien "Staffing"` if unsure by
adding a temporary manual check; not required as a permanent test case
since this is standard Jinja2 autoescaping, not new logic.)

- [ ] **Step 5: Add an e2e test for the delete confirmation**

Create `tests/web/e2e/test_delete_confirmation.py`. Each test adds its
own source through the UI first (via `/sources/new`) rather than relying
on state from another test file, since `live_server` is a session-scoped
fixture shared across the whole e2e suite:

```python
def test_dismissing_modal_keeps_the_source(live_server, page):
    page.goto(live_server + "/sources/new")
    page.fill('input[name="name"]', "Acme (Greenhouse)")
    page.select_option('select[name="type"]', "greenhouse")
    page.fill('input[name="board_token"]', "acme")
    page.click('button[type="submit"]')
    page.wait_for_url("**/sources")

    page.click('form:has-text("Acme (Greenhouse)") button:has-text("Delete")')
    page.wait_for_selector("#confirm-modal[open]")
    page.click("#confirm-modal-cancel")

    page.wait_for_timeout(300)
    assert page.locator('text=Acme (Greenhouse)').count() == 1


def test_confirming_modal_deletes_the_source(live_server, page):
    page.goto(live_server + "/sources/new")
    page.fill('input[name="name"]', "Beta (Lever)")
    page.select_option('select[name="type"]', "lever")
    page.fill('input[name="board_token"]', "beta")
    page.click('button[type="submit"]')
    page.wait_for_url("**/sources")

    page.click('form:has-text("Beta (Lever)") button:has-text("Delete")')
    page.wait_for_selector("#confirm-modal[open]")
    page.click("#confirm-modal-confirm")

    page.wait_for_timeout(300)
    assert page.locator('text=Beta (Lever)').count() == 0
```

- [ ] **Step 6: Run the e2e test**

Run: `pytest tests/web/e2e/test_delete_confirmation.py -v`
Expected: both PASS

- [ ] **Step 7: Run the full fast suite and full e2e suite once more**

Run: `pytest -q && pytest tests/web/e2e -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add app/web/templates/sources_list.html tests/web/test_sources_list.py tests/web/e2e/test_delete_confirmation.py
git commit -m "Guard source deletion with the themed confirm modal (#40)"
```

---

### Task 7: Documentation + version bump

**Files:**
- Modify: `CHANGELOG.md`, `pyproject.toml`, `README.md`, `docs/USAGE.md`, `ROADMAP.md`

No tests — these are docs/metadata changes, verified by reading the diff.

- [ ] **Step 1: Bump the version in `pyproject.toml`**

Change:

```toml
version = "0.11.0"
```

to:

```toml
version = "0.12.0"
```

- [ ] **Step 2: Add a CHANGELOG entry**

In `CHANGELOG.md`, change:

```markdown
## [Unreleased]

## [0.11.0] — 2026-08-16
```

to:

```markdown
## [Unreleased]

## [0.12.0] — 2026-08-16

### Fixed

- "Run now" on the Dashboard silently did nothing on any day not
  included in the configured "check days" (Preferences) — the same
  day-of-week gate meant for the scheduled daily cron was incorrectly
  applied to the manual button too. Run now now always triggers a scrape
  regardless of the configured days (issue #42).
- Long unbroken strings (e.g. source URLs) on the Guide page overflowed
  their container instead of wrapping, widening the page past the
  viewport (issue #41).

### Added

- The Dashboard now shows past run executions in a paginated,
  auto-refreshing responsive table (reusing the former History page's
  table), with the Run now button at the top; the separate History page
  and nav link have been removed (issue #42).
- A themed, reusable confirm-modal dialog replaces the native
  `confirm()` popup previously used before importing settings, and now
  also guards source deletion, which previously had no confirmation at
  all (issue #40).

## [0.11.0] — 2026-08-16
```

- [ ] **Step 3: Update `README.md`'s Web UI table**

Change:

```markdown
| `/` (Dashboard) | Last run time and new-job count, plus a **Run now** button that triggers a scrape as a background task without blocking the page. |
| `/jobs` | Every job CareerSpyder has ever found — company, search name, linked title, location, dates found/removed, age, emailed status, and a summary where available. |
| `/history` | Table of past runs — start/finish time, new job count, failed source names. |
| `/sources` | Table of configured sources with Edit/Delete actions and an **Add source** button. |
| `/sources/new`, `/sources/{id}/edit` | A form for one source; the `type` field determines which other fields are shown. Includes a **Test this source** button that runs the adapter once against the in-progress (unsaved) form values and previews the jobs it currently finds — useful for validating `generic_html` selectors before committing. |
| `/settings/email` | SMTP host/port/from address. The SMTP password is intentionally not present here (see [Secrets](#secrets)). |
| `/settings/data` | Clear the job dedup cache (the next run will re-report every currently known job as new and may send a large digest email), and export/import `sources.json` (import replaces the entire source list, and asks for confirmation before doing so). |
```

to:

```markdown
| `/` (Dashboard) | A **Run now** button (always triggers an immediate scrape, regardless of configured check days) at the top, plus a paginated, auto-refreshing table of past runs — start/finish time, new job count, failed source names. |
| `/jobs` | Every job CareerSpyder has ever found — company, search name, linked title, location, dates found/removed, age, emailed status, and a summary where available. |
| `/sources` | Table of configured sources with Edit/Delete actions (delete asks for confirmation via a themed dialog) and an **Add source** button. |
| `/sources/new`, `/sources/{id}/edit` | A form for one source; the `type` field determines which other fields are shown. Includes a **Test this source** button that runs the adapter once against the in-progress (unsaved) form values and previews the jobs it currently finds — useful for validating `generic_html` selectors before committing. |
| `/settings/email` | SMTP host/port/from address. The SMTP password is intentionally not present here (see [Secrets](#secrets)). |
| `/settings/data` | Clear the job dedup cache (the next run will re-report every currently known job as new and may send a large digest email), and export/import `sources.json` (import replaces the entire source list, and asks for confirmation via a themed dialog before doing so). |
```

- [ ] **Step 4: Update `docs/USAGE.md`**

Change the "Getting started" list:

```markdown
5. Go to the **Dashboard** and click **Run now** to trigger an immediate
   scrape.
6. Check **History** for the run's result, the **Jobs** page for the
   postings themselves, or wait for the digest email if new jobs were
   found.
```

to:

```markdown
5. Go to the **Dashboard** and click **Run now** to trigger an immediate
   scrape.
6. Check the **Dashboard**'s run table for the result, the **Jobs** page
   for the postings themselves, or wait for the digest email if new jobs
   were found.
```

Change the "Web UI tour" table:

```markdown
| Dashboard (`/`) | Last run time and new-job count, plus a **Run now** button. |
| Jobs (`/jobs`) | Every job ever found — company, search name, title/link, location, dates found/removed, age, emailed status, and a summary where available. |
| History (`/history`) | Table of past runs — start/finish time, new job count, failed source names. A **Refresh** button re-fetches the latest rows, and the page auto-refreshes itself every 10 seconds while a run is still in progress. |
| Sources (`/sources`) | Table of configured sources with Edit/Delete actions and an **Add source** button. |
| Settings → Email (`/settings/email`) | SMTP host/port/from address (the password is a container env var, not editable here). |
| Settings → Data (`/settings/data`) | Clear the job dedup cache, and export/import `sources.json`. Importing asks for confirmation before replacing the source list. |
```

to:

```markdown
| Dashboard (`/`) | A **Run now** button (always triggers an immediate scrape, regardless of configured check days) at the top, plus a paginated table of past runs — start/finish time, new job count, failed source names. A **Refresh** button re-fetches the latest rows, and the page auto-refreshes itself every 10 seconds while a run is still in progress. |
| Jobs (`/jobs`) | Every job ever found — company, search name, title/link, location, dates found/removed, age, emailed status, and a summary where available. |
| Sources (`/sources`) | Table of configured sources with Edit/Delete actions (delete asks for confirmation via a themed dialog) and an **Add source** button. |
| Settings → Email (`/settings/email`) | SMTP host/port/from address (the password is a container env var, not editable here). |
| Settings → Data (`/settings/data`) | Clear the job dedup cache, and export/import `sources.json`. Importing asks for confirmation via a themed dialog before replacing the source list. |
```

- [ ] **Step 5: Trim `ROADMAP.md`**

Remove this now-resolved bullet from the "## Features" section:

```markdown
- **Richer frontend (from design spec).** v1 is deliberately
  server-rendered, full-page-reload HTML with no SPA and no JS build step.
  The History page now polls for in-progress-run updates (issue #34); a
  similar live-updating indicator on the Dashboard's "Run now" button is
  a reasonable next step if the current UX feels too static there too,
  but isn't needed for the core job-digest use case.
```

- [ ] **Step 6: Verify the version is consistent app-wide**

Run: `pytest tests/web/test_base.py::test_footer_shows_app_name_and_version -v`
Expected: PASS (it reads `importlib.metadata.version("careerspyder")`,
which picks up the new `pyproject.toml` version automatically — no code
change needed there)

- [ ] **Step 7: Commit**

```bash
git add CHANGELOG.md pyproject.toml README.md docs/USAGE.md ROADMAP.md
git commit -m "Update docs and bump version to 0.12.0 for #40/#41/#42"
```

---

### Task 8: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full fast test suite**

Run: `pytest -q`
Expected: all PASS, no warnings about missing fixtures/routes

- [ ] **Step 2: Run the full Playwright e2e suite**

Run: `pytest tests/web/e2e -v`
Expected: all PASS

- [ ] **Step 3: Manual browser walkthrough**

Start the app: `uvicorn app.web.main:app --reload --port 8080` (set
`CAREERSPYDER_DB_PATH`/`CAREERSPYDER_SOURCES_PATH` to temp paths first,
or just accept the container defaults if running via `docker compose up`
instead). In a real browser:

1. Load `/guide` at a narrow window width (~375px) and confirm the
   Indeed/LinkedIn example URLs wrap instead of overflowing.
2. Load `/` (Dashboard): confirm Run now is at the top, click it, and
   confirm the table updates in place (no full page reload) showing an
   "in progress" row that later flips to a timestamp, without a manual
   refresh — including on a day you've excluded via
   `/settings/preferences` "check days," to confirm the fix actually
   fires the scrape.
3. Load `/settings/data`, click Import with a file selected: confirm a
   themed dialog appears (not a browser-native popup), Cancel leaves the
   source list untouched, Confirm proceeds.
4. Load `/sources`, click Delete on a row: confirm the same themed
   dialog appears, Cancel keeps the row, Confirm removes it.
5. Confirm the removed `/history` nav link is gone and `/history`
   404s.

- [ ] **Step 4: Confirm no stray references remain**

Run: `grep -rn "confirm(" app/web/templates app/web/static` — expected:
no matches (the only prior use was the deleted inline script).

Run: `grep -rln "history\.js\|routes_history\|/history\b" app tests` —
expected: no matches (everything was renamed/removed in Task 3).

No commit for this task — it's verification-only. If anything fails,
fix it in the task that introduced it and re-commit there (or as a
follow-up fixup commit if the branch has already been reviewed).
