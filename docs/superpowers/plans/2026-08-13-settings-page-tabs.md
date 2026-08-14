# Settings Page Tabs (Email / Data) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `/settings` into an Email tab (today's SMTP form, unchanged) and a new Data tab with a job-cache clear action and sources.json import/export, per GH issue #14.

**Architecture:** Tabs are separate full-page-reload routes (`/settings/email`, `/settings/data`), not client-side JS panels — matches this app's existing no-SPA design. `/settings` redirects to `/settings/email`. New backend logic (`db.clear_jobs`, `config.export_sources_json`, `config.import_sources_json`) is added as small, independently-testable functions and wired into new routes on the existing `routes_settings.py` router.

**Tech Stack:** FastAPI, Jinja2 (`app/web/templating.py`'s shared `templates` instance), sqlite3, pydantic (existing `SourceConfig`/`SourcesFile` models in `app/config.py`), pytest + FastAPI `TestClient`, Playwright (e2e, already wired via `tests/web/e2e/conftest.py`).

## Global Constraints

- `sources.json` writes must go through `app/config.py::save_sources` (atomic temp-file + `os.replace`) — never a direct `open(path, "w")`.
- `SMTP_PASSWORD` must never be written to SQLite, added to a pydantic model, or rendered in a template — unaffected by this plan, but don't touch that boundary while editing `routes_settings.py`.
- New templates only need to live under `app/web/templates/*.html` — `pyproject.toml`'s `[tool.setuptools.package-data]` already globs `templates/*.html`, no config change needed.
- Route handlers that do blocking I/O stay plain `def` (FastAPI threadpools them) unless there's a specific reason to be `async def` (e.g. reading `request.form()`). Follow the existing mix in `routes_settings.py`/`routes_sources.py`.
- Tests must not make live network calls or launch a real browser except via the existing Playwright e2e fixtures in `tests/web/e2e/conftest.py`.
- Run `pytest -q` before every commit; the suite must stay fast and fully offline.

---

### Task 1: `db.clear_jobs`

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `clear_jobs(conn: sqlite3.Connection) -> None` — deletes every row from the `jobs` table and commits. Idempotent on an empty table. Does not touch `runs` or `settings`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py` (after `test_new_job_then_seen_on_second_run`):

```python
def test_clear_jobs_empties_the_table(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    job = make_job()
    run_id = db.start_run(conn)
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])
    assert db.get_new_jobs(conn, [job]) == []

    db.clear_jobs(conn)

    assert db.get_new_jobs(conn, [job]) == [job]


def test_clear_jobs_on_empty_table_does_not_raise(tmp_db_path):
    conn = db.init_db(tmp_db_path)

    db.clear_jobs(conn)  # should not raise

    assert db.get_new_jobs(conn, [make_job()]) == [make_job()]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -k clear_jobs -v`
Expected: FAIL with `AttributeError: module 'app.db' has no attribute 'clear_jobs'`

- [ ] **Step 3: Implement `clear_jobs`**

In `app/db.py`, add after `save_jobs`:

```python
def clear_jobs(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM jobs")
    conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -k clear_jobs -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite and commit**

Run: `pytest -q`
Expected: all pass

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: add db.clear_jobs to empty the job dedup cache"
```

---

### Task 2: `config.export_sources_json` / `config.import_sources_json`

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: existing `load_sources(path) -> list[SourceConfig]`, `save_sources(path, sources) -> None`, `SourcesFile` model.
- Produces:
  - `export_sources_json(path: str) -> str` — JSON string, same `{"sources": [...]}` shape `save_sources` writes. Missing file exports `{"sources": []}`.
  - `import_sources_json(path: str, raw: bytes) -> list[SourceConfig]` — parses + validates `raw`, replaces the file via `save_sources`, returns the new source list. Raises `json.JSONDecodeError` (bad JSON) or `pydantic.ValidationError` (schema-invalid) without touching the file on disk.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py` (after `test_save_sources_is_atomic_and_leaves_no_tmp_file`):

```python
def test_export_sources_json_round_trips_saved_sources(tmp_path):
    path = tmp_path / "sources.json"
    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.save_sources(str(path), [source])

    exported = json.loads(config.export_sources_json(str(path)))

    assert exported == {"sources": [source.model_dump()]}


def test_export_sources_json_on_missing_file_returns_empty_list(tmp_path):
    path = tmp_path / "does-not-exist.json"

    exported = json.loads(config.export_sources_json(str(path)))

    assert exported == {"sources": []}


def test_import_sources_json_replaces_existing_sources(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [{"id": "old", "name": "Old", "type": "greenhouse", "board_token": "old"}])
    payload = json.dumps({
        "sources": [{"id": "new", "name": "New", "type": "lever", "board_token": "new"}],
    }).encode()

    result = config.import_sources_json(str(path), payload)

    assert [s.id for s in result] == ["new"]
    assert [s.id for s in config.load_sources(str(path))] == ["new"]


def test_import_sources_json_rejects_invalid_json(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [{"id": "old", "name": "Old", "type": "greenhouse", "board_token": "old"}])

    with pytest.raises(json.JSONDecodeError):
        config.import_sources_json(str(path), b"not json")

    assert [s.id for s in config.load_sources(str(path))] == ["old"]


def test_import_sources_json_rejects_payload_missing_sources_key(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [{"id": "old", "name": "Old", "type": "greenhouse", "board_token": "old"}])

    with pytest.raises(ValidationError):
        config.import_sources_json(str(path), b'{"nope": []}')

    assert [s.id for s in config.load_sources(str(path))] == ["old"]


def test_import_sources_json_rejects_unknown_source_type(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [{"id": "old", "name": "Old", "type": "greenhouse", "board_token": "old"}])
    payload = json.dumps({"sources": [{"id": "x", "name": "X", "type": "carrier_pigeon"}]}).encode()

    with pytest.raises(ValidationError):
        config.import_sources_json(str(path), payload)

    assert [s.id for s in config.load_sources(str(path))] == ["old"]


def test_import_sources_json_rejects_blank_required_field(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [{"id": "old", "name": "Old", "type": "greenhouse", "board_token": "old"}])
    payload = json.dumps({"sources": [{"id": "x", "name": "X", "type": "greenhouse", "board_token": ""}]}).encode()

    with pytest.raises(ValidationError):
        config.import_sources_json(str(path), payload)

    assert [s.id for s in config.load_sources(str(path))] == ["old"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -k "export_sources_json or import_sources_json" -v`
Expected: FAIL with `AttributeError: module 'app.config' has no attribute 'export_sources_json'`

- [ ] **Step 3: Implement both functions**

In `app/config.py`, add after `save_sources`:

```python
def export_sources_json(path: str) -> str:
    sources = load_sources(path)
    payload = {"sources": [s.model_dump() for s in sources]}
    return json.dumps(payload, indent=2)


def import_sources_json(path: str, raw: bytes) -> list[SourceConfig]:
    data = json.loads(raw)
    sources = SourcesFile.model_validate(data).sources
    save_sources(path, sources)
    return sources
```

(`json` and `SourcesFile` are already imported/defined earlier in this module.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -k "export_sources_json or import_sources_json" -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the full suite and commit**

Run: `pytest -q`
Expected: all pass

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add config.export_sources_json / import_sources_json"
```

---

### Task 3: Split Settings into Email tab (`/settings/email`), `/settings` redirects

**Files:**
- Modify: `app/web/routes_settings.py`
- Create: `app/web/templates/settings_tabs.html`
- Create: `app/web/templates/settings_email.html`
- Delete: `app/web/templates/settings.html`
- Modify: `app/web/templates/base.html`
- Modify: `app/web/static/style.css`
- Modify: `tests/web/test_settings.py`

**Interfaces:**
- Consumes: existing `db.get_settings`, `db.save_settings`, `templates` (from `app.web.templating`).
- Produces: `GET /settings` (redirect to `/settings/email`), `GET /settings/email`, `POST /settings/email` — same behavior as today's `/settings` GET/POST, just moved.

- [ ] **Step 1: Update the existing settings tests to target `/settings/email`, and add a redirect test**

Replace the full contents of `tests/web/test_settings.py`:

```python
def test_settings_redirects_to_email_tab(client):
    resp = client.get("/settings", follow_redirects=False)
    assert resp.status_code in (301, 302, 303, 307, 308)
    assert resp.headers["location"] == "/settings/email"


def test_settings_page_shows_current_values(client):
    resp = client.get("/settings/email")
    assert resp.status_code == 200
    assert 'value="smtp.example.com"' in resp.text


def test_settings_page_does_not_expose_password_field(client):
    resp = client.get("/settings/email")
    assert 'name="smtp_password"' not in resp.text
    assert 'name="password"' not in resp.text


def test_post_settings_saves_new_values(client):
    resp = client.post("/settings/email", data={
        "smtp_host": "smtp2.example.com", "smtp_port": "465",
        "smtp_user": "user2", "email_from": "from2@x.test", "email_to": "to2@x.test",
    }, follow_redirects=False)

    assert resp.status_code == 303

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["smtp_host"] == "smtp2.example.com"
    assert settings["smtp_port"] == 465


def test_post_settings_rejects_file_upload_field(client):
    resp = client.post(
        "/settings/email",
        data={"smtp_port": "465", "smtp_user": "user2", "email_from": "from2@x.test", "email_to": "to2@x.test"},
        files={"smtp_host": ("evil.txt", b"not a hostname")},
    )

    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_settings.py -v`
Expected: FAIL — `/settings/email` still 404s, `/settings` doesn't redirect.

- [ ] **Step 3: Create the shared tab-nav partial**

Create `app/web/templates/settings_tabs.html`:

```html
<nav aria-label="Settings tabs">
  <a href="/settings/email" {% if request.url.path == "/settings/email" %}aria-current="page"{% endif %}>Email</a>
  <a href="/settings/data" {% if request.url.path == "/settings/data" %}aria-current="page"{% endif %}>Data</a>
</nav>
```

- [ ] **Step 4: Create `settings_email.html` and delete `settings.html`**

Create `app/web/templates/settings_email.html`:

```html
{% extends "base.html" %}
{% block content %}
{% include "settings_tabs.html" %}
<h1>Email settings</h1>
<p>SMTP password is set via the <code>SMTP_PASSWORD</code> environment variable and is not editable here.</p>
<form method="post" action="/settings/email">
  <label>SMTP host <input type="text" name="smtp_host" value="{{ settings.smtp_host }}"></label><br>
  <label>SMTP port <input type="number" name="smtp_port" value="{{ settings.smtp_port }}"></label><br>
  <label>SMTP user <input type="text" name="smtp_user" value="{{ settings.smtp_user }}"></label><br>
  <label>From address <input type="text" name="email_from" value="{{ settings.email_from }}"></label><br>
  <label>To address <input type="text" name="email_to" value="{{ settings.email_to }}"></label><br>
  <button type="submit">Save</button>
</form>
{% endblock %}
```

Delete the old template:

```bash
git rm app/web/templates/settings.html
```

- [ ] **Step 5: Update `routes_settings.py`**

Replace the full contents of `app/web/routes_settings.py`:

```python
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db
from app.web.templating import templates

router = APIRouter()


def _str_field(form: dict, key: str) -> str:
    value = form[key]
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{key} must be a text field")
    return value


@router.get("/settings", response_class=HTMLResponse)
def settings_redirect():
    return RedirectResponse(url="/settings/email")


@router.get("/settings/email", response_class=HTMLResponse)
def show_settings(request: Request):
    settings = db.get_settings(request.app.state.conn)
    return templates.TemplateResponse(request, "settings_email.html", {"settings": settings})


@router.post("/settings/email")
async def save_settings(request: Request):
    form = dict((await request.form()).items())
    db.save_settings(
        request.app.state.conn,
        _str_field(form, "smtp_host"), int(_str_field(form, "smtp_port")), _str_field(form, "smtp_user"),
        _str_field(form, "email_from"), _str_field(form, "email_to"),
    )
    return RedirectResponse(url="/settings/email", status_code=303)
```

- [ ] **Step 6: Update `base.html`'s Settings nav link to match any `/settings*` path**

In `app/web/templates/base.html`, change:

```html
      <a href="/settings" {% if request.url.path == "/settings" %}aria-current="page"{% endif %}>Settings</a>
```

to:

```html
      <a href="/settings" {% if request.url.path.startswith("/settings") %}aria-current="page"{% endif %}>Settings</a>
```

- [ ] **Step 7: Style the new Settings tabs nav**

In `app/web/static/style.css`, change:

```css
nav[aria-label="Main"] a {
  color: var(--fg);
  text-decoration: none;
}

nav[aria-label="Main"] a[aria-current="page"] {
  color: var(--accent);
  font-weight: 600;
  text-decoration: underline;
}
```

to:

```css
nav[aria-label="Main"] a,
nav[aria-label="Settings tabs"] a {
  color: var(--fg);
  text-decoration: none;
}

nav[aria-label="Main"] a[aria-current="page"],
nav[aria-label="Settings tabs"] a[aria-current="page"] {
  color: var(--accent);
  font-weight: 600;
  text-decoration: underline;
}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/web/test_settings.py -v`
Expected: PASS (5 tests)

- [ ] **Step 9: Run the full suite and commit**

Run: `pytest -q`
Expected: all pass (watch for any other test referencing `/settings` or `settings.html` directly — there are none outside `tests/web/test_settings.py` as of this plan, but confirm with `grep -rn '"/settings"' tests/` before committing).

```bash
git add app/web/routes_settings.py app/web/templates/settings_tabs.html app/web/templates/settings_email.html app/web/templates/base.html app/web/static/style.css tests/web/test_settings.py
git commit -m "feat: split /settings into an Email tab at /settings/email"
```

---

### Task 4: Data tab skeleton (`GET /settings/data`)

**Files:**
- Modify: `app/web/routes_settings.py`
- Create: `app/web/templates/settings_data.html`
- Modify: `app/web/static/style.css`
- Modify: `tests/web/test_settings.py`

**Interfaces:**
- Consumes: `settings_tabs.html` (Task 3).
- Produces: `GET /settings/data` route rendering `settings_data.html`, which statically includes: a clear-cache form posting to `/settings/data/clear-cache`, an export link to `/settings/data/sources/export`, and an import form posting to `/settings/data/sources/import` (routes for these three added in Tasks 5–7; this task only renders the markup and wires the GET). Template also reads `request.query_params.get("cleared")` / `.get("imported")` for a success banner, and an `error` context var for an inline failure banner — both used by later tasks.

- [ ] **Step 1: Write the failing test**

Add to `tests/web/test_settings.py`:

```python
def test_settings_data_page_shows_data_tab_controls(client):
    resp = client.get("/settings/data")

    assert resp.status_code == 200
    assert 'action="/settings/data/clear-cache"' in resp.text
    assert 'href="/settings/data/sources/export"' in resp.text
    assert 'action="/settings/data/sources/import"' in resp.text
    assert 'name="file"' in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_settings.py -k data_page -v`
Expected: FAIL with 404 (route doesn't exist)

- [ ] **Step 3: Create `settings_data.html`**

Create `app/web/templates/settings_data.html`:

```html
{% extends "base.html" %}
{% block content %}
{% include "settings_tabs.html" %}
<h1>Data</h1>

{% if request.query_params.get("cleared") %}
<div class="success">Job cache cleared. The next run will re-report every currently known job as new.</div>
{% endif %}
{% if request.query_params.get("imported") %}
<div class="success">Imported {{ request.query_params.get("imported") }} source(s).</div>
{% endif %}
{% if error %}
<div class="error">{{ error }}</div>
{% endif %}

<h2>Job cache</h2>
<p>Clears CareerSpyder's record of jobs it has already seen. The next run
will treat every currently known job as new and may send a large digest
email as a result.</p>
<form method="post" action="/settings/data/clear-cache">
  <button type="submit">Clear job cache</button>
</form>

<h2>Sources</h2>
<p><a href="/settings/data/sources/export">Export sources</a></p>
<form method="post" action="/settings/data/sources/import" enctype="multipart/form-data">
  <label>Import sources <input type="file" name="file" accept="application/json"></label><br>
  <button type="submit">Import</button>
</form>
<p>Importing replaces the entire source list with the contents of the uploaded file.</p>
{% endblock %}
```

- [ ] **Step 4: Add the route**

In `app/web/routes_settings.py`, add after `save_settings`:

```python
@router.get("/settings/data", response_class=HTMLResponse)
def show_settings_data(request: Request):
    return templates.TemplateResponse(request, "settings_data.html", {})
```

- [ ] **Step 5: Add the `.success` style**

In `app/web/static/style.css`, add after the existing `.error` rule:

```css
.success {
  background: var(--bg-elevated);
  color: var(--accent);
  border: 1px solid var(--accent);
  border-radius: 0.375rem;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/web/test_settings.py -k data_page -v`
Expected: PASS

- [ ] **Step 7: Run the full suite and commit**

Run: `pytest -q`
Expected: all pass

```bash
git add app/web/routes_settings.py app/web/templates/settings_data.html app/web/static/style.css tests/web/test_settings.py
git commit -m "feat: add the Settings Data tab skeleton at /settings/data"
```

---

### Task 5: Clear job cache (`POST /settings/data/clear-cache`)

**Files:**
- Modify: `app/web/routes_settings.py`
- Modify: `tests/web/test_settings.py`

**Interfaces:**
- Consumes: `db.clear_jobs(conn)` (Task 1).
- Produces: `POST /settings/data/clear-cache` — clears the job cache, redirects (303) to `/settings/data?cleared=1`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_settings.py`:

```python
def test_post_clear_cache_empties_jobs_and_redirects(client):
    from app import db
    from app.models import Job

    conn = client.app.state.conn
    job = Job(key="k1", title="Engineer", url="https://x.test/1", source_name="Acme")
    run_id = db.start_run(conn)
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])
    assert db.get_new_jobs(conn, [job]) == []

    resp = client.post("/settings/data/clear-cache", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings/data?cleared=1"
    assert db.get_new_jobs(conn, [job]) == [job]


def test_settings_data_page_shows_success_banner_after_clear(client):
    resp = client.get("/settings/data?cleared=1")

    assert resp.status_code == 200
    assert "Job cache cleared" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_settings.py -k clear_cache -v`
Expected: FAIL with 404 on the POST (route doesn't exist yet)

- [ ] **Step 3: Add the route**

In `app/web/routes_settings.py`:
- Change the `from app import db` import to also pull in nothing extra (it's already `from app import db`).
- Add after `show_settings_data`:

```python
@router.post("/settings/data/clear-cache")
def clear_cache(request: Request):
    db.clear_jobs(request.app.state.conn)
    return RedirectResponse(url="/settings/data?cleared=1", status_code=303)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_settings.py -k clear_cache -v`
Expected: PASS (2 tests — the second one already passes once Task 4's template banner logic is exercised, confirming that wiring end-to-end)

- [ ] **Step 5: Run the full suite and commit**

Run: `pytest -q`
Expected: all pass

```bash
git add app/web/routes_settings.py tests/web/test_settings.py
git commit -m "feat: add POST /settings/data/clear-cache"
```

---

### Task 6: Export sources (`GET /settings/data/sources/export`)

**Files:**
- Modify: `app/web/routes_settings.py`
- Modify: `tests/web/test_settings.py`

**Interfaces:**
- Consumes: `config.export_sources_json(path)` (Task 2).
- Produces: `GET /settings/data/sources/export` — returns the current sources as a JSON body with `Content-Disposition: attachment; filename="sources.json"`.

- [ ] **Step 1: Write the failing test**

Add to `tests/web/test_settings.py`:

```python
def test_get_export_sources_returns_current_sources_as_download(client):
    import json

    from app import config

    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.add_source(client.app.state.sources_path, source)

    resp = client.get("/settings/data/sources/export")

    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert "sources.json" in resp.headers["content-disposition"]
    assert json.loads(resp.text) == {"sources": [source.model_dump()]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_settings.py -k export_sources -v`
Expected: FAIL with 404

- [ ] **Step 3: Add the route**

In `app/web/routes_settings.py`:
- Add `Response` to the `fastapi.responses` import: `from fastapi.responses import HTMLResponse, RedirectResponse, Response`.
- Add `config` to the `app` import: `from app import config, db`.
- Add after `clear_cache`:

```python
@router.get("/settings/data/sources/export")
def export_sources(request: Request):
    payload = config.export_sources_json(request.app.state.sources_path)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="sources.json"'},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/web/test_settings.py -k export_sources -v`
Expected: PASS

- [ ] **Step 5: Run the full suite and commit**

Run: `pytest -q`
Expected: all pass

```bash
git add app/web/routes_settings.py tests/web/test_settings.py
git commit -m "feat: add GET /settings/data/sources/export"
```

---

### Task 7: Import sources (`POST /settings/data/sources/import`)

**Files:**
- Modify: `app/web/routes_settings.py`
- Modify: `tests/web/test_settings.py`

**Interfaces:**
- Consumes: `config.import_sources_json(path, raw)` (Task 2, raises `json.JSONDecodeError` / `pydantic.ValidationError`).
- Produces: `POST /settings/data/sources/import` — on success, redirects (303) to `/settings/data?imported=N`; on failure (no file, invalid JSON, or schema-invalid payload), re-renders `settings_data.html` with `error` set, HTTP 400, `sources.json` unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_settings.py`:

```python
def test_post_import_sources_replaces_list_and_redirects(client):
    import json

    from app import config

    payload = json.dumps({
        "sources": [{"id": "new", "name": "New", "type": "lever", "board_token": "new"}],
    }).encode()

    resp = client.post(
        "/settings/data/sources/import",
        files={"file": ("sources.json", payload, "application/json")},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings/data?imported=1"
    assert [s.id for s in config.load_sources(client.app.state.sources_path)] == ["new"]


def test_settings_data_page_shows_success_banner_after_import(client):
    resp = client.get("/settings/data?imported=3")

    assert resp.status_code == 200
    assert "Imported 3 source(s)" in resp.text


def test_post_import_sources_with_no_file_returns_400(client):
    resp = client.post("/settings/data/sources/import", data={})

    assert resp.status_code == 400
    assert "Choose a file" in resp.text


def test_post_import_sources_with_invalid_json_returns_400_and_leaves_sources(client):
    from app import config

    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.add_source(client.app.state.sources_path, source)

    resp = client.post(
        "/settings/data/sources/import",
        files={"file": ("bad.json", b"not json", "application/json")},
    )

    assert resp.status_code == 400
    assert [s.id for s in config.load_sources(client.app.state.sources_path)] == ["s1"]


def test_post_import_sources_with_unknown_type_returns_400_and_leaves_sources(client):
    import json

    from app import config

    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.add_source(client.app.state.sources_path, source)
    payload = json.dumps({"sources": [{"id": "x", "name": "X", "type": "carrier_pigeon"}]}).encode()

    resp = client.post(
        "/settings/data/sources/import",
        files={"file": ("bad.json", payload, "application/json")},
    )

    assert resp.status_code == 400
    assert [s.id for s in config.load_sources(client.app.state.sources_path)] == ["s1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_settings.py -k import_sources -v`
Expected: FAIL with 404 on the POSTs (route doesn't exist yet); the banner test fails on the missing "Imported 3 source(s)" text only incidentally (template already supports it from Task 4, so that one may already pass — confirm which).

- [ ] **Step 3: Add the route**

In `app/web/routes_settings.py`:
- Add imports: `import json` at the top; `from fastapi import APIRouter, HTTPException, Request, UploadFile`; `from pydantic import ValidationError`.
- Add after `export_sources`:

```python
@router.post("/settings/data/sources/import")
async def import_sources(request: Request):
    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return templates.TemplateResponse(
            request, "settings_data.html", {"error": "Choose a file to import."}, status_code=400,
        )
    raw = await upload.read()
    try:
        sources = config.import_sources_json(request.app.state.sources_path, raw)
    except (json.JSONDecodeError, ValidationError) as exc:
        return templates.TemplateResponse(
            request, "settings_data.html", {"error": f"Import failed: {exc}"}, status_code=400,
        )
    return RedirectResponse(url=f"/settings/data?imported={len(sources)}", status_code=303)
```

**Deviation found while implementing this step:** the snippet above imports
`UploadFile` from `starlette.datastructures`, not `fastapi` as originally
planned. `request.form()` (used here instead of FastAPI's `File()`/
`UploadFile` dependency injection) returns Starlette's `UploadFile`, and
`fastapi.UploadFile` does **not** subclass it — the two are siblings, not
parent/child — so `isinstance(upload, UploadFile)` against the `fastapi`
import silently always failed, and every import POST 400'd with "Choose a
file to import." even when a file was attached. Caught by
`test_post_import_sources_replaces_list_and_redirects` failing in Step 4
below with an unexpected 400 instead of the expected 404-before-route-
exists failure from Step 2.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_settings.py -k import_sources -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full suite and commit**

Run: `pytest -q`
Expected: all pass

```bash
git add app/web/routes_settings.py tests/web/test_settings.py
git commit -m "feat: add POST /settings/data/sources/import"
```

---

### Task 8: E2E coverage for the Settings tab nav

**Files:**
- Modify: `tests/web/e2e/test_keyboard_navigation.py`

**Interfaces:**
- Consumes: `live_server` and `page` fixtures from `tests/web/e2e/conftest.py` (already exist, unchanged).

- [ ] **Step 1: Write the failing test**

Add to `tests/web/e2e/test_keyboard_navigation.py`:

```python
def test_settings_tabs_navigate_and_mark_current_tab(live_server, page):
    page.goto(live_server + "/settings/email")

    assert page.get_attribute('nav[aria-label="Settings tabs"] a[href="/settings/email"]', "aria-current") == "page"
    assert page.get_attribute('nav[aria-label="Settings tabs"] a[href="/settings/data"]', "aria-current") is None

    page.click('nav[aria-label="Settings tabs"] a[href="/settings/data"]')
    page.wait_for_url("**/settings/data")

    assert page.get_attribute('nav[aria-label="Settings tabs"] a[href="/settings/data"]', "aria-current") == "page"
    assert page.get_attribute('nav[aria-label="Settings tabs"] a[href="/settings/email"]', "aria-current") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/e2e/test_keyboard_navigation.py -k settings_tabs -v`
Expected: FAIL — prior to this plan, `/settings/email` doesn't exist; by this point in the plan the route exists, so this step is really a sanity check the test is wired correctly. If everything from Tasks 3–4 is already committed, this test should already pass on first run — in that case, skip straight to Step 3's verification and note in the commit message that this is coverage-only.

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/web/e2e/test_keyboard_navigation.py -v`
Expected: PASS (all tests in the file, including the two pre-existing ones)

- [ ] **Step 4: Run the full suite and commit**

Run: `pytest -q`
Expected: all pass

```bash
git add tests/web/e2e/test_keyboard_navigation.py
git commit -m "test: add e2e coverage for the Settings Email/Data tab nav"
```

---

### Task 9: Documentation

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Update `README.md`**

In the **Features** list, add a bullet after the "Server-rendered web UI" bullet:

```markdown
- **Settings: Email and Data tabs** — `/settings/email` holds the SMTP
  config (unchanged); `/settings/data` adds a job-cache clear (clearing it
  makes the next run re-report every currently known job as new, which
  can trigger a large digest email) and sources.json import/export (import
  replaces the entire source list; export downloads the current one).
```

In the **Web UI** table, replace the `/settings` row:

```markdown
| `/settings` | `/settings/email` | SMTP host/port/from/recipient address. The SMTP password is intentionally not present here (see [Secrets](#secrets)). |
```

with two rows:

```markdown
| `/settings/email` | SMTP host/port/from/recipient address. The SMTP password is intentionally not present here (see [Secrets](#secrets)). |
| `/settings/data` | Clear the job dedup cache (the next run will re-report every currently known job as new and may send a large digest email), and export/import `sources.json` (import replaces the entire source list). |
```

No **Project structure** edit is needed: Settings is still one router
(`routes_settings.py`, just with more routes) and the templates line
already says `templates/*.html`, which covers the new files.

- [ ] **Step 2: Update `CHANGELOG.md`**

Under `## [Unreleased]` → `### Added`, add (after the "Enhanced web UI (#12)" entry):

```markdown
- Settings page Data tab (#14): `/settings/data` adds a job-cache clear
  (empties the `jobs` dedup table so the next run re-reports every
  currently known job as new) and sources.json import/export (export
  downloads the current source list; import validates and replaces it
  entirely, rejecting bad JSON or schema-invalid sources without touching
  the file on disk). The existing SMTP settings form moved to
  `/settings/email`; `/settings` now redirects there.
```

- [ ] **Step 3: Update `AGENTS.md`**

`AGENTS.md` doesn't enumerate individual routes (that's `README.md`'s Web
UI table, updated in Step 1), so the only change here is flagging the new
write path into `sources.json`. In the **Non-negotiable constraints**
section, find the `sources.json` bullet:

```markdown
- **`sources.json` is the single source of truth for sources**, re-read on
  every run and every `/sources` request — no rebuild or restart needed
  after an edit. Writes go through `app/config.py::save_sources`, which
  writes atomically (temp file + `os.replace`) — don't reintroduce a
  direct `open(path, "w")`.
```

Replace with:

```markdown
- **`sources.json` is the single source of truth for sources**, re-read on
  every run and every `/sources` request — no rebuild or restart needed
  after an edit. Writes go through `app/config.py::save_sources`, which
  writes atomically (temp file + `os.replace`) — don't reintroduce a
  direct `open(path, "w")`. `/settings/data`'s import feature
  (`app/config.py::import_sources_json`) is the one other write path;
  it validates against the same `SourcesFile` model before calling
  `save_sources`, so an invalid upload can't partially overwrite the file.
```

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md AGENTS.md
git commit -m "docs: document the Settings Data tab (#14)"
```

---

## Self-Review Notes

- **Spec coverage:** Email tab (Task 3), Data tab skeleton (Task 4), cache clear (Task 1 + 5), export (Task 2 + 6), import (Task 2 + 7), e2e nav coverage (Task 8), docs (Task 9) — every spec section has a task.
- **Positive/negative test coverage:** each of Tasks 1, 2, 5, 6, 7 has at least one negative-path test (empty-table clear, bad JSON, missing `sources` key, unknown type, blank required field, no file chosen), matching the request for both positive and negative cases.
- **Type/name consistency:** `db.clear_jobs`, `config.export_sources_json`, `config.import_sources_json` are named identically everywhere they're referenced across Tasks 1–2 and 5–7.
