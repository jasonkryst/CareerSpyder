# Settings Import/Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Data tab's sources-only export/import to also cover Preferences-tab settings (`email_days`, `resend_jobs`, `email_to`), closing GH #29.

**Architecture:** `app/config.py::export_sources_json`/`import_sources_json` stay untouched (sources-only, file-backed). `app/web/routes_settings.py` renames the routes and wraps them: export additionally reads `db.get_settings` and nests a `preferences` object into the JSON; import calls the existing `config.import_sources_json` first (unchanged sources validation/failure behavior), then separately parses an optional top-level `preferences` key out of the same bytes and, if present, calls `db.save_preferences`.

**Tech Stack:** FastAPI route handlers, Jinja2 templates, pytest + `fastapi.testclient.TestClient` (existing patterns in this repo — no new dependencies).

## Global Constraints

- Payload shape: `{"sources": [...], "preferences": {"email_days": [...], "resend_jobs": bool, "email_to": [...]}}` — arrays, not the DB's internal CSV strings.
- Routes: `GET /settings/data/export`, `POST /settings/data/import` (renamed from `.../sources/export`, `.../sources/import`).
- Download filename: `settings.json` (was `sources.json`).
- `preferences` is optional on import: absent → stored preferences untouched. Present-but-malformed sub-fields → each falls back to its empty/`False` default individually, sources import still succeeds (no 400).
- Excluded from scope: theme, SMTP/Email-tab settings, job-cache-clear action.
- Spec: `docs/superpowers/specs/2026-08-16-settings-import-export-design.md`.

---

### Task 1: Rename and extend the export/import routes, with template and tests

**Files:**
- Modify: `app/web/routes_settings.py:91-116` (the `export_sources`/`import_sources` handlers)
- Modify: `app/web/templates/settings_data.html:26-34` (the "Sources" card)
- Modify: `tests/web/test_settings.py:180-307` (existing Data-tab tests)

**Interfaces:**
- Consumes: `config.load_sources(path) -> list[SourceConfig]`, `config.import_sources_json(path, raw: bytes) -> list[SourceConfig]` (raises `json.JSONDecodeError`/`ValidationError`), `db.get_settings(conn) -> dict | None` (keys: `email_days: str` CSV, `resend_jobs: bool`, `email_to: str` CSV), `db.save_preferences(conn, email_days: str, resend_jobs: bool, email_to: str) -> None`. `DAY_CODES` module-level list already in `routes_settings.py`.
- Produces: `GET /settings/data/export`, `POST /settings/data/import` routes. `_export_payload(request) -> dict` and `_parse_preferences_import(data: dict) -> tuple[str, bool, str] | None` helper functions in `routes_settings.py`, usable by later tasks/tests if needed (none currently planned).

- [ ] **Step 1: Update existing test assertions to the new routes and payload shape**

In `tests/web/test_settings.py`, apply these changes to existing tests:

```python
def test_settings_data_page_shows_data_tab_controls(client):
    resp = client.get("/settings/data")

    assert resp.status_code == 200
    assert 'action="/settings/data/clear-cache"' in resp.text
    assert 'href="/settings/data/export"' in resp.text
    assert 'action="/settings/data/import"' in resp.text
    assert 'name="file"' in resp.text
```

```python
def test_get_export_settings_returns_sources_and_preferences_as_download(client):
    import json

    from app import config

    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.add_source(client.app.state.sources_path, source)

    resp = client.get("/settings/data/export")

    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert "settings.json" in resp.headers["content-disposition"]
    body = json.loads(resp.text)
    assert body["sources"] == [source.model_dump()]
    assert body["preferences"] == {
        "email_days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "resend_jobs": False,
        "email_to": ["to@x.test"],
    }
```

(Renamed from `test_get_export_sources_returns_current_sources_as_download`; the fixture in `tests/web/conftest.py` sets `EMAIL_TO=to@x.test` and the app seeds it via `seed_settings_if_empty` at startup, with `email_days`/`resend_jobs` at their DB column defaults — this is why the expected `preferences` block above has those exact values.)

```python
def test_post_import_settings_replaces_sources_and_redirects(client):
    import json

    from app import config

    payload = json.dumps({
        "sources": [{"id": "new", "name": "New", "type": "lever", "board_token": "new"}],
    }).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings/data?imported=1"
    assert [s.id for s in config.load_sources(client.app.state.sources_path)] == ["new"]
```

(Renamed from `test_post_import_sources_replaces_list_and_redirects`; URL updated, no `preferences` key so the `&preferences=1` suffix is absent.)

```python
def test_post_import_settings_with_no_file_returns_400(client):
    resp = client.post("/settings/data/import", data={})

    assert resp.status_code == 400
    assert "Choose a file" in resp.text


def test_post_import_settings_with_invalid_json_returns_400_and_leaves_sources(client):
    from app import config

    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.add_source(client.app.state.sources_path, source)

    resp = client.post(
        "/settings/data/import",
        files={"file": ("bad.json", b"not json", "application/json")},
    )

    assert resp.status_code == 400
    assert [s.id for s in config.load_sources(client.app.state.sources_path)] == ["s1"]


def test_post_import_settings_with_unknown_source_type_returns_400_and_leaves_sources(client):
    import json

    from app import config

    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.add_source(client.app.state.sources_path, source)
    payload = json.dumps({"sources": [{"id": "x", "name": "X", "type": "carrier_pigeon"}]}).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("bad.json", payload, "application/json")},
    )

    assert resp.status_code == 400
    assert [s.id for s in config.load_sources(client.app.state.sources_path)] == ["s1"]
```

(All three renamed from their `sources`-URL originals, bodies otherwise unchanged.)

Now add new tests, appended after the renamed block:

```python
def test_post_import_settings_with_preferences_overwrites_stored_preferences(client):
    import json

    from app import db

    db.save_preferences(client.app.state.conn, "mon", True, "old@x.test")
    payload = json.dumps({
        "sources": [],
        "preferences": {
            "email_days": ["tue", "thu"],
            "resend_jobs": False,
            "email_to": ["new@x.test"],
        },
    }).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings/data?imported=0&preferences=1"
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_days"] == "tue,thu"
    assert settings["resend_jobs"] is False
    assert settings["email_to"] == "new@x.test"


def test_post_import_settings_without_preferences_key_leaves_stored_preferences_untouched(client):
    import json

    from app import db

    db.save_preferences(client.app.state.conn, "mon", True, "old@x.test")
    payload = json.dumps({"sources": []}).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings/data?imported=0"
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_days"] == "mon"
    assert settings["resend_jobs"] is True
    assert settings["email_to"] == "old@x.test"


def test_post_import_settings_with_malformed_preferences_falls_back_to_defaults(client):
    import json

    from app import db

    db.save_preferences(client.app.state.conn, "mon", True, "old@x.test")
    payload = json.dumps({
        "sources": [],
        "preferences": {"email_days": "mon", "resend_jobs": "yes", "email_to": "not-a-list@x.test"},
    }).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_days"] == ""
    assert settings["resend_jobs"] is False
    assert settings["email_to"] == ""


def test_settings_data_page_shows_success_banner_after_import_with_preferences(client):
    resp = client.get("/settings/data?imported=3&preferences=1")

    assert resp.status_code == 200
    assert "Imported 3 source(s) and preferences." in resp.text


def test_settings_data_page_shows_success_banner_after_import_without_preferences(client):
    resp = client.get("/settings/data?imported=3")

    assert resp.status_code == 200
    assert "Imported 3 source(s)." in resp.text
    assert "and preferences" not in resp.text
```

Delete the old `test_settings_data_page_shows_success_banner_after_import` (superseded by the two above).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/web/test_settings.py -v`
Expected: FAILs on every renamed-URL test (404, old routes still exist under the old paths) and every new preferences test (404 or `AssertionError` on missing `preferences` key/wrong redirect location).

- [ ] **Step 3: Implement the route changes**

Replace lines 91-116 of `app/web/routes_settings.py` (the `export_sources`/`import_sources` handlers) with:

```python
DEFAULT_PREFERENCES = {"email_days": [], "resend_jobs": False, "email_to": []}


def _export_payload(request: Request) -> dict:
    sources = config.load_sources(request.app.state.sources_path)
    settings = db.get_settings(request.app.state.conn)
    if settings is None:
        preferences = dict(DEFAULT_PREFERENCES)
    else:
        preferences = {
            "email_days": [d for d in settings["email_days"].split(",") if d],
            "resend_jobs": settings["resend_jobs"],
            "email_to": [a for a in settings["email_to"].split(",") if a],
        }
    return {"sources": [s.model_dump() for s in sources], "preferences": preferences}


def _parse_preferences_import(data: dict) -> tuple[str, bool, str] | None:
    preferences = data.get("preferences")
    if preferences is None:
        return None

    raw_days = preferences.get("email_days")
    days = raw_days if isinstance(raw_days, list) else []
    selected_days = {d for d in days if isinstance(d, str)} & set(DAY_CODES)
    email_days = ",".join(day for day in DAY_CODES if day in selected_days)

    resend_jobs = preferences.get("resend_jobs")
    if not isinstance(resend_jobs, bool):
        resend_jobs = False

    raw_emails = preferences.get("email_to")
    emails = raw_emails if isinstance(raw_emails, list) else []
    email_to = ",".join(addr.strip() for addr in emails if isinstance(addr, str) and addr.strip())

    return email_days, resend_jobs, email_to


@router.get("/settings/data/export")
def export_settings(request: Request):
    payload = json.dumps(_export_payload(request), indent=2)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="settings.json"'},
    )


@router.post("/settings/data/import")
async def import_settings(request: Request):
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

    parsed_preferences = _parse_preferences_import(json.loads(raw))
    if parsed_preferences is not None:
        email_days, resend_jobs, email_to = parsed_preferences
        db.save_preferences(request.app.state.conn, email_days, resend_jobs, email_to)

    redirect_url = f"/settings/data?imported={len(sources)}"
    if parsed_preferences is not None:
        redirect_url += "&preferences=1"
    return RedirectResponse(url=redirect_url, status_code=303)
```

This drops in exactly where the old `export_sources`/`import_sources` handlers were; no other part of the file changes. `Request` is already imported at the top of the file.

- [ ] **Step 4: Update the template**

In `app/web/templates/settings_data.html`, replace the "Sources" card (lines 26-34) with:

```html
<div class="card">
<h2>Export/Import settings</h2>
<p><a href="/settings/data/export">Export settings</a></p>
<form method="post" action="/settings/data/import" enctype="multipart/form-data">
  <label>Import settings <input type="file" name="file" accept="application/json"></label>
  <button type="submit">Import</button>
</form>
<p>Importing replaces the entire source list with the contents of the uploaded
file. Preferences (check days, resend, recipients) are only replaced if the
file includes a <code>preferences</code> section.</p>
</div>
```

And update the success-banner block near the top of the same file (currently `{% if request.query_params.get("imported") %}...{% endif %}`) to:

```html
{% if request.query_params.get("imported") %}
<div class="success">Imported {{ request.query_params.get("imported") }} source(s){% if request.query_params.get("preferences") %} and preferences{% endif %}.</div>
{% endif %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/web/test_settings.py -v`
Expected: PASS on all tests in the file.

- [ ] **Step 6: Run the full test suite**

Run: `pytest -q`
Expected: PASS (no other test file references the old `sources/export`/`sources/import` paths — confirmed by repo-wide search during design).

- [ ] **Step 7: Commit**

```bash
git add app/web/routes_settings.py app/web/templates/settings_data.html tests/web/test_settings.py
git commit -m "feat: include preferences in settings export/import (#29)"
```

---

### Task 2: Bump version and update the changelog

**Files:**
- Modify: `pyproject.toml:7`
- Modify: `CHANGELOG.md:1-8` (the `[Unreleased]` section)

**Interfaces:**
- Consumes: nothing from Task 1 beyond it being complete.
- Produces: nothing consumed by later tasks — this is the final task in the plan.

- [ ] **Step 1: Bump the version**

In `pyproject.toml`, change:

```toml
version = "0.8.0"
```
to:
```toml
version = "0.9.0"
```

- [ ] **Step 2: Update the changelog**

In `CHANGELOG.md`, replace:

```markdown
## [Unreleased]

## [0.8.0] — 2026-08-14
```

with:

```markdown
## [Unreleased]

## [0.9.0] — 2026-08-16

### Added

- Settings export/import (Data tab) now also covers Preferences-tab
  settings — check days, resend behavior, and digest recipients —
  alongside the existing source list, in one `settings.json` file
  (issue #29). `preferences` is optional in an uploaded file; if
  absent, stored preferences are left untouched, so old sources-only
  exports still import cleanly.

## [0.8.0] — 2026-08-14
```

- [ ] **Step 3: Verify the version is consistent**

Run: `grep -rn "0.8.0" pyproject.toml CHANGELOG.md`
Expected: no output (both files now reference `0.9.0` where the version appears; `0.8.0` only remains as a historical changelog heading, which the grep above will still show — confirm by eye that the only remaining `0.8.0` hits are the `## [0.8.0] — 2026-08-14` heading itself, not the `version =` line).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: bump version to 0.9.0"
```
