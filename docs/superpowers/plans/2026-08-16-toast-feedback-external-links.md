# Toast Feedback & External Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close GH #45 (toast confirmation on every save/update/delete) and
GH #46 (external job links open in a new tab with an icon indicator), per
`docs/superpowers/specs/2026-08-16-toast-feedback-external-links-design.md`.

**Architecture:** A new `app/web/flash.py::flash_redirect(path, message)`
helper wraps `RedirectResponse`, appending the message as a `?flash=`
query param. `base.html` renders a toast whenever that param is present;
a new `app/web/static/toast.js` auto-dismisses it and cleans the URL. All
7 mutating routes (Sources create/update/delete, Settings email save,
Settings preferences save, Settings/Data clear-cache and import) switch
to this helper, replacing Settings/Data's two ad hoc `?cleared=1`/
`?imported=N` inline banners. Separately, a new
`_external_link.html::external_link(url, label)` macro adds
`target="_blank" rel="noopener noreferrer"` plus a `↗` icon to the Jobs
table's title link — the only external link in the app today.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, vanilla JS, hand-written
CSS, pytest + httpx `TestClient`, Playwright (`sync_api`) for e2e under
`tests/web/e2e/`.

## Global Constraints

- TDD throughout: failing test → minimal implementation → passing test →
  commit, per task.
- Toast messages are server-authored constants only — never echo raw
  user input into a `flash` message (avoids any new reflected-content
  surface, even though Jinja autoescape would already neutralize it).
- `target="_blank"` must always be paired with `rel="noopener noreferrer"`
  — never emit one without the other.
- Templates render through the single shared `Jinja2Templates` instance
  in `app/web/templating.py` — never instantiate a new one.
- Run `pytest -q` after every task. Run `pytest tests/web/e2e -v` after
  Tasks 6 and 8 (JS/template-visible behavior).
- Bump `pyproject.toml`'s version (`0.13.0` → `0.14.0`) as part of this
  branch, per this repo's one-minor-bump-per-PR convention.

---

### Task 1: `flash_redirect` helper

**Files:**
- Create: `app/web/flash.py`
- Test: `tests/web/test_flash.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: `flash_redirect(path: str, message: str, status_code: int = 303) -> RedirectResponse`.
  Later tasks call this by name with exactly two positional args
  (`path`, `message`); don't rename.

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_flash.py
from urllib.parse import parse_qs, urlparse

from fastapi.responses import RedirectResponse

from app.web.flash import flash_redirect


def test_flash_redirect_returns_a_redirect_response():
    resp = flash_redirect("/sources", "Source added.")
    assert isinstance(resp, RedirectResponse)


def test_flash_redirect_defaults_to_303():
    resp = flash_redirect("/sources", "Source added.")
    assert resp.status_code == 303


def test_flash_redirect_appends_message_as_flash_query_param():
    resp = flash_redirect("/sources", "Source added.")
    location = urlparse(resp.headers["location"])
    assert location.path == "/sources"
    assert parse_qs(location.query)["flash"] == ["Source added."]


def test_flash_redirect_url_encodes_special_characters():
    resp = flash_redirect("/jobs", "50% done & more")
    location = urlparse(resp.headers["location"])
    assert parse_qs(location.query)["flash"] == ["50% done & more"]


def test_flash_redirect_accepts_a_custom_status_code():
    resp = flash_redirect("/sources", "Source added.", status_code=302)
    assert resp.status_code == 302
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_flash.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.web.flash'`)

- [ ] **Step 3: Write the implementation**

```python
# app/web/flash.py
from urllib.parse import urlencode

from fastapi.responses import RedirectResponse


def flash_redirect(path: str, message: str, status_code: int = 303) -> RedirectResponse:
    query = urlencode({"flash": message})
    return RedirectResponse(url=f"{path}?{query}", status_code=status_code)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_flash.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Run full suite, commit**

```bash
pytest -q
git add app/web/flash.py tests/web/test_flash.py
git commit -m "Add flash_redirect helper for toast messages"
```

---

### Task 2: Toast UI — markup, JS, CSS

**Files:**
- Modify: `app/web/templates/base.html`
- Create: `app/web/static/toast.js`
- Modify: `app/web/static/style.css`
- Test: `tests/web/test_base.py`

**Interfaces:**
- Consumes: nothing new (reads `request.query_params.get("flash")`
  directly — `request` is already in every template's context via
  FastAPI's `Jinja2Templates`).
- Produces: a `.toast` element (inside `#toast-container`) rendered on
  any page whenever the request's `flash` query param is non-empty.
  Task 3/4 rely on this appearing automatically once they redirect via
  `flash_redirect`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_base.py — append
def test_base_template_renders_toast_when_flash_param_present(client):
    resp = client.get("/jobs?flash=Test+message")

    assert 'id="toast-container"' in resp.text
    assert 'class="toast" role="status"' in resp.text
    assert "Test message" in resp.text
    assert 'class="toast-close"' in resp.text


def test_base_template_renders_no_toast_without_flash_param(client):
    resp = client.get("/jobs")

    assert 'class="toast" role="status"' not in resp.text


def test_base_template_renders_no_toast_with_empty_flash_param(client):
    resp = client.get("/jobs?flash=")

    assert 'class="toast" role="status"' not in resp.text


def test_toast_js_is_served(client):
    resp = client.get("/static/toast.js")

    assert resp.status_code == 200
    assert "toast-close" in resp.text
    assert "replaceState" in resp.text


def test_style_css_has_toast_rules(client):
    resp = client.get("/static/style.css")

    assert ".toast-container" in resp.text
    assert ".toast {" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_base.py -v -k toast`
Expected: FAIL (no toast markup/route/CSS yet)

- [ ] **Step 3: Write the implementation**

`app/web/templates/base.html` — add the toast container right before the
existing `<dialog id="confirm-modal">` element, and register the new
script tag next to `confirm-modal.js`:

```html
  <div id="toast-container" aria-live="polite" aria-atomic="true">
    {% if request.query_params.get("flash") %}
    <div class="toast" role="status">
      {{ request.query_params.get("flash") }}
      <button type="button" class="toast-close" aria-label="Dismiss">&times;</button>
    </div>
    {% endif %}
  </div>
  <dialog id="confirm-modal" class="modal">
```

and, next to the existing `<script src="/static/confirm-modal.js" defer></script>` line in `<head>`:

```html
  <script src="/static/toast.js" defer></script>
```

```javascript
// app/web/static/toast.js
(function () {
  var toast = document.querySelector(".toast");
  if (!toast) return;

  var timer = setTimeout(dismiss, 5000);

  function dismiss() {
    clearTimeout(timer);
    toast.remove();
    var url = new URL(window.location.href);
    url.searchParams.delete("flash");
    var next = url.pathname + (url.search || "") + url.hash;
    history.replaceState(null, "", next);
  }

  var closeBtn = toast.querySelector(".toast-close");
  if (closeBtn) closeBtn.addEventListener("click", dismiss);
})();
```

```css
/* app/web/static/style.css — append near .success/.error */
.toast-container {
  position: fixed;
  top: var(--space-4);
  right: var(--space-4);
  z-index: 100;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.toast {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  background: var(--success-bg);
  color: var(--success-fg);
  border-left: 4px solid var(--success-fg);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: var(--space-3) var(--space-4);
}

.toast-close {
  background: none;
  border: none;
  color: inherit;
  font-size: 1.1rem;
  line-height: 1;
  cursor: pointer;
  padding: 0;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_base.py -v`
Expected: PASS (all, including every pre-existing test in the file)

- [ ] **Step 5: Run full suite, commit**

```bash
pytest -q
git add app/web/templates/base.html app/web/static/toast.js app/web/static/style.css tests/web/test_base.py
git commit -m "Add floating toast UI driven by a flash query param"
```

---

### Task 3: Wire Sources create/update/delete to the toast

**Files:**
- Modify: `app/web/routes_sources.py`
- Test: `tests/web/test_source_form.py`
- Test: `tests/web/test_sources_list.py`

**Interfaces:**
- Consumes: `flash_redirect` (Task 1).
- Produces: nothing new consumed by later tasks.

- [ ] **Step 1: Update the existing test that breaks, and write the new failing tests**

`tests/web/test_source_form.py` — the existing
`test_post_new_source_saves_and_redirects` asserts an exact bare
`"/sources"` location; update it to allow the new `flash` query param,
and add a dedicated flash-message test right after it:

```python
def test_post_new_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "greenhouse", "name": "Acme", "company": "Acme Corp", "board_token": "acme",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/sources?flash=")
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["name"] == "Acme"
    assert saved[0]["board_token"] == "acme"


def test_post_new_source_redirect_carries_added_flash_message(client):
    from urllib.parse import parse_qs, urlparse

    resp = client.post("/sources/new", data={
        "type": "greenhouse", "name": "Acme", "company": "Acme Corp", "board_token": "acme",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    location = urlparse(resp.headers["location"])
    assert location.path == "/sources"
    assert parse_qs(location.query)["flash"] == ["Source added."]
```

Right after the existing `test_post_edit_updates_existing_source`, add:

```python
def test_post_edit_redirect_carries_saved_flash_message(client):
    from urllib.parse import parse_qs, urlparse

    with open(client.app.state.sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.post("/sources/s1/edit", data={
        "id": "s1", "type": "greenhouse", "name": "Acme Renamed", "board_token": "acme",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    location = urlparse(resp.headers["location"])
    assert location.path == "/sources"
    assert parse_qs(location.query)["flash"] == ["Source saved."]
```

`tests/web/test_source_form.py` — the existing
`test_post_new_source_with_empty_board_token_shows_error_and_does_not_save`
already asserts `status_code == 400` for a validation failure; add one
line confirming that failure path never renders a toast (validation
errors re-render inline, they never redirect through `flash_redirect`):

```python
def test_post_new_source_with_empty_board_token_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "greenhouse", "name": "Acme", "company": "Acme Corp", "board_token": "",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    assert "Add source" in resp.text
    assert 'class="toast" role="status"' not in resp.text
    with open(client.app.state.sources_path) as f:
        assert json.load(f)["sources"] == []
```

`tests/web/test_sources_list.py` — right after the existing
`test_delete_source_removes_it`, add:

```python
def test_delete_source_redirect_carries_deleted_flash_message(client):
    from urllib.parse import parse_qs, urlparse

    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme (Greenhouse)", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.post("/sources/s1/delete", follow_redirects=False)

    location = urlparse(resp.headers["location"])
    assert location.path == "/sources"
    assert parse_qs(location.query)["flash"] == ["Source deleted."]


def test_delete_unknown_source_does_not_redirect_with_flash(client):
    resp = client.post("/sources/does-not-exist/delete")

    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_source_form.py tests/web/test_sources_list.py -v -k "flash"`
Expected: FAIL (routes still return bare `RedirectResponse`)

- [ ] **Step 3: Write the implementation**

`app/web/routes_sources.py` — add the import and swap the three
`RedirectResponse` returns:

```python
from app.web.flash import flash_redirect
```

```python
@router.post("/sources/{source_id}/delete")
def delete_source(request: Request, source_id: str):
    try:
        config.delete_source(request.app.state.sources_path, source_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Source not found")
    return flash_redirect("/sources", "Source deleted.")
```

```python
@router.post("/sources/new")
async def create_source(request: Request):
    form = dict((await request.form()).items())
    try:
        source = source_from_form(form)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "source_form.html",
            {"source": echo_source(form), "action": "/sources/new", "error": str(exc)},
            status_code=400,
        )
    config.add_source(request.app.state.sources_path, source)
    return flash_redirect("/sources", "Source added.")
```

```python
@router.post("/sources/{source_id}/edit")
async def update_source(request: Request, source_id: str):
    form = dict((await request.form()).items())
    action = f"/sources/{source_id}/edit"
    try:
        source = source_from_form(form)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "source_form.html",
            {"source": echo_source(form), "action": action, "error": str(exc)},
            status_code=400,
        )
    source.id = source_id
    try:
        config.update_source(request.app.state.sources_path, source_id, source)
    except KeyError:
        raise HTTPException(status_code=404, detail="Source not found")
    return flash_redirect("/sources", "Source saved.")
```

(Only the final `return` line of each of these three functions changes;
everything else in `routes_sources.py` — including `test_source_preview`
— stays as-is.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_source_form.py tests/web/test_sources_list.py -v`
Expected: PASS (all, including every pre-existing test in both files)

- [ ] **Step 5: Run full suite, commit**

```bash
pytest -q
git add app/web/routes_sources.py tests/web/test_source_form.py tests/web/test_sources_list.py
git commit -m "Show a toast confirmation on Sources create/update/delete"
```

---

### Task 4: Wire Settings routes to the toast, retire the ad hoc banners

**Files:**
- Modify: `app/web/routes_settings.py`
- Modify: `app/web/templates/settings_data.html`
- Test: `tests/web/test_settings.py`

**Interfaces:**
- Consumes: `flash_redirect` (Task 1).
- Produces: nothing new consumed by later tasks.

- [ ] **Step 1: Update existing tests that break, remove obsolete banner tests, add new failing tests**

`tests/web/test_settings.py`:

1. Update `test_post_clear_cache_empties_jobs_and_redirects` (currently
   asserts `resp.headers["location"] == "/settings/data?cleared=1"`):

```python
def test_post_clear_cache_empties_jobs_and_redirects(client):
    from urllib.parse import parse_qs, urlparse

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
    location = urlparse(resp.headers["location"])
    assert location.path == "/settings/data"
    assert parse_qs(location.query)["flash"] == [
        "Job cache cleared. The next run will re-report every currently known job as new."
    ]
    assert db.get_new_jobs(conn, [job]) == [job]
```

2. Replace `test_settings_data_page_shows_success_banner_after_clear`
   (which asserts on the now-removed `?cleared=1` inline banner) with a
   full-flow toast check:

```python
def test_post_clear_cache_shows_toast_after_redirect(client):
    resp = client.post("/settings/data/clear-cache")

    assert resp.status_code == 200
    assert 'class="toast" role="status"' in resp.text
    assert "Job cache cleared" in resp.text
```

3. Update `test_post_import_settings_replaces_sources_and_redirects`
   (currently asserts `location == "/settings/data?imported=1"`):

```python
def test_post_import_settings_replaces_sources_and_redirects(client):
    import json
    from urllib.parse import parse_qs, urlparse

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
    location = urlparse(resp.headers["location"])
    assert location.path == "/settings/data"
    assert parse_qs(location.query)["flash"] == ["Imported 1 source(s)."]
    assert [s.id for s in config.load_sources(client.app.state.sources_path)] == ["new"]
```

4. Update `test_post_import_settings_with_preferences_overwrites_stored_preferences`
   (currently asserts `location == "/settings/data?imported=0&preferences=1"`):

```python
def test_post_import_settings_with_preferences_overwrites_stored_preferences(client):
    import json
    from urllib.parse import parse_qs, urlparse

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
    location = urlparse(resp.headers["location"])
    assert location.path == "/settings/data"
    assert parse_qs(location.query)["flash"] == ["Imported 0 source(s) and preferences."]
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_days"] == "tue,thu"
    assert settings["resend_jobs"] is False
    assert settings["email_to"] == "new@x.test"
```

5. Update `test_post_import_settings_without_preferences_key_leaves_stored_preferences_untouched`
   (currently asserts `location == "/settings/data?imported=0"`):

```python
def test_post_import_settings_without_preferences_key_leaves_stored_preferences_untouched(client):
    import json
    from urllib.parse import parse_qs, urlparse

    from app import db

    db.save_preferences(client.app.state.conn, "mon", True, "old@x.test")
    payload = json.dumps({"sources": []}).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    location = urlparse(resp.headers["location"])
    assert location.path == "/settings/data"
    assert parse_qs(location.query)["flash"] == ["Imported 0 source(s)."]
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_days"] == "mon"
    assert settings["resend_jobs"] is True
    assert settings["email_to"] == "old@x.test"
```

6. Replace both
   `test_settings_data_page_shows_success_banner_after_import_with_preferences`
   and `..._without_preferences` (which GET the now-removed
   `?imported=`/`?preferences=` query params directly) with full-flow
   toast checks:

```python
def test_post_import_settings_with_preferences_shows_toast_after_redirect(client):
    import json

    payload = json.dumps({
        "sources": [{"id": "s1", "name": "A", "type": "greenhouse", "board_token": "a"},
                    {"id": "s2", "name": "B", "type": "greenhouse", "board_token": "b"},
                    {"id": "s3", "name": "C", "type": "greenhouse", "board_token": "c"}],
        "preferences": {"email_days": ["mon"], "resend_jobs": False, "email_to": ["a@x.test"]},
    }).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
    )

    assert resp.status_code == 200
    assert "Imported 3 source(s) and preferences." in resp.text


def test_post_import_settings_without_preferences_shows_toast_after_redirect(client):
    import json

    payload = json.dumps({
        "sources": [{"id": "s1", "name": "A", "type": "greenhouse", "board_token": "a"},
                    {"id": "s2", "name": "B", "type": "greenhouse", "board_token": "b"},
                    {"id": "s3", "name": "C", "type": "greenhouse", "board_token": "c"}],
    }).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
    )

    assert resp.status_code == 200
    assert "Imported 3 source(s)." in resp.text
    assert "and preferences" not in resp.text
```

7. The existing
   `test_post_preferences_rejects_malformed_email_and_does_not_save` and
   `test_post_import_settings_with_invalid_json_returns_400_and_leaves_sources`
   already assert `status_code == 400` for their respective validation
   failures; add one line to each confirming no toast renders on that
   path either:

```python
def test_post_preferences_rejects_malformed_email_and_does_not_save(client):
    resp = client.post("/settings/preferences", data={
        "email_days": ["mon"], "email_to": ["not-an-email"],
    })

    assert resp.status_code == 400
    assert "Invalid email address" in resp.text
    assert 'class="toast" role="status"' not in resp.text

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings is None or settings["email_to"] != "not-an-email"
```

```python
def test_post_import_settings_with_invalid_json_returns_400_and_leaves_sources(client):
    from app import config

    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.add_source(client.app.state.sources_path, source)

    resp = client.post(
        "/settings/data/import",
        files={"file": ("bad.json", b"not json", "application/json")},
    )

    assert resp.status_code == 400
    assert 'class="toast" role="status"' not in resp.text
    assert [s.id for s in config.load_sources(client.app.state.sources_path)] == ["s1"]
```

8. Add flash-message tests for the two Settings save routes, right after
   `test_post_settings_saves_new_values` and
   `test_post_preferences_saves_days_resend_and_recipients` respectively:

```python
def test_post_settings_redirect_carries_saved_flash_message(client):
    from urllib.parse import parse_qs, urlparse

    resp = client.post("/settings/email", data={
        "smtp_host": "smtp2.example.com", "smtp_port": "465",
        "smtp_user": "user2", "email_from": "from2@x.test",
    }, follow_redirects=False)

    location = urlparse(resp.headers["location"])
    assert location.path == "/settings/email"
    assert parse_qs(location.query)["flash"] == ["Email settings saved."]
```

```python
def test_post_preferences_redirect_carries_saved_flash_message(client):
    from urllib.parse import parse_qs, urlparse

    resp = client.post("/settings/preferences", data={
        "email_days": ["mon", "wed", "fri"],
        "resend_jobs": "on",
        "email_to": ["a@x.test", "b@x.test"],
    }, follow_redirects=False)

    location = urlparse(resp.headers["location"])
    assert location.path == "/settings/preferences"
    assert parse_qs(location.query)["flash"] == ["Preferences saved."]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_settings.py -v -k "flash or toast"`
Expected: FAIL (routes still return bare `RedirectResponse`; the two
removed-banner tests should be deleted from the file, not left failing)

- [ ] **Step 3: Write the implementation**

`app/web/routes_settings.py` — add the import and swap the four
`RedirectResponse` returns:

```python
from app.web.flash import flash_redirect
```

```python
@router.post("/settings/email")
async def save_settings(request: Request):
    form = dict((await request.form()).items())
    db.save_settings(
        request.app.state.conn,
        _str_field(form, "smtp_host"), int(_str_field(form, "smtp_port")), _str_field(form, "smtp_user"),
        _str_field(form, "email_from"),
    )
    return flash_redirect("/settings/email", "Email settings saved.")
```

```python
    email_to = ",".join(submitted_emails)
    db.save_preferences(request.app.state.conn, email_days, resend_jobs, email_to)
    return flash_redirect("/settings/preferences", "Preferences saved.")
```

```python
@router.post("/settings/data/clear-cache")
def clear_cache(request: Request):
    db.clear_jobs(request.app.state.conn)
    return flash_redirect(
        "/settings/data",
        "Job cache cleared. The next run will re-report every currently known job as new.",
    )
```

```python
    redirect_message = f"Imported {len(sources)} source(s)."
    if parsed_preferences is not None:
        redirect_message = f"Imported {len(sources)} source(s) and preferences."
    return flash_redirect("/settings/data", redirect_message)
```

(This last change replaces the existing `redirect_url = f"/settings/data?imported={len(sources)}"` / `if parsed_preferences is not None: redirect_url += "&preferences=1"` / `return RedirectResponse(url=redirect_url, status_code=303)` block in `import_settings` — same `if`, different variable and message text.)

`app/web/templates/settings_data.html` — remove the two now-dead
banner blocks entirely (the global toast in `base.html` replaces them):

```html
{% if request.query_params.get("cleared") %}
<div class="success">Job cache cleared. The next run will re-report every currently known job as new.</div>
{% endif %}
{% if request.query_params.get("imported") %}
<div class="success">Imported {{ request.query_params.get("imported") }} source(s){% if request.query_params.get("preferences") %} and preferences{% endif %}.</div>
{% endif %}
```

The `{% if error %}` block directly below stays untouched.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_settings.py -v`
Expected: PASS (all, including every remaining pre-existing test in the file)

- [ ] **Step 5: Run full suite, commit**

```bash
pytest -q
git add app/web/routes_settings.py app/web/templates/settings_data.html tests/web/test_settings.py
git commit -m "Show a toast confirmation on Settings save/clear-cache/import"
```

---

### Task 5: External link macro on the Jobs table

**Files:**
- Create: `app/web/templates/_external_link.html`
- Modify: `app/web/templates/jobs.html`
- Test: `tests/web/test_jobs.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `external_link(url, label)` Jinja macro in
  `_external_link.html`, imported via `{% from "_external_link.html"
  import external_link %}`. No later task consumes it, but it's written
  as a reusable macro per the design spec.

- [ ] **Step 1: Write the failing tests**

```python
# tests/web/test_jobs.py — append
def test_jobs_page_title_link_opens_in_new_tab_with_icon(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job()], db.start_run(conn))

    resp = client.get("/jobs")

    assert 'target="_blank"' in resp.text
    assert 'rel="noopener noreferrer"' in resp.text
    assert "↗" in resp.text
    assert "(opens in new tab)" in resp.text


def test_jobs_page_internal_nav_link_is_not_target_blank(client):
    resp = client.get("/jobs")

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    nav_jobs_link = soup.select_one('nav[aria-label="Main"] a[href="/jobs"]')

    assert nav_jobs_link is not None
    assert nav_jobs_link.get("target") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_jobs.py -v -k "new_tab or nav_link"`
Expected: FAIL (`target="_blank"` not present yet)

- [ ] **Step 3: Write the implementation**

```jinja
{# app/web/templates/_external_link.html #}
{% macro external_link(url, label) -%}
<a href="{{ url }}" target="_blank" rel="noopener noreferrer">{{ label }} <span aria-hidden="true">&#8599;</span><span class="sr-only"> (opens in new tab)</span></a>
{%- endmacro %}
```

`app/web/templates/jobs.html` — add the import next to the existing
`_sort_header.html` import, and replace the Title cell:

```jinja
{% from "_sort_header.html" import sort_th %}
{% from "_external_link.html" import external_link %}
```

```jinja
    <td data-label="Title">{{ external_link(job.safe_url, job.title) }}</td>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_jobs.py -v`
Expected: PASS (all, including every pre-existing test in the file —
`test_jobs_page_lists_active_job`'s `'href="https://x.test/1"' in resp.text`
assertion still holds since the macro still emits that exact `href`)

- [ ] **Step 5: Run full suite, commit**

```bash
pytest -q
git add app/web/templates/_external_link.html app/web/templates/jobs.html tests/web/test_jobs.py
git commit -m "Open external job links in a new tab with an icon indicator"
```

---

### Task 6: e2e — real-browser toast and new-tab behavior

**Files:**
- Create: `tests/web/e2e/test_toast_and_external_links.py`

**Interfaces:**
- Consumes: everything from Tasks 1-5, running against the real
  `live_server`.
- Produces: nothing (leaf task).

- [ ] **Step 1: Write the test**

```python
# tests/web/e2e/test_toast_and_external_links.py
import os

from app import db
from app.models import Job


def test_toast_appears_after_deleting_a_source_and_can_be_dismissed(live_server, page):
    page.goto(live_server + "/sources/new")
    page.fill('input[name="name"]', "Toast Test Source")
    page.select_option('select[name="type"]', "greenhouse")
    page.fill('input[name="board_token"]', "toast-test")
    page.click('button[type="submit"]')
    page.wait_for_url("**/sources")

    row = page.locator("tr", has_text="Toast Test Source")
    row.locator('form[action$="/delete"] button[type="submit"]').click()
    page.click("#confirm-modal-confirm")
    page.wait_for_selector(".toast")

    assert page.locator(".toast").inner_text().strip().startswith("Source deleted.")

    page.click(".toast-close")
    page.wait_for_selector(".toast", state="detached")


def test_toast_auto_dismisses_without_manual_close(live_server, page):
    page.goto(live_server + "/settings/email")
    page.fill('input[name="smtp_host"]', "smtp.example.com")
    page.fill('input[name="smtp_port"]', "587")
    page.fill('input[name="smtp_user"]', "user")
    page.fill('input[name="email_from"]', "from@x.test")
    page.click('button[type="submit"]')

    page.wait_for_selector(".toast")
    page.wait_for_selector(".toast", state="detached", timeout=8000)


def test_clicking_job_title_opens_a_new_tab_to_the_job_url(live_server, page):
    conn = db.init_db(os.environ["CAREERSPYDER_DB_PATH"])
    job = Job(key="e2e-external-link", title="E2E External Link Job",
              url="https://example.com/job/e2e-external-link")
    run_id = db.start_run(conn)
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])

    page.context.route("https://example.com/**", lambda route: route.fulfill(
        status=200, content_type="text/html", body="<html><body>stub</body></html>",
    ))

    page.goto(live_server + "/jobs")
    with page.context.expect_page() as new_page_info:
        page.click("text=E2E External Link Job")
    new_page = new_page_info.value
    new_page.wait_for_load_state()

    assert new_page.url == "https://example.com/job/e2e-external-link"
    assert new_page != page
    new_page.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/web/e2e/test_toast_and_external_links.py -v`
Expected: FAIL if any Task 1-5 markup/behavior is wrong; otherwise PASS
immediately since Tasks 1-5 are already complete by this point in the
plan — treat any failure here as a real bug in an earlier task, not an
ordering issue.

- [ ] **Step 3: Fix any markup/behavior issues found, then re-run**

Run: `pytest tests/web/e2e/test_toast_and_external_links.py -v`
Expected: PASS

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: all tests pass (unit + web + e2e)

- [ ] **Step 5: Commit**

```bash
git add tests/web/e2e/test_toast_and_external_links.py
git commit -m "Add e2e coverage for toast confirmations and external job links"
```

---

### Task 7: Documentation + version bump

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

In `pyproject.toml`, change `version = "0.13.0"` to `version = "0.14.0"`.

- [ ] **Step 2: Update CHANGELOG.md**

`CHANGELOG.md` currently has an empty `## [Unreleased]` heading directly
above `## [0.13.0] — 2026-08-16`. Insert the new entry between them
(`## [Unreleased]` stays empty, as-is):

```markdown
## [0.14.0] — 2026-08-16

### Added

- A toast confirmation appears after every save, update, or delete
  action (adding/editing/deleting a source, saving email or preference
  settings, clearing the job cache, importing settings) — auto-dismisses
  after a few seconds or can be closed manually (issue #45).
- Job posting links on the Jobs page now open in a new tab and show a
  `↗` icon indicating they leave the app (issue #46).
```

- [ ] **Step 3: Update README.md**

In the `## Web UI` section (line 227), insert one new sentence between
the heading and the table (currently the heading is followed directly
by a blank line then the table header row):

```markdown
## Web UI

Every save, update, or delete action across these pages shows a brief
toast confirmation in the top-right corner.

| Page | Purpose |
```

Reword the `/jobs` row (line 232) to mention the new-tab behavior —
replace:

```markdown
| `/jobs` | Every job CareerSpyder has ever found — company, search name, linked title, location, dates found/removed, age, emailed status, and a summary where available. Sortable by company, title, date found, or age; filterable by company, source, and removed/emailed status. |
```

with:

```markdown
| `/jobs` | Every job CareerSpyder has ever found — company, search name, linked title (opens in a new tab), location, dates found/removed, age, emailed status, and a summary where available. Sortable by company, title, date found, or age; filterable by company, source, and removed/emailed status. |
```

- [ ] **Step 4: Update docs/USAGE.md**

In the `## Web UI tour` section (line 26), insert the same new sentence
between the heading and the table:

```markdown
## Web UI tour

Every save, update, or delete action across these pages shows a brief
toast confirmation in the top-right corner.

| Page | Purpose |
```

Reword the `Jobs (`/jobs`)` row (line 31) — replace:

```markdown
| Jobs (`/jobs`) | Every job ever found — company, search name, title/link, location, dates found/removed, age, emailed status, and a summary where available. Sortable by company, title, date found, or age; filterable by company, source, and removed/emailed status. |
```

with:

```markdown
| Jobs (`/jobs`) | Every job ever found — company, search name, title/link (opens in a new tab), location, dates found/removed, age, emailed status, and a summary where available. Sortable by company, title, date found, or age; filterable by company, source, and removed/emailed status. |
```

- [ ] **Step 5: Update app/web/templates/guide.html**

In `app/web/templates/guide.html`, the Jobs row of the "Web UI tour"
table (lines 30-32) currently reads:

```html
  <tr><td><a href="/jobs">Jobs</a></td><td>Every job CareerSpyder has ever found &mdash;
    sortable by company, title, date found, or age; filterable by company, source, and
    removed/emailed status.</td></tr>
```

Replace it with:

```html
  <tr><td><a href="/jobs">Jobs</a></td><td>Every job CareerSpyder has ever found &mdash;
    sortable by company, title, date found, or age; filterable by company, source, and
    removed/emailed status. Job titles open in a new tab.</td></tr>
```

- [ ] **Step 6: Verify and commit**

```bash
pytest -q
git add pyproject.toml CHANGELOG.md README.md docs/USAGE.md app/web/templates/guide.html
git commit -m "Update docs and bump version to 0.14.0 for #45, #46"
```

---

### Task 8: Final full-suite verification

**Files:** none (verification only)

- [ ] **Step 1:** `pytest -q` — expect all tests passing, 0 failures.
- [ ] **Step 2:** `pytest tests/web/e2e -v` — expect all e2e passing
  (already covered by Step 1, run in isolation as a final sanity check
  given these exercise a real chromium browser).
- [ ] **Step 3:** Manually smoke-test in a real browser (see
  `AGENTS.md`'s `uvicorn app.web.main:app --reload --port 8080`):
  - Add, edit, and delete a source — confirm a toast appears each time,
    auto-dismisses after ~5s, and can be closed early with the × button.
  - Save Settings → Email and Settings → Preferences — confirm each
    shows its own toast.
  - Settings → Data: clear the job cache and import a `settings.json` —
    confirm both show a toast (and that the old inline banners are gone).
  - On `/jobs` (with at least one job present, e.g. via a real scrape
    run or by pointing at a test source), confirm the title link shows
    a `↗` icon and opens the posting in a new browser tab.
