# Table Sorting & Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close GH #33 — add server-side column sorting and light filters to
the Jobs, Dashboard (run history), and Sources tables, per
`docs/superpowers/specs/2026-08-16-table-sorting-filters-design.md`.

**Architecture:** A shared `sort_url`/`query_url` pair of Jinja globals
(`app/web/query_params.py`) plus a `sort_th` macro handle URL-building and
markup for every sortable column across all three tables. Jobs and
Dashboard sort/filter happen in SQL (`app/db.py`, whitelisted column
maps to avoid injection); Sources sort/filter happen in Python over the
in-memory list `config.load_sources` already returns. Everything is a
GET query param (`sort`, `dir`, plus table-specific filter params) so
state is bookmarkable and survives refresh/back-forward.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, SQLite (`sqlite3`), vanilla
JS, hand-written CSS, pytest + httpx `TestClient`, Playwright
(`sync_api`) for e2e under `tests/web/e2e/`.

## Global Constraints

- TDD throughout: failing test → minimal implementation → passing test →
  commit, per task.
- Every `sort`/`direction` value that reaches a raw SQL string MUST go
  through a whitelist dict lookup with a safe fallback — never
  string-format a query param directly into `ORDER BY`.
- Calling any of `list_jobs`/`count_jobs`/`list_runs`/`count_runs` with
  no new keyword args must reproduce today's exact default ordering —
  existing tests assert specific row orders and must stay green
  unmodified.
- Templates render through the single shared `Jinja2Templates` instance
  in `app/web/templating.py` — never instantiate a new one.
- Run `pytest -q` after every task. Run `pytest tests/web/e2e -v`
  after any task touching JS/templates covered by e2e (Tasks 5, 8).
- Bump `pyproject.toml`'s version (`0.12.0` → `0.13.0`) as part of this
  branch, per this repo's one-minor-bump-per-PR convention.

---

### Task 1: Shared query-param helpers + sortable-header macro

**Files:**
- Create: `app/web/query_params.py`
- Create: `app/web/templates/_sort_header.html`
- Modify: `app/web/templating.py`
- Test: `tests/web/test_query_params.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: `query_url(request, path, **overrides) -> str`,
  `sort_url(request, path, field) -> str` — both registered as Jinja
  globals under those exact names. `sort_th(request, path, field,
  label)` Jinja macro in `_sort_header.html`, imported via `{% from
  "_sort_header.html" import sort_th %}`. Later tasks call these by
  name; don't rename.

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_query_params.py
from starlette.requests import Request

from app.web.query_params import query_url, sort_url


def _request(query_string: str = "") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/jobs",
        "query_string": query_string.encode(),
        "headers": [],
    }
    return Request(scope)


def test_query_url_with_no_overrides_and_no_existing_params():
    assert query_url(_request(), "/jobs") == "/jobs"


def test_query_url_adds_and_preserves_params():
    req = _request("company=Acme")
    assert query_url(req, "/jobs", page=2) in (
        "/jobs?company=Acme&page=2", "/jobs?page=2&company=Acme",
    )


def test_query_url_none_or_empty_override_removes_key():
    req = _request("page=2&company=Acme")
    result = query_url(req, "/jobs", page=None)
    assert "page=" not in result
    assert "company=Acme" in result


def test_sort_url_defaults_new_field_to_ascending():
    req = _request("")
    assert sort_url(req, "/jobs", "company") == "/jobs?sort=company&dir=asc"


def test_sort_url_toggles_active_ascending_field_to_descending():
    req = _request("sort=company&dir=asc")
    assert sort_url(req, "/jobs", "company") == "/jobs?sort=company&dir=desc"


def test_sort_url_toggles_active_descending_field_back_to_ascending():
    req = _request("sort=company&dir=desc")
    assert sort_url(req, "/jobs", "company") == "/jobs?sort=company&dir=asc"


def test_sort_url_switching_field_resets_to_ascending():
    req = _request("sort=company&dir=desc")
    assert sort_url(req, "/jobs", "title") == "/jobs?sort=title&dir=asc"


def test_sort_url_drops_page():
    req = _request("page=3&sort=company&dir=asc")
    assert "page=" not in sort_url(req, "/jobs", "title")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_query_params.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.web.query_params'`)

- [ ] **Step 3: Write the implementation**

```python
# app/web/query_params.py
from urllib.parse import urlencode

from starlette.requests import Request


def query_url(request: Request, path: str, **overrides: str | int | None) -> str:
    params = dict(request.query_params)
    for key, value in overrides.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = str(value)
    query = urlencode(params)
    return f"{path}?{query}" if query else path


def sort_url(request: Request, path: str, field: str) -> str:
    current_field = request.query_params.get("sort", "")
    current_dir = request.query_params.get("dir", "")
    if current_field == field:
        new_dir = "asc" if current_dir == "desc" else "desc"
    else:
        new_dir = "asc"
    return query_url(request, path, sort=field, dir=new_dir, page=None)
```

```python
# app/web/templating.py — add below the existing globals
from app.web.query_params import query_url, sort_url

templates.env.globals["query_url"] = query_url
templates.env.globals["sort_url"] = sort_url
```

```jinja
{# app/web/templates/_sort_header.html #}
{% macro sort_th(request, path, field, label) -%}
{%- set active = request.query_params.get('sort', '') == field -%}
{%- set desc = request.query_params.get('dir', '') == 'desc' -%}
<th scope="col"{% if active %} aria-sort="{{ 'descending' if desc else 'ascending' }}"{% endif %}><a href="{{ sort_url(request, path, field) }}">{{ label }}{% if active %} {{ '▼' if desc else '▲' }}{% endif %}</a></th>
{%- endmacro %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_query_params.py -v`
Expected: PASS (all 8 tests)

- [ ] **Step 5: Run full suite, commit**

```bash
pytest -q
git add app/web/query_params.py app/web/templates/_sort_header.html app/web/templating.py tests/web/test_query_params.py
git commit -m "Add shared sort/query URL helpers and sortable-header macro"
```

---

### Task 2: Jobs — DB layer sort + filter

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `list_jobs(conn, limit=25, offset=0, *, sort="", direction="", company=None, source_name=None, removed=None, emailed=None)`,
  `count_jobs(conn, *, company=None, source_name=None, removed=None, emailed=None)`,
  `list_job_source_names(conn) -> list[str]`. Task 3's route calls these
  exact names/signatures.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db.py — append
def test_list_jobs_sorts_by_company_ascending(conn):
    db.save_jobs(conn, [
        Job(key="a", title="T", url="u", company="Zeta", location=None,
            source_name="s", source_id="1", summary=None),
        Job(key="b", title="T", url="u", company="Acme", location=None,
            source_name="s", source_id="1", summary=None),
    ], db.start_run(conn))

    rows = db.list_jobs(conn, sort="company", direction="asc")

    assert [r["company"] for r in rows] == ["Acme", "Zeta"]


def test_list_jobs_default_ordering_unchanged_with_no_new_kwargs(conn):
    run_id = db.start_run(conn)
    db.save_jobs(conn, [Job(key="a", title="T", url="u", company="A", location=None,
                             source_name="s", source_id="1", summary=None)], run_id)
    db.save_jobs(conn, [Job(key="b", title="T", url="u", company="B", location=None,
                             source_name="s", source_id="1", summary=None)], run_id)

    rows = db.list_jobs(conn)

    assert [r["key"] for r in rows] == ["b", "a"]


def test_list_jobs_unrecognized_sort_falls_back_to_default(conn):
    db.save_jobs(conn, [Job(key="a", title="T", url="u", company="A", location=None,
                             source_name="s", source_id="1", summary=None)], db.start_run(conn))

    rows = db.list_jobs(conn, sort="'; DROP TABLE jobs; --")

    assert len(rows) == 1


def test_list_jobs_filters_by_company_substring_case_insensitive(conn):
    run_id = db.start_run(conn)
    db.save_jobs(conn, [Job(key="a", title="T", url="u", company="Acme Corp", location=None,
                             source_name="s", source_id="1", summary=None)], run_id)
    db.save_jobs(conn, [Job(key="b", title="T", url="u", company="Zenith", location=None,
                             source_name="s", source_id="1", summary=None)], run_id)

    rows = db.list_jobs(conn, company="acme")

    assert [r["key"] for r in rows] == ["a"]


def test_list_jobs_filters_by_removed_status(conn):
    run_id = db.start_run(conn)
    db.save_jobs(conn, [Job(key="a", title="T", url="u", company="A", location=None,
                             source_name="s", source_id="src", summary=None)], run_id)
    db.reconcile_jobs(conn, configured_source_ids=set(), succeeded_source_ids={"src"}, found_jobs=[])

    active = db.list_jobs(conn, removed="active")
    removed = db.list_jobs(conn, removed="removed")

    assert active == []
    assert len(removed) == 1


def test_list_jobs_filters_by_emailed_status(conn):
    run_id = db.start_run(conn)
    db.save_jobs(conn, [Job(key="a", title="T", url="u", company="A", location=None,
                             source_name="s", source_id="1", summary=None)], run_id)
    db.mark_emailed(conn, ["a"])

    assert len(db.list_jobs(conn, emailed="sent")) == 1
    assert db.list_jobs(conn, emailed="not_sent") == []


def test_count_jobs_respects_filters(conn):
    run_id = db.start_run(conn)
    db.save_jobs(conn, [Job(key="a", title="T", url="u", company="Acme", location=None,
                             source_name="s", source_id="1", summary=None)], run_id)

    assert db.count_jobs(conn, company="acme") == 1
    assert db.count_jobs(conn, company="nope") == 0


def test_list_job_source_names_returns_distinct_sorted_names(conn):
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        Job(key="a", title="T", url="u", company="A", location=None,
            source_name="Zeta Board", source_id="1", summary=None),
        Job(key="b", title="T", url="u", company="B", location=None,
            source_name="Acme Board", source_id="2", summary=None),
        Job(key="c", title="T", url="u", company="C", location=None,
            source_name="Acme Board", source_id="2", summary=None),
    ], run_id)

    assert db.list_job_source_names(conn) == ["Acme Board", "Zeta Board"]
```

Check `tests/test_db.py` for an existing `conn` fixture (likely in
`tests/conftest.py`) before writing these — reuse it rather than opening
a new connection inline.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v -k "sort or filter or source_names or count_jobs_respects"`
Expected: FAIL (`TypeError: list_jobs() got an unexpected keyword argument 'sort'`, `AttributeError: module 'app.db' has no attribute 'list_job_source_names'`)

- [ ] **Step 3: Write the implementation**

Replace `list_jobs`/`count_jobs` in `app/db.py` and add
`list_job_source_names`, per the exact column-whitelist, direction rule,
and filter semantics in the design spec's "Jobs" section (`_JOB_SORT_COLUMNS`,
`_job_filters_sql` shared by both functions). Keep the existing
`SELECT` column list unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (all, including pre-existing `test_db.py` cases —
regression check for the default-ordering constraint)

- [ ] **Step 5: Commit**

```bash
pytest -q
git add app/db.py tests/test_db.py
git commit -m "Add sort/filter support to Jobs DB queries"
```

---

### Task 3: Jobs — route + template

**Files:**
- Modify: `app/web/routes_jobs.py`
- Modify: `app/web/templates/jobs.html`
- Test: `tests/web/test_jobs.py`

**Interfaces:**
- Consumes: `db.list_jobs`/`count_jobs`/`list_job_source_names` (Task 2),
  `sort_th` macro (Task 1).
- Produces: nothing new consumed by later tasks (Jobs is a leaf page).

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_jobs.py — append
def test_jobs_page_sort_by_company_orders_rows(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="a", company="Zeta")], run_id)
    db.save_jobs(conn, [make_job(key="b", company="Acme")], run_id)

    resp = client.get("/jobs?sort=company&dir=asc")

    assert resp.text.index("Acme") < resp.text.index("Zeta")


def test_jobs_page_filters_by_company(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="a", company="Acme")], run_id)
    db.save_jobs(conn, [make_job(key="b", company="Zeta")], run_id)

    resp = client.get("/jobs?company=Acme")

    assert "Acme" in resp.text
    assert "Zeta" not in resp.text


def test_jobs_page_filter_dropdown_lists_distinct_source_names(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="a", source_name="Acme Board")], db.start_run(conn))

    resp = client.get("/jobs")

    assert '<option value="Acme Board"' in resp.text


def test_jobs_page_invalid_sort_does_not_error(client):
    resp = client.get("/jobs?sort=nonsense")

    assert resp.status_code == 200


def test_jobs_page_empty_filter_matches_none_renders_empty_table(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="a", company="Acme")], db.start_run(conn))

    resp = client.get("/jobs?company=NoSuchCompany")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text
    assert "Acme" not in resp.text


def test_jobs_page_clear_filters_link_hidden_when_no_filter_active(client):
    resp = client.get("/jobs")
    assert "Clear filters" not in resp.text


def test_jobs_page_clear_filters_link_shown_when_filter_active(client):
    resp = client.get("/jobs?company=Acme")
    assert 'href="/jobs"' in resp.text
    assert "Clear filters" in resp.text


def test_jobs_page_sortable_headers_have_aria_sort_when_active(client):
    resp = client.get("/jobs?sort=company&dir=asc")
    assert 'aria-sort="ascending"' in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_jobs.py -v -k "sort or filter or clear_filters or aria_sort"`
Expected: FAIL (route ignores the new query params; no `<select>`/filter
form/`sort_th` markup yet)

- [ ] **Step 3: Write the implementation**

`app/web/routes_jobs.py`: add `from fastapi import Query`; extend
`jobs()` with `sort: str = "", direction: str = Query("", alias="dir"),
company: str = "", source: str = "", removed: str = "", emailed: str =
""`; pass through to `count_jobs`/`list_jobs`; add `source_names =
db.list_job_source_names(...)`; add `filters` dict to context
(`{"company": company, "source": source, "removed": removed, "emailed":
emailed}`).

`app/web/templates/jobs.html`: add `{% from "_sort_header.html" import
sort_th %}` at top; replace the Company/Title/Date found/Age (days)
`<th>` cells with `{{ sort_th(request, '/jobs', 'company', 'Company')
}}` etc.; add the filter `<form>` above `.table-scroll` per the design
spec's Jobs section (text input, two selects, hidden sort/dir, submit,
conditional clear-filters link).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_jobs.py -v`
Expected: PASS (all, including every pre-existing test in the file)

- [ ] **Step 5: Commit**

```bash
pytest -q
git add app/web/routes_jobs.py app/web/templates/jobs.html tests/web/test_jobs.py
git commit -m "Add column sorting and filters to the Jobs page"
```

---

### Task 4: Dashboard history — DB layer sort + filter

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `list_runs(conn, limit=50, offset=0, *, sort="", direction="", failures=None)`,
  `count_runs(conn, *, failures=None)`. Task 5's route calls these exact
  signatures.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db.py — append
def test_list_runs_sorts_by_new_job_count_ascending(conn):
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=5, failed_sources=[])
    r2 = db.start_run(conn)
    db.finish_run(conn, r2, new_job_count=1, failed_sources=[])

    rows = db.list_runs(conn, sort="new_job_count", direction="asc")

    assert [r["new_job_count"] for r in rows] == [1, 5]


def test_list_runs_default_ordering_unchanged_with_no_new_kwargs(conn):
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=1, failed_sources=[])
    r2 = db.start_run(conn)
    db.finish_run(conn, r2, new_job_count=2, failed_sources=[])

    rows = db.list_runs(conn)

    assert [r["id"] for r in rows] == [r2, r1]


def test_list_runs_unrecognized_sort_falls_back_to_default(conn):
    db.start_run(conn)
    rows = db.list_runs(conn, sort="garbage")
    assert len(rows) == 1


def test_list_runs_filters_only_failures(conn):
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=0, failed_sources=["Bad Co"])
    r2 = db.start_run(conn)
    db.finish_run(conn, r2, new_job_count=0, failed_sources=[])

    only = db.list_runs(conn, failures="only")
    clean = db.list_runs(conn, failures="clean")

    assert [r["id"] for r in only] == [r1]
    assert [r["id"] for r in clean] == [r2]


def test_count_runs_respects_failures_filter(conn):
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=0, failed_sources=["Bad Co"])

    assert db.count_runs(conn, failures="only") == 1
    assert db.count_runs(conn, failures="clean") == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v -k "list_runs or count_runs_respects"`
Expected: FAIL (`TypeError: list_runs() got an unexpected keyword argument 'sort'`)

- [ ] **Step 3: Write the implementation**

Replace `list_runs`/`count_runs` in `app/db.py` per the design spec's
"Dashboard history" section (`_RUN_SORT_COLUMNS`, `id` fallback,
`_run_filters_sql` shared helper, `id {direction}` secondary tiebreaker).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
pytest -q
git add app/db.py tests/test_db.py
git commit -m "Add sort/filter support to run-history DB queries"
```

---

### Task 5: Dashboard — routes + templates + JS refresh fix

**Files:**
- Modify: `app/web/routes_dashboard.py`
- Modify: `app/web/templates/dashboard.html`
- Modify: `app/web/templates/_history_rows.html`
- Modify: `app/web/static/dashboard.js`
- Test: `tests/web/test_dashboard.py`
- Test: `tests/web/e2e/test_dashboard_rows_refresh.py` (one new case)

**Interfaces:**
- Consumes: `db.list_runs`/`count_runs` (Task 4), `sort_th`/`query_url`
  (Task 1).
- Produces: nothing new consumed by later tasks.

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_dashboard.py — append
def test_dashboard_sort_by_new_job_count_orders_rows(client):
    conn = client.app.state.conn
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=5, failed_sources=[])
    r2 = db.start_run(conn)
    db.finish_run(conn, r2, new_job_count=1, failed_sources=[])

    resp = client.get("/?sort=new_job_count&dir=asc")

    assert resp.text.index('data-label="New jobs">1') < resp.text.index('data-label="New jobs">5')


def test_dashboard_failures_filter_only_shows_failed_runs(client):
    conn = client.app.state.conn
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=0, failed_sources=["Bad Co"])
    r2 = db.start_run(conn)
    db.finish_run(conn, r2, new_job_count=0, failed_sources=[])

    resp = client.get("/?failures=only")

    assert "Bad Co" in resp.text
    assert "Page 1 of 1" in resp.text


def test_rows_endpoint_honors_sort_and_failures_params(client):
    conn = client.app.state.conn
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=0, failed_sources=["Bad Co"])
    r2 = db.start_run(conn)
    db.finish_run(conn, r2, new_job_count=0, failed_sources=[])

    resp = client.get("/rows?failures=clean")

    assert "Bad Co" not in resp.text


def test_dashboard_invalid_sort_and_failures_do_not_error(client):
    resp = client.get("/?sort=nonsense&failures=nonsense")
    assert resp.status_code == 200


def test_dashboard_pagination_link_preserves_active_filter(client):
    conn = client.app.state.conn
    for i in range(30):
        run_id = db.start_run(conn)
        db.finish_run(conn, run_id, new_job_count=0, failed_sources=[])

    resp = client.get("/?failures=clean&page=1")

    assert "failures=clean" in resp.text


def test_dashboard_js_uses_location_search_for_refresh(client):
    resp = client.get("/static/dashboard.js")
    assert "window.location.search" in resp.text
    assert "data-page" not in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_dashboard.py -v -k "sort or failures or pagination_link or location_search"`
Expected: FAIL

- [ ] **Step 3: Write the implementation**

`app/web/routes_dashboard.py`: `_dashboard_context(request, page, sort,
direction, failures)`; both `dashboard()` and `dashboard_rows()` declare
`sort: str = "", direction: str = Query("", alias="dir"), failures: str
= ""` and forward them.

`app/web/templates/dashboard.html`: add `{% from "_sort_header.html"
import sort_th %}`; insert the `failures` filter `<form>` (per design
spec) between `.history-toolbar` and `{% include "_history_rows.html"
%}`.

`app/web/templates/_history_rows.html`: `sort_th` for
Started/Finished/New jobs; drop the `data-page` attribute from the
`#history-rows` div; pagination links become `{{ query_url(request,
'/', page=pagination.page - 1) }}` / `+ 1`.

`app/web/static/dashboard.js`: in `refresh()`, replace the
`container.getAttribute("data-page")` line and URL-building with:

```js
function refresh() {
  return fetch("/rows" + window.location.search)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_dashboard.py -v`
Expected: PASS (all)

- [ ] **Step 5: Add and run the e2e regression case**

Append to `tests/web/e2e/test_dashboard_rows_refresh.py`:

```python
def test_refresh_request_preserves_current_query_string(live_server, page):
    captured = {}

    def handler(route):
        captured["url"] = route.request.url
        route.fulfill(
            status=200, content_type="text/html",
            body='<div id="history-rows"><div class="table-scroll"><table></table></div>'
                 '<nav aria-label="Pagination"><span>Page 1 of 1</span></nav></div>',
        )

    page.route("**/rows*", handler)
    page.goto(live_server + "/?failures=only")

    page.click("#refresh-history")
    page.wait_for_function("document.getElementById('history-status').textContent === 'Updated'")

    assert "failures=only" in captured["url"]
```

Run: `pytest tests/web/e2e/test_dashboard_rows_refresh.py -v`
Expected: PASS (all, including this new case and the 4 pre-existing ones)

- [ ] **Step 6: Commit**

```bash
pytest -q
git add app/web/routes_dashboard.py app/web/templates/dashboard.html app/web/templates/_history_rows.html app/web/static/dashboard.js tests/web/test_dashboard.py tests/web/e2e/test_dashboard_rows_refresh.py
git commit -m "Add column sorting and a failures filter to the Dashboard"
```

---

### Task 6: Sources — route + template (Python-side sort/filter)

**Files:**
- Modify: `app/web/routes_sources.py`
- Modify: `app/web/templates/sources_list.html`
- Test: `tests/web/test_sources_list.py`

**Interfaces:**
- Consumes: `sort_th`/`query_url` (Task 1), `config.load_sources`
  (existing).
- Produces: nothing new consumed by later tasks.

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_sources_list.py — append
def test_sources_list_sorts_by_name_ascending(client):
    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Zeta", "type": "greenhouse", "board_token": "z"},
            {"id": "s2", "name": "Acme", "type": "greenhouse", "board_token": "a"},
        ]}, f)

    resp = client.get("/sources?sort=name&dir=asc")

    assert resp.text.index("Acme") < resp.text.index("Zeta")


def test_sources_list_filters_by_type(client):
    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "A", "type": "greenhouse", "board_token": "a"},
            {"id": "s2", "name": "B", "type": "lever", "board_token": "b"},
        ]}, f)

    resp = client.get("/sources?type=lever")

    assert ">B<" in resp.text or "data-label=\"Name\">B" in resp.text
    assert "data-label=\"Name\">A" not in resp.text


def test_sources_list_type_filter_options_only_include_present_types(client):
    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "A", "type": "greenhouse", "board_token": "a"},
        ]}, f)

    resp = client.get("/sources")

    assert '<option value="greenhouse"' in resp.text
    assert '<option value="lever"' not in resp.text


def test_sources_list_invalid_sort_does_not_error(client):
    resp = client.get("/sources?sort=nonsense")
    assert resp.status_code == 200


def test_sources_list_second_page_still_shows_remaining_sources_unsorted(client):
    sources_path = client.app.state.sources_path
    sources = [
        {"id": f"s{i}", "name": f"Source {i}", "type": "greenhouse", "board_token": f"tok{i}"}
        for i in range(30)
    ]
    with open(sources_path, "w") as f:
        json.dump({"sources": sources}, f)

    page1 = client.get("/sources?page=1")

    assert "Source 0" in page1.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_sources_list.py -v -k "sort or filter or type"`
Expected: FAIL

- [ ] **Step 3: Write the implementation**

`app/web/routes_sources.py`: add `from fastapi import Query`; add
`_SOURCE_SORT_KEYS` dict; extend `list_sources()` with `sort: str = "",
direction: str = Query("", alias="dir"), source_type: str = Query("",
alias="type")`; compute `available_types` before filtering; filter by
`source_type` before pagination; sort (when `sort` is recognized) before
pagination, ascending by default; add `available_types` and `filters`
to the template context.

`app/web/templates/sources_list.html`: `{% from "_sort_header.html"
import sort_th %}`; `sort_th` for Name/Type/Company; filter `<form>`
(one `<select name="type">`, hidden sort/dir, submit, conditional clear
link).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_sources_list.py -v`
Expected: PASS (all, including every pre-existing test in the file)

- [ ] **Step 5: Commit**

```bash
pytest -q
git add app/web/routes_sources.py app/web/templates/sources_list.html tests/web/test_sources_list.py
git commit -m "Add column sorting and a type filter to the Sources page"
```

---

### Task 7: Styling

**Files:**
- Modify: `app/web/static/style.css`
- Test: `tests/web/test_base.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `.filter-bar` class used by Tasks 3/5/6's templates
  (already written by the time this task lands — CSS-only, order
  doesn't block prior tasks' tests since none assert on computed
  styles).

- [ ] **Step 1: Write the failing test**

```python
# tests/web/test_base.py — append
def test_style_css_has_filter_bar_and_sort_link_rules(client):
    resp = client.get("/static/style.css")

    assert ".filter-bar" in resp.text
    assert "th a" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_base.py::test_style_css_has_filter_bar_and_sort_link_rules -v`
Expected: FAIL

- [ ] **Step 3: Write the CSS**

Append to `app/web/static/style.css` (near `.history-toolbar`):

```css
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

th a {
  color: inherit;
  text-decoration: none;
}

th a:hover {
  text-decoration: underline;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/web/test_base.py::test_style_css_has_filter_bar_and_sort_link_rules -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
pytest -q
git add app/web/static/style.css tests/web/test_base.py
git commit -m "Style the new filter bars and sortable header links"
```

---

### Task 8: e2e — real-browser sort/filter interaction

**Files:**
- Create: `tests/web/e2e/test_table_sort_and_filter.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7, running against the real
  `live_server`.
- Produces: nothing (leaf task).

- [ ] **Step 1: Write the test**

```python
# tests/web/e2e/test_table_sort_and_filter.py
from app import db
from app.models import Job


def test_clicking_company_header_sorts_jobs_table(live_server, page):
    from app.web.main import app as _app  # noqa: F401  (ensures app import path is warm)

    page.goto(live_server + "/jobs")
    page.click("text=Company")
    page.wait_for_url("**sort=company*")

    assert "sort=company" in page.url
    assert "dir=asc" in page.url


def test_clicking_company_header_twice_toggles_direction(live_server, page):
    page.goto(live_server + "/jobs?sort=company&dir=asc")
    page.click("text=Company")
    page.wait_for_url("**dir=desc*")

    assert "dir=desc" in page.url


def test_submitting_jobs_filter_form_narrows_url_params(live_server, page):
    page.goto(live_server + "/jobs")
    page.fill('input[name="company"]', "Acme")
    page.click(".filter-bar button[type=submit]")
    page.wait_for_url("**company=Acme*")

    assert "company=Acme" in page.url
```

Adjust the `live_server` fixture usage/imports to match whatever exists
in `tests/web/e2e/conftest.py` (no new fixtures needed — reuse
`live_server`/`page`). If `page.click("text=Company")` is ambiguous
because "Company" also appears in the filter form's label, scope the
click with a more specific selector (e.g. `page.click("th a:has-text('Company')")`).

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/web/e2e/test_table_sort_and_filter.py -v`
Expected: FAIL (no `sort_th` links / filter form yet reachable if run
before Task 3 — but since Tasks 1-7 are already done by this point in
the plan, this should mostly pass immediately; treat any failure here
as a real bug in Task 3/6's markup, not an ordering issue)

- [ ] **Step 3: Fix any markup issues found, then re-run**

Run: `pytest tests/web/e2e/test_table_sort_and_filter.py -v`
Expected: PASS

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (unit + web + e2e)

- [ ] **Step 5: Commit**

```bash
git add tests/web/e2e/test_table_sort_and_filter.py
git commit -m "Add e2e coverage for table sorting and filtering"
```

---

### Task 9: Documentation + version bump

**Files:**
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/USAGE.md`
- Modify: `app/web/templates/guide.html`
- Test: `tests/web/test_guide.py` (spot-check, if it asserts table
  contents — otherwise no test changes needed for docs)

**Interfaces:**
- Consumes: nothing (docs only).
- Produces: nothing.

- [ ] **Step 1: Bump the version**

In `pyproject.toml`, change `version = "0.12.0"` to `version = "0.13.0"`.

- [ ] **Step 2: Update CHANGELOG.md**

Add above the existing `## [0.12.0]` entry:

```markdown
## [0.13.0] — 2026-08-16

### Added

- Column sorting (click a column header to sort ascending/descending)
  and light filters on the Jobs, Dashboard, and Sources tables — Jobs
  filters by company, source, removed/emailed status; Dashboard filters
  by whether a run had failed sources; Sources filters by type. All
  server-side and encoded in the URL, so results are correct across
  pagination and links are bookmarkable (issue #33).
```

- [ ] **Step 3: Update README.md**

In the Web UI table (~line 231-233), reword the `/`, `/jobs`, `/sources`
rows to mention sorting/filtering, e.g.:

```markdown
| `/` (Dashboard) | A **Run now** button (always triggers an immediate scrape, regardless of configured check days) at the top, plus a paginated, auto-refreshing, sortable/filterable table of past runs — start/finish time, new job count, failed source names. |
| `/jobs` | Every job CareerSpyder has ever found — sortable by company, title, date found, or age; filterable by company, source, removed/emailed status. Shows company, search name, linked title, location, dates found/removed, age, emailed status, and a summary where available. |
| `/sources` | Sortable/filterable-by-type table of configured sources with Edit/Delete actions (delete asks for confirmation via a themed dialog) and an **Add source** button. |
```

Also fix the architecture table (~line 90): remove `/history` from the
route list (`/`, `/jobs`, `/history`, `/sources`, `/settings` →
`/`, `/jobs`, `/sources`, `/settings`) — stale reference to a route
removed in #42.

- [ ] **Step 4: Update docs/USAGE.md**

Apply the same three-row wording update to its "Web UI tour" table
(mirrors README's).

- [ ] **Step 5: Update app/web/templates/guide.html**

Apply the same wording update to Dashboard/Sources rows in its "Web UI
tour" table, and add the missing Jobs row (pre-existing gap):

```html
<tr><td><a href="/jobs">Jobs</a></td><td>Every job CareerSpyder has ever
  found &mdash; sortable by company, title, date found, or age;
  filterable by company, source, removed/emailed status.</td></tr>
```

- [ ] **Step 6: Verify and commit**

```bash
pytest -q
git add pyproject.toml CHANGELOG.md README.md docs/USAGE.md app/web/templates/guide.html
git commit -m "Update docs and bump version to 0.13.0 for #33"
```

---

### Task 10: Final full-suite verification

**Files:** none (verification only)

- [ ] **Step 1:** `pytest -q` — expect all tests passing, 0 failures.
- [ ] **Step 2:** `pytest tests/web/e2e -v` — expect all e2e passing
  (already covered by Step 1, run in isolation as a final sanity check
  given these exercise a real chromium browser).
- [ ] **Step 3:** Manually smoke-test in a real browser (see
  `AGENTS.md`'s `uvicorn app.web.main:app --reload --port 8080`): visit
  `/jobs`, `/`, `/sources`; click each sortable header twice (ascending
  then descending); submit each filter form; use "Clear filters"; use
  Previous/Next while a filter is active and confirm it stays active.
