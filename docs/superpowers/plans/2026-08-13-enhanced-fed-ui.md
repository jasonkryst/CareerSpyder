# Enhanced FED UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give CareerSpyder's server-rendered web UI responsive layout, light/dark theming, accessibility improvements, server-side pagination on the History and Sources tables, and an app name + version footer, per GitHub issue #12, with route-level and browser-level test coverage.

**Architecture:** Stay entirely within the existing FastAPI + Jinja2, no-build-step architecture. Add a `static/` directory (CSS + one small JS file) served via `StaticFiles`, extend `base.html` with semantic/responsive/theming markup, add a small pure-function pagination helper used by both `/history` and `/sources`, and add a new Playwright-based e2e test layer alongside the existing FastAPI `TestClient` tests.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, SQLite (stdlib `sqlite3`), Playwright (already a dependency — used today only by scraping adapters), pytest.

## Global Constraints

- No React, no JS build step, no new runtime dependencies — vanilla CSS/JS only, matching the project's deliberate v1 architecture decision (see spec).
- Any new file under `app/web/static/` must be added to `pyproject.toml`'s `[tool.setuptools.package-data]` (`"app.web" = ["templates/*.html", "static/*"]`) or it silently won't ship in the installed package / Docker image.
- Pagination must **clamp** invalid `page` query params (missing, `0`, negative, non-integer, past the last page) to a valid page rather than raising a 400/500. `total_pages` is always at least `1`, even when the underlying collection is empty.
- Pagination page size is a fixed `25`; UI is Prev/Next + "Page X of Y" text only — no numbered page list.
- The dark/light theme choice must be applied via an **inline, non-deferred** `<script>` in `<head>` (reads `localStorage`, sets `data-theme` on `<html>`) so there is no flash of the wrong theme on load; the deferred `theme.js` file only wires the toggle button's click handler.
- Every `<table>` must be wrapped in `<div class="table-scroll">` and every `<th>` must carry `scope="col"`.
- Tests must not make live network calls. The new Playwright e2e tests drive a real local `uvicorn` instance of this app (no external network) — that's consistent with the existing "no live network" rule, not a violation of it.
- `pytest -q` must stay fast enough to run in CI; keep the Playwright e2e test count small and focused (theme toggle, keyboard tab order, no horizontal overflow) rather than broad UI coverage.

---

### Task 1: Foundation shell — static assets, base.html, theming

**Files:**
- Create: `app/web/static/style.css`
- Create: `app/web/static/theme.js`
- Modify: `app/web/templating.py`
- Modify: `app/web/main.py`
- Modify: `app/web/templates/base.html`
- Modify: `pyproject.toml`
- Test: Create `tests/web/test_base.py`

**Interfaces:**
- Produces: `templates.env.globals["app_name"]` (`"CareerSpyder"`) and `templates.env.globals["app_version"]` (string from `importlib.metadata.version("careerspyder")`), available in every template without any route change.
- Produces: `/static/style.css` and `/static/theme.js` served as static files.
- Produces: `base.html` markup contract every other template implicitly relies on: `<html lang="en">`, a `<meta name="viewport">`, a `.skip-link` as the first focusable element, `<header>` containing `<nav aria-label="Main">` (4 links, each getting `aria-current="page"` when `request.url.path` matches/starts-with its section) and `<button id="theme-toggle" aria-pressed="...">`, `<main id="main">{% block content %}{% endblock %}</main>`, and a `<footer>` showing `{{ app_name }} v{{ app_version }}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_base.py`:

```python
from importlib.metadata import version


def test_footer_shows_app_name_and_version(client):
    resp = client.get("/")

    assert resp.status_code == 200
    assert "CareerSpyder" in resp.text
    assert f"v{version('careerspyder')}" in resp.text


def test_base_layout_has_viewport_lang_and_skip_link(client):
    resp = client.get("/")

    assert '<html lang="en">' in resp.text
    assert 'name="viewport"' in resp.text
    assert 'class="skip-link"' in resp.text


def test_nav_marks_current_page_with_aria_current(client):
    resp = client.get("/history")

    assert 'href="/history" aria-current="page"' in resp.text
    assert 'href="/" aria-current="page"' not in resp.text


def test_theme_toggle_button_present(client):
    resp = client.get("/")

    assert 'id="theme-toggle"' in resp.text
    assert 'aria-pressed="false"' in resp.text


def test_static_assets_are_served(client):
    css = client.get("/static/style.css")
    js = client.get("/static/theme.js")

    assert css.status_code == 200
    assert "prefers-color-scheme" in css.text
    assert js.status_code == 200
    assert "localStorage" in js.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_base.py -v`
Expected: FAIL — `<html lang="en">`, `.skip-link`, `#theme-toggle`, and `/static/*` don't exist yet; `app_version` isn't in the footer.

- [ ] **Step 3: Add version/name Jinja globals**

Modify `app/web/templating.py` (replace the whole file):

```python
"""Shared Jinja2Templates instance.

Uses an absolute path derived from this module's own location so template
resolution does not depend on the process's current working directory (which
would otherwise break when the package is installed/run from a location
other than the source checkout).
"""

from importlib.metadata import version
from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["app_name"] = "CareerSpyder"
templates.env.globals["app_version"] = version("careerspyder")
```

- [ ] **Step 4: Mount static files**

Modify `app/web/main.py`. Add to the imports at the top:

```python
from pathlib import Path

from fastapi.staticfiles import StaticFiles
```

Add right after `app = FastAPI(title="CareerSpyder", lifespan=lifespan)`:

```python
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)
```

- [ ] **Step 5: Declare static/ as shipped package data**

Modify `pyproject.toml`:

```toml
[tool.setuptools.package-data]
"app.web" = ["templates/*.html", "static/*"]
```

- [ ] **Step 6: Write style.css**

Create `app/web/static/style.css`:

```css
:root {
  --bg: #ffffff;
  --bg-elevated: #f5f5f7;
  --fg: #1a1a1a;
  --fg-muted: #55555a;
  --border: #d0d0d5;
  --accent: #0a5cd8;
  --accent-fg: #ffffff;
  --error-bg: #fdeaea;
  --error-fg: #8a1f1f;
  --focus-ring: #0a5cd8;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14151a;
    --bg-elevated: #1e2027;
    --fg: #e8e8ea;
    --fg-muted: #a8a8b0;
    --border: #34363f;
    --accent: #6ea8ff;
    --accent-fg: #0b1220;
    --error-bg: #3a1616;
    --error-fg: #ff9a9a;
    --focus-ring: #6ea8ff;
  }
}

:root[data-theme="dark"] {
  --bg: #14151a;
  --bg-elevated: #1e2027;
  --fg: #e8e8ea;
  --fg-muted: #a8a8b0;
  --border: #34363f;
  --accent: #6ea8ff;
  --accent-fg: #0b1220;
  --error-bg: #3a1616;
  --error-fg: #ff9a9a;
  --focus-ring: #6ea8ff;
}

:root[data-theme="light"] {
  --bg: #ffffff;
  --bg-elevated: #f5f5f7;
  --fg: #1a1a1a;
  --fg-muted: #55555a;
  --border: #d0d0d5;
  --accent: #0a5cd8;
  --accent-fg: #ffffff;
  --error-bg: #fdeaea;
  --error-fg: #8a1f1f;
  --focus-ring: #0a5cd8;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  line-height: 1.5;
}

.skip-link {
  position: absolute;
  left: -9999px;
  top: 0;
  background: var(--accent);
  color: var(--accent-fg);
  padding: 0.5rem 1rem;
  z-index: 100;
}

.skip-link:focus {
  left: 0.5rem;
  top: 0.5rem;
}

header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1rem;
  border-bottom: 1px solid var(--border);
}

nav[aria-label="Main"] {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}

nav[aria-label="Main"] a {
  color: var(--fg);
  text-decoration: none;
}

nav[aria-label="Main"] a[aria-current="page"] {
  color: var(--accent);
  font-weight: 600;
  text-decoration: underline;
}

main {
  max-width: 60rem;
  margin: 0 auto;
  padding: 1.5rem 1rem;
}

footer {
  max-width: 60rem;
  margin: 0 auto;
  padding: 1rem;
  color: var(--fg-muted);
  font-size: 0.875rem;
}

button, input, select {
  font: inherit;
  color: inherit;
}

button {
  background: var(--bg-elevated);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 0.375rem;
  padding: 0.5rem 0.875rem;
  cursor: pointer;
}

button:hover {
  border-color: var(--accent);
}

input[type="text"], input[type="number"] {
  background: var(--bg);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 0.25rem;
  padding: 0.375rem 0.5rem;
  width: 100%;
  max-width: 28rem;
}

label {
  display: block;
  margin-bottom: 0.75rem;
}

.table-scroll {
  overflow-x: auto;
}

table {
  border-collapse: collapse;
  width: 100%;
}

th, td {
  border: 1px solid var(--border);
  padding: 0.5rem 0.75rem;
  text-align: left;
}

th {
  background: var(--bg-elevated);
}

.error {
  background: var(--error-bg);
  color: var(--error-fg);
  border-radius: 0.375rem;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
}

nav[aria-label="Pagination"] {
  display: flex;
  gap: 1rem;
  align-items: center;
  margin-top: 1rem;
}

:focus-visible {
  outline: 3px solid var(--focus-ring);
  outline-offset: 2px;
}

@media (max-width: 30rem) {
  header {
    flex-direction: column;
    align-items: stretch;
  }
}
```

- [ ] **Step 7: Write theme.js**

Create `app/web/static/theme.js`:

```js
(function () {
  var toggle = document.getElementById("theme-toggle");
  if (!toggle) return;

  function currentTheme() {
    return (
      document.documentElement.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    );
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    toggle.setAttribute("aria-pressed", String(theme === "dark"));
    toggle.textContent = theme === "dark" ? "Light mode" : "Dark mode";
  }

  applyTheme(currentTheme());

  toggle.addEventListener("click", function () {
    var next = currentTheme() === "dark" ? "light" : "dark";
    localStorage.setItem("theme", next);
    applyTheme(next);
  });
})();
```

- [ ] **Step 8: Rewrite base.html**

Modify `app/web/templates/base.html` (replace the whole file):

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CareerSpyder</title>
  <script>
    (function () {
      var stored = localStorage.getItem("theme");
      if (stored === "dark" || stored === "light") {
        document.documentElement.setAttribute("data-theme", stored);
      }
    })();
  </script>
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/theme.js" defer></script>
</head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>
  <header>
    <nav aria-label="Main">
      <a href="/" {% if request.url.path == "/" %}aria-current="page"{% endif %}>Dashboard</a>
      <a href="/history" {% if request.url.path == "/history" %}aria-current="page"{% endif %}>History</a>
      <a href="/sources" {% if request.url.path.startswith("/sources") %}aria-current="page"{% endif %}>Sources</a>
      <a href="/settings" {% if request.url.path == "/settings" %}aria-current="page"{% endif %}>Settings</a>
    </nav>
    <button id="theme-toggle" type="button" aria-pressed="false">Dark mode</button>
  </header>
  <main id="main">
    {% block content %}{% endblock %}
  </main>
  <footer>
    <p>{{ app_name }} v{{ app_version }}</p>
  </footer>
</body>
</html>
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/web/test_base.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 10: Run the full suite to check nothing else broke**

Run: `pytest -q`
Expected: PASS — other `tests/web/*` tests assert on substrings like specific field text, not the removed `<nav>|<a href="/">Dashboard</a>` markup, so they should be unaffected. If any test asserts on old `base.html` markup verbatim, fix it to match the new markup.

- [ ] **Step 11: Commit**

```bash
git add app/web/static app/web/templating.py app/web/main.py app/web/templates/base.html pyproject.toml tests/web/test_base.py
git commit -m "feat: add responsive/dark-mode/a11y foundation shell and version footer"
```

---

### Task 2: Table accessibility — scoped headers and scroll wrapper

**Files:**
- Modify: `app/web/templates/history.html`
- Modify: `app/web/templates/sources_list.html`
- Test: Modify `tests/web/test_history.py`
- Test: Modify `tests/web/test_sources_list.py`

Only these two templates currently render `<table>` elements.

**Interfaces:**
- Produces: both templates now wrap their `<table>` in `<div class="table-scroll">...</div>` and every `<th>` carries `scope="col"` — Task 5 and Task 6 build their pagination `<nav>` immediately after this wrapper `</div>`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_history.py`:

```python
def test_history_table_has_scoped_headers_and_scroll_wrapper(client):
    resp = client.get("/history")

    assert 'scope="col"' in resp.text
    assert 'class="table-scroll"' in resp.text
```

Add to `tests/web/test_sources_list.py`:

```python
def test_sources_table_has_scoped_headers_and_scroll_wrapper(client):
    resp = client.get("/sources")

    assert 'scope="col"' in resp.text
    assert 'class="table-scroll"' in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_history.py tests/web/test_sources_list.py -v`
Expected: FAIL on the two new tests (`scope="col"` and `table-scroll` absent).

- [ ] **Step 3: Update history.html**

Modify `app/web/templates/history.html` (replace the whole file):

```html
{% extends "base.html" %}
{% block content %}
<h1>Run history</h1>
<div class="table-scroll">
<table border="1" cellpadding="4">
  <tr><th scope="col">Started</th><th scope="col">Finished</th><th scope="col">New jobs</th><th scope="col">Failed sources</th></tr>
  {% for run in runs %}
  <tr>
    <td>{{ run.started_at }}</td>
    <td>{{ run.finished_at or "in progress" }}</td>
    <td>{{ run.new_job_count }}</td>
    <td>{{ run.failed_sources | join(", ") }}</td>
  </tr>
  {% endfor %}
</table>
</div>
{% endblock %}
```

- [ ] **Step 4: Update sources_list.html**

Modify `app/web/templates/sources_list.html` (replace the whole file):

```html
{% extends "base.html" %}
{% block content %}
<h1>Sources</h1>
<a href="/sources/new">Add source</a>
<div class="table-scroll">
<table border="1" cellpadding="4">
  <tr><th scope="col">Name</th><th scope="col">Type</th><th scope="col">Company</th><th scope="col"></th><th scope="col"></th></tr>
  {% for s in sources %}
  <tr>
    <td>{{ s.name }}</td>
    <td>{{ s.type }}</td>
    <td>{{ s.company or "" }}</td>
    <td><a href="/sources/{{ s.id }}/edit">Edit</a></td>
    <td>
      <form method="post" action="/sources/{{ s.id }}/delete" style="display:inline">
        <button type="submit">Delete</button>
      </form>
    </td>
  </tr>
  {% endfor %}
</table>
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/web/test_history.py tests/web/test_sources_list.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/web/templates/history.html app/web/templates/sources_list.html tests/web/test_history.py tests/web/test_sources_list.py
git commit -m "feat: add scoped table headers and horizontal-scroll wrapper for a11y"
```

---

### Task 3: Pagination helper

**Files:**
- Create: `app/web/pagination.py`
- Test: Create `tests/web/test_pagination.py`

**Interfaces:**
- Produces: `paginate(total: int, page: object, page_size: int = 25) -> Pagination`, and the `Pagination` dataclass with fields `page: int`, `total_pages: int`, `offset: int`, `has_prev: bool`, `has_next: bool`. Task 5 and Task 6 call this directly; the templates in those tasks read `pagination.page`, `pagination.total_pages`, `pagination.has_prev`, `pagination.has_next`.

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_pagination.py`:

```python
from app.web.pagination import paginate


def test_middle_page_computes_correct_offset():
    result = paginate(total=100, page=3, page_size=25)

    assert result.page == 3
    assert result.offset == 50
    assert result.total_pages == 4
    assert result.has_prev is True
    assert result.has_next is True


def test_page_zero_clamps_to_one():
    result = paginate(total=100, page=0, page_size=25)

    assert result.page == 1
    assert result.offset == 0
    assert result.has_prev is False


def test_negative_page_clamps_to_one():
    result = paginate(total=100, page=-5, page_size=25)

    assert result.page == 1


def test_non_numeric_page_clamps_to_one():
    result = paginate(total=100, page="not-a-number", page_size=25)

    assert result.page == 1


def test_page_beyond_last_clamps_to_last_page():
    result = paginate(total=100, page=999, page_size=25)

    assert result.page == 4
    assert result.has_next is False


def test_empty_total_has_one_page():
    result = paginate(total=0, page=1, page_size=25)

    assert result.total_pages == 1
    assert result.page == 1
    assert result.has_prev is False
    assert result.has_next is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_pagination.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.web.pagination'`

- [ ] **Step 3: Implement pagination.py**

Create `app/web/pagination.py`:

```python
from dataclasses import dataclass


@dataclass
class Pagination:
    page: int
    total_pages: int
    offset: int
    has_prev: bool
    has_next: bool


def paginate(total: int, page: object, page_size: int = 25) -> Pagination:
    total_pages = max(1, -(-total // page_size))  # ceil(total / page_size), floored at 1

    try:
        page_num = int(page)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        page_num = 1

    page_num = max(1, min(page_num, total_pages))
    offset = (page_num - 1) * page_size

    return Pagination(
        page=page_num,
        total_pages=total_pages,
        offset=offset,
        has_prev=page_num > 1,
        has_next=page_num < total_pages,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_pagination.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Commit**

```bash
git add app/web/pagination.py tests/web/test_pagination.py
git commit -m "feat: add paginate() helper with graceful clamping of invalid page params"
```

---

### Task 4: Offset support for `db.list_runs` + `db.count_runs`

**Files:**
- Modify: `app/db.py:91-103`
- Test: Modify `tests/test_db.py`

**Interfaces:**
- Produces: `db.list_runs(conn, limit=50, offset=0) -> list[dict]` (new `offset` keyword, default preserves current behavior) and `db.count_runs(conn) -> int`. Task 5 calls both.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py`:

```python
def test_list_runs_respects_offset(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    ids = [db.start_run(conn) for _ in range(3)]
    for run_id in ids:
        db.finish_run(conn, run_id, new_job_count=0, failed_sources=[])

    page2 = db.list_runs(conn, limit=2, offset=2)

    assert [r["id"] for r in page2] == [ids[0]]


def test_count_runs_returns_total(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.start_run(conn)
    db.start_run(conn)

    assert db.count_runs(conn) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — `list_runs()` doesn't accept `offset`; `count_runs` doesn't exist.

- [ ] **Step 3: Implement the changes**

Modify `app/db.py`, replacing the existing `list_runs` function (currently lines 91-103):

```python
def list_runs(conn: sqlite3.Connection, limit: int = 50, offset: int = 0) -> list[dict]:
    rows = conn.execute(
        "SELECT id, started_at, finished_at, new_job_count, failed_sources "
        "FROM runs ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [
        {
            "id": r[0], "started_at": r[1], "finished_at": r[2],
            "new_job_count": r[3], "failed_sources": json.loads(r[4]),
        }
        for r in rows
    ]


def count_runs(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM runs").fetchone()
    return row[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: add offset support and count_runs to the run-history query"
```

---

### Task 5: Wire pagination into `/history`

**Files:**
- Modify: `app/web/routes_history.py`
- Modify: `app/web/templates/history.html`
- Test: Modify `tests/web/test_history.py`

**Interfaces:**
- Consumes: `db.list_runs(conn, limit, offset)`, `db.count_runs(conn)` (Task 4); `paginate(total, page, page_size)` (Task 3).

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_history.py`:

```python
def test_history_second_page_shows_older_runs(client):
    conn = client.app.state.conn
    for i in range(30):
        run_id = db.start_run(conn)
        db.finish_run(conn, run_id, new_job_count=i, failed_sources=[])

    page1 = client.get("/history?page=1")
    page2 = client.get("/history?page=2")

    assert "Page 1 of 2" in page1.text
    assert "Page 2 of 2" in page2.text


def test_history_invalid_page_param_clamps_instead_of_erroring(client):
    resp = client.get("/history?page=not-a-number")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_history_negative_page_param_clamps_to_first_page(client):
    resp = client.get("/history?page=-3")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_history.py -v`
Expected: FAIL — no pagination text is rendered yet.

- [ ] **Step 3: Update the route**

Modify `app/web/routes_history.py` (replace the whole file):

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app import db
from app.web.pagination import paginate
from app.web.templating import templates

router = APIRouter()

PAGE_SIZE = 25


@router.get("/history", response_class=HTMLResponse)
def history(request: Request, page: str = "1"):
    total = db.count_runs(request.app.state.conn)
    pagination = paginate(total, page, PAGE_SIZE)
    runs = db.list_runs(request.app.state.conn, limit=PAGE_SIZE, offset=pagination.offset)
    return templates.TemplateResponse(
        request, "history.html", {"runs": runs, "pagination": pagination}
    )
```

- [ ] **Step 4: Add pagination nav to the template**

Modify `app/web/templates/history.html`, adding a `<nav>` right after the closing `</div>` of `.table-scroll` (the file becomes):

```html
{% extends "base.html" %}
{% block content %}
<h1>Run history</h1>
<div class="table-scroll">
<table border="1" cellpadding="4">
  <tr><th scope="col">Started</th><th scope="col">Finished</th><th scope="col">New jobs</th><th scope="col">Failed sources</th></tr>
  {% for run in runs %}
  <tr>
    <td>{{ run.started_at }}</td>
    <td>{{ run.finished_at or "in progress" }}</td>
    <td>{{ run.new_job_count }}</td>
    <td>{{ run.failed_sources | join(", ") }}</td>
  </tr>
  {% endfor %}
</table>
</div>
<nav aria-label="Pagination">
  {% if pagination.has_prev %}<a href="/history?page={{ pagination.page - 1 }}">Previous</a>{% endif %}
  <span>Page {{ pagination.page }} of {{ pagination.total_pages }}</span>
  {% if pagination.has_next %}<a href="/history?page={{ pagination.page + 1 }}">Next</a>{% endif %}
</nav>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/web/test_history.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/web/routes_history.py app/web/templates/history.html tests/web/test_history.py
git commit -m "feat: paginate the /history table"
```

---

### Task 6: Wire pagination into `/sources`

**Files:**
- Modify: `app/web/routes_sources.py:1-17`
- Modify: `app/web/templates/sources_list.html`
- Test: Modify `tests/web/test_sources_list.py`

**Interfaces:**
- Consumes: `config.load_sources(path)` (existing, unchanged); `paginate(total, page, page_size)` (Task 3).

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_sources_list.py`:

```python
def test_sources_list_second_page_shows_remaining_sources(client):
    sources_path = client.app.state.sources_path
    sources = [
        {"id": f"s{i}", "name": f"Source {i}", "type": "greenhouse", "board_token": f"tok{i}"}
        for i in range(30)
    ]
    with open(sources_path, "w") as f:
        json.dump({"sources": sources}, f)

    page1 = client.get("/sources?page=1")
    page2 = client.get("/sources?page=2")

    assert "Page 1 of 2" in page1.text
    assert "Source 0" in page1.text
    assert "Source 0" not in page2.text
    assert "Page 2 of 2" in page2.text


def test_sources_list_invalid_page_param_clamps_instead_of_erroring(client):
    resp = client.get("/sources?page=abc")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_sources_list.py -v`
Expected: FAIL — no pagination text rendered yet.

- [ ] **Step 3: Update the route**

Modify `app/web/routes_sources.py`. Add this import alongside the existing ones at the top:

```python
from app.web.pagination import paginate
```

Replace the existing `list_sources` route (currently lines 14-17):

```python
PAGE_SIZE = 25


@router.get("/sources", response_class=HTMLResponse)
def list_sources(request: Request, page: str = "1"):
    all_sources = config.load_sources(request.app.state.sources_path)
    pagination = paginate(len(all_sources), page, PAGE_SIZE)
    sources = all_sources[pagination.offset : pagination.offset + PAGE_SIZE]
    return templates.TemplateResponse(
        request, "sources_list.html", {"sources": sources, "pagination": pagination}
    )
```

- [ ] **Step 4: Add pagination nav to the template**

Modify `app/web/templates/sources_list.html` (replace the whole file):

```html
{% extends "base.html" %}
{% block content %}
<h1>Sources</h1>
<a href="/sources/new">Add source</a>
<div class="table-scroll">
<table border="1" cellpadding="4">
  <tr><th scope="col">Name</th><th scope="col">Type</th><th scope="col">Company</th><th scope="col"></th><th scope="col"></th></tr>
  {% for s in sources %}
  <tr>
    <td>{{ s.name }}</td>
    <td>{{ s.type }}</td>
    <td>{{ s.company or "" }}</td>
    <td><a href="/sources/{{ s.id }}/edit">Edit</a></td>
    <td>
      <form method="post" action="/sources/{{ s.id }}/delete" style="display:inline">
        <button type="submit">Delete</button>
      </form>
    </td>
  </tr>
  {% endfor %}
</table>
</div>
<nav aria-label="Pagination">
  {% if pagination.has_prev %}<a href="/sources?page={{ pagination.page - 1 }}">Previous</a>{% endif %}
  <span>Page {{ pagination.page }} of {{ pagination.total_pages }}</span>
  {% if pagination.has_next %}<a href="/sources?page={{ pagination.page + 1 }}">Next</a>{% endif %}
</nav>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/web/test_sources_list.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/web/routes_sources.py app/web/templates/sources_list.html tests/web/test_sources_list.py
git commit -m "feat: paginate the /sources table"
```

---

### Task 7: Playwright e2e infrastructure + theme toggle test

**Files:**
- Create: `tests/web/e2e/__init__.py`
- Create: `tests/web/e2e/conftest.py`
- Create: `tests/web/e2e/test_theme_toggle.py`
- Modify: `.github/workflows/ci.yml:29-37`

**Interfaces:**
- Produces: session-scoped `live_server` fixture (yields the base URL string of a real running instance of the app, e.g. `"http://127.0.0.1:54321"`) and session-scoped `browser` fixture (a Playwright `Browser`), plus a function-scoped `page` fixture (a fresh Playwright `Page` per test, closed after). Task 8 reuses all three.

- [ ] **Step 1: Create the package marker**

Create `tests/web/e2e/__init__.py` (empty file).

- [ ] **Step 2: Write conftest.py (server + browser fixtures)**

Create `tests/web/e2e/conftest.py`:

```python
import json
import os
import socket
import threading
import time

import pytest
import uvicorn
from playwright.sync_api import sync_playwright


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("e2e")
    sources_path = tmp_path / "sources.json"
    sources_path.write_text(json.dumps({"sources": []}))

    env_overrides = {
        "CAREERSPYDER_DB_PATH": str(tmp_path / "state.db"),
        "CAREERSPYDER_SOURCES_PATH": str(sources_path),
        "RUN_HOUR": "8",
        "TZ": "UTC",
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "user",
        "EMAIL_FROM": "from@x.test",
        "EMAIL_TO": "to@x.test",
        "SMTP_PASSWORD": "secret",
    }
    previous = {k: os.environ.get(k) for k in env_overrides}
    os.environ.update(env_overrides)

    from app.web.main import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)
    for k, v in previous.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    p = browser.new_page()
    yield p
    p.close()
```

- [ ] **Step 3: Make sure the CI test job has a browser to drive**

Modify `.github/workflows/ci.yml`, in the `test` job (currently lines 29-37), add a browser install step between installing dependencies and running pytest:

```yaml
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: playwright install --with-deps chromium
      - run: pytest -q
```

- [ ] **Step 4: Write the theme toggle test**

Create `tests/web/e2e/test_theme_toggle.py`:

```python
def test_theme_toggle_switches_and_persists_across_reload(live_server, page):
    page.goto(live_server + "/")
    toggle = page.locator("#theme-toggle")

    toggle.click()
    first_theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert first_theme in ("dark", "light")
    expected_pressed = "true" if first_theme == "dark" else "false"
    assert toggle.get_attribute("aria-pressed") == expected_pressed

    toggle.click()
    second_theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert second_theme != first_theme
    assert second_theme in ("dark", "light")

    page.reload()
    persisted_theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert persisted_theme == second_theme
```

- [ ] **Step 5: Install chromium locally if needed, then run the test**

Run: `playwright install --with-deps chromium` (only if not already installed locally — see AGENTS.md)
Run: `pytest tests/web/e2e/test_theme_toggle.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tests/web/e2e/__init__.py tests/web/e2e/conftest.py tests/web/e2e/test_theme_toggle.py .github/workflows/ci.yml
git commit -m "test: add Playwright e2e infrastructure and a theme-toggle test"
```

---

### Task 8: Playwright e2e — keyboard tab order and responsive overflow

**Files:**
- Create: `tests/web/e2e/test_keyboard_navigation.py`
- Create: `tests/web/e2e/test_responsive_layout.py`

**Interfaces:**
- Consumes: `live_server` and `page` fixtures from `tests/web/e2e/conftest.py` (Task 7).

- [ ] **Step 1: Write the keyboard tab order test**

Create `tests/web/e2e/test_keyboard_navigation.py`:

```python
def test_tab_order_reaches_skip_link_first(live_server, page):
    page.goto(live_server + "/")

    page.keyboard.press("Tab")

    assert page.evaluate("document.activeElement.className") == "skip-link"


def test_tab_order_reaches_theme_toggle_after_skip_link_and_nav(live_server, page):
    page.goto(live_server + "/")

    # skip-link, then the 4 nav links (Dashboard/History/Sources/Settings), then the toggle
    for _ in range(6):
        page.keyboard.press("Tab")

    assert page.evaluate("document.activeElement.id") == "theme-toggle"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/web/e2e/test_keyboard_navigation.py -v`
Expected: FAIL (file doesn't exist until this step, so this simply confirms the test collects and runs against the current `base.html`; both should already pass once Task 1 landed — if `test_tab_order_reaches_theme_toggle_after_skip_link_and_nav` fails, the header's DOM order or tab count doesn't match Task 1's `base.html`, and this step is where that mismatch would first surface. Since Task 1 already implemented the matching markup, this is a verification run, not a red step — see next step.)

- [ ] **Step 3: Run it to verify it passes**

Run: `pytest tests/web/e2e/test_keyboard_navigation.py -v`
Expected: PASS (both tests)

- [ ] **Step 4: Write the responsive overflow test**

Create `tests/web/e2e/test_responsive_layout.py`:

```python
def test_no_horizontal_overflow_at_narrow_viewport(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/sources")

    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    inner_width = page.evaluate("window.innerWidth")

    assert scroll_width <= inner_width
```

- [ ] **Step 5: Run it**

Run: `pytest tests/web/e2e/test_responsive_layout.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: PASS — this is the full deliverable for issue #12; everything should be green.

- [ ] **Step 7: Commit**

```bash
git add tests/web/e2e/test_keyboard_navigation.py tests/web/e2e/test_responsive_layout.py
git commit -m "test: add keyboard tab-order and responsive-overflow e2e tests"
```

---

### Task 9: Changelog entry

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the entry**

Modify `CHANGELOG.md`, inserting a new bullet at the end of the `### Added` list under `## [Unreleased]` (immediately after the existing `findly` bullet, before the `## [0.1.0]` heading):

```markdown
- Enhanced web UI (#12): responsive layout down to narrow/mobile viewports,
  light/dark theme (follows `prefers-color-scheme` by default, with a
  manual toggle that persists via `localStorage`), accessibility
  improvements (skip-to-content link, semantic landmarks, scoped table
  headers, visible focus outlines, `aria-current` on the active nav link),
  server-side pagination on the `/history` and `/sources` tables (25 rows
  per page via `?page=`), and a footer showing the app name and version.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: document the enhanced FED UI (#12)"
```
