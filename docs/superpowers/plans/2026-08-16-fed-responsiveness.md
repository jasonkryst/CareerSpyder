# FED Responsiveness/UI/UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close GH #34 — six UI/UX fixes to CareerSpyder's web UI: a hamburger main menu on narrow screens, card-layout tables on narrow screens, a dark-mode fix for email inputs, client+server email validation, a confirm-before-import guard, and an auto-refreshing History page.

**Architecture:** Server-rendered Jinja2 templates (FastAPI + `TemplateResponse`), vanilla no-build-step JS (small IIFEs, one per concern, matching `theme.js`/`preferences.js`), and a single new CSS breakpoint (`40rem`) shared by the nav and table changes. The only new backend surface is `GET /history/rows`, a fragment endpoint reused by both the initial page render (via `{% include %}`) and client-side polling.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, SQLite, vanilla JS, pytest + `TestClient` (unit/integration), Playwright `sync_api` (e2e, via the existing `tests/web/e2e/conftest.py::live_server`/`browser`/`page` fixtures).

## Global Constraints

- New breakpoint: `40rem` (640px), used consistently for the hamburger nav and card tables. The existing `30rem` header-stacking breakpoint in `style.css` is untouched.
- No JS framework, no build step — plain `<script defer>` IIFEs served from `app/web/static/`, same pattern as `theme.js`/`preferences.js`.
- Every route/template change must leave all *existing* tests passing unmodified — this plan's tasks are additive or hidden above `40rem`; if a step would require editing an existing assertion, stop and re-check the design spec (`docs/superpowers/specs/2026-08-16-fed-responsiveness-design.md`) before proceeding.
- Server-side email validation regex: `^[^@\s]+@[^@\s]+\.[^@\s]+$` (loose by design — matches the codebase's existing level of validation rigor, e.g. `app/textutils.py::safe_url_scheme`).
- Version: `pyproject.toml` `0.9.0` → `0.10.0`.

---

### Task 1: Email field dark-mode CSS fix

**Files:**
- Modify: `app/web/static/style.css:224`
- Test: `tests/web/test_base.py`

**Interfaces:**
- Produces: nothing consumed by later tasks; fully standalone.

- [ ] **Step 1: Write the failing test**

Add to `tests/web/test_base.py`:

```python
def test_style_css_styles_email_inputs_like_text_inputs(client):
    resp = client.get("/static/style.css")

    assert resp.status_code == 200
    assert 'input[type="text"], input[type="email"], input[type="number"], select {' in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_base.py::test_style_css_styles_email_inputs_like_text_inputs -v`
Expected: FAIL (current rule is `input[type="text"], input[type="number"], select {`, no `email`).

- [ ] **Step 3: Fix the CSS rule**

In `app/web/static/style.css`, change:

```css
input[type="text"], input[type="number"], select {
```

to:

```css
input[type="text"], input[type="email"], input[type="number"], select {
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/web/test_base.py::test_style_css_styles_email_inputs_like_text_inputs -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/web/static/style.css tests/web/test_base.py
git commit -m "fix: style email inputs like text inputs so dark mode applies (#34)"
```

---

### Task 2: Hamburger main menu

**Files:**
- Modify: `app/web/templates/base.html:33-40`
- Create: `app/web/static/nav.js`
- Modify: `app/web/static/style.css` (new rules near `nav[aria-label="Main"]`, ~line 138-164)
- Test: `tests/web/test_base.py`
- Test (e2e): Create `tests/web/e2e/test_nav_menu.py`

**Interfaces:**
- Produces: `#nav-toggle` button (`aria-expanded`, `aria-controls="main-nav"`), `#main-nav` on the `<nav aria-label="Main">` element, `.open` class toggled on that nav by `nav.js`. No other task depends on this directly.

- [ ] **Step 1: Write the failing unit tests**

Add to `tests/web/test_base.py`:

```python
def test_base_layout_includes_nav_toggle_button(client):
    resp = client.get("/")

    assert 'id="nav-toggle"' in resp.text
    assert 'aria-controls="main-nav"' in resp.text
    assert 'aria-expanded="false"' in resp.text
    assert 'id="main-nav"' in resp.text


def test_nav_js_is_served(client):
    resp = client.get("/static/nav.js")

    assert resp.status_code == 200
    assert "nav-toggle" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_base.py -k nav_toggle -v`
Expected: FAIL — `nav-toggle` doesn't exist yet, `/static/nav.js` 404s.

- [ ] **Step 3: Add the toggle button and nav id to base.html**

In `app/web/templates/base.html`, replace:

```html
    <nav aria-label="Main">
      <a href="/" {% if request.url.path == "/" %}aria-current="page"{% endif %}>Dashboard</a>
      <a href="/jobs" {% if request.url.path == "/jobs" %}aria-current="page"{% endif %}>Jobs</a>
      <a href="/history" {% if request.url.path == "/history" %}aria-current="page"{% endif %}>History</a>
      <a href="/sources" {% if request.url.path.startswith("/sources") %}aria-current="page"{% endif %}>Sources</a>
      <a href="/settings" {% if request.url.path.startswith("/settings") %}aria-current="page"{% endif %}>Settings</a>
      <a href="/guide" {% if request.url.path == "/guide" %}aria-current="page"{% endif %}>Guide</a>
    </nav>
```

with:

```html
    <button type="button" id="nav-toggle" class="nav-toggle" aria-expanded="false" aria-controls="main-nav">
      <span class="sr-only">Menu</span>
      <span aria-hidden="true">&#9776;</span>
    </button>
    <nav aria-label="Main" id="main-nav">
      <a href="/" {% if request.url.path == "/" %}aria-current="page"{% endif %}>Dashboard</a>
      <a href="/jobs" {% if request.url.path == "/jobs" %}aria-current="page"{% endif %}>Jobs</a>
      <a href="/history" {% if request.url.path == "/history" %}aria-current="page"{% endif %}>History</a>
      <a href="/sources" {% if request.url.path.startswith("/sources") %}aria-current="page"{% endif %}>Sources</a>
      <a href="/settings" {% if request.url.path.startswith("/settings") %}aria-current="page"{% endif %}>Settings</a>
      <a href="/guide" {% if request.url.path == "/guide" %}aria-current="page"{% endif %}>Guide</a>
    </nav>
```

The button is placed *before* the nav in DOM order, but is `display: none` above `40rem` (added in Step 5), so it's not focusable at desktop width — the existing `tests/web/e2e/test_keyboard_navigation.py::test_tab_order_reaches_run_now_button_after_skip_link_and_nav` (which runs at the default/desktop Playwright viewport and expects exactly 8 tabs — skip-link, 6 nav links, "Run now") is unaffected.

Also add the script tag next to the other two, in `<head>`:

```html
  <script src="/static/theme.js" defer></script>
  <script src="/static/preferences.js" defer></script>
  <script src="/static/nav.js" defer></script>
```

- [ ] **Step 4: Create `app/web/static/nav.js`**

```javascript
(function () {
  var toggle = document.getElementById("nav-toggle");
  var nav = document.getElementById("main-nav");
  if (!toggle || !nav) return;

  function close() {
    nav.classList.remove("open");
    toggle.setAttribute("aria-expanded", "false");
  }

  function open() {
    nav.classList.add("open");
    toggle.setAttribute("aria-expanded", "true");
  }

  toggle.addEventListener("click", function () {
    if (nav.classList.contains("open")) {
      close();
    } else {
      open();
    }
  });

  document.addEventListener("click", function (event) {
    if (!nav.classList.contains("open")) return;
    if (nav.contains(event.target) || toggle.contains(event.target)) return;
    close();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && nav.classList.contains("open")) {
      close();
      toggle.focus();
    }
  });

  window.addEventListener("resize", function () {
    if (window.innerWidth > 640) close();
  });
})();
```

- [ ] **Step 5: Add CSS for the toggle button, the `.sr-only` utility, and the breakpoint**

In `app/web/static/style.css`, after the `nav[aria-label="Main"] a[aria-current="page"], ...` rule block (around line 164, right before `nav[aria-label="Settings tabs"] {`), add:

```css
.nav-toggle {
  display: none;
  background: var(--bg-elevated);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.5rem 0.75rem;
  font-size: 1.25rem;
  line-height: 1;
  cursor: pointer;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 40rem) {
  .nav-toggle {
    display: inline-block;
  }

  nav[aria-label="Main"] {
    display: none;
    flex-direction: column;
    width: 100%;
  }

  nav[aria-label="Main"].open {
    display: flex;
  }
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/web/test_base.py -k nav_toggle -v`
Expected: PASS

- [ ] **Step 7: Write e2e tests**

Create `tests/web/e2e/test_nav_menu.py`:

```python
def test_nav_toggle_hidden_at_desktop_width(live_server, page):
    page.goto(live_server + "/")

    assert page.is_hidden("#nav-toggle")


def test_nav_toggle_opens_and_closes_menu_at_narrow_width(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/")

    assert page.is_visible("#nav-toggle")
    assert page.get_attribute("#nav-toggle", "aria-expanded") == "false"

    page.click("#nav-toggle")
    assert page.get_attribute("#nav-toggle", "aria-expanded") == "true"
    assert page.is_visible('nav[aria-label="Main"] a[href="/jobs"]')

    page.click("#nav-toggle")
    assert page.get_attribute("#nav-toggle", "aria-expanded") == "false"


def test_escape_key_closes_open_menu(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/")

    page.click("#nav-toggle")
    assert page.get_attribute("#nav-toggle", "aria-expanded") == "true"

    page.keyboard.press("Escape")
    assert page.get_attribute("#nav-toggle", "aria-expanded") == "false"


def test_clicking_outside_closes_open_menu(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/")

    page.click("#nav-toggle")
    assert page.get_attribute("#nav-toggle", "aria-expanded") == "true"

    page.mouse.click(10, 10)
    assert page.get_attribute("#nav-toggle", "aria-expanded") == "false"


def test_nav_links_reachable_by_keyboard_when_open(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/")

    page.click("#nav-toggle")
    page.click('nav[aria-label="Main"] a[href="/jobs"]')
    page.wait_for_url("**/jobs")
```

- [ ] **Step 8: Run the full e2e file and the desktop keyboard-nav regression test**

Run: `pytest tests/web/e2e/test_nav_menu.py tests/web/e2e/test_keyboard_navigation.py -v`
Expected: all PASS, including the pre-existing `test_tab_order_reaches_run_now_button_after_skip_link_and_nav`.

- [ ] **Step 9: Commit**

```bash
git add app/web/templates/base.html app/web/static/nav.js app/web/static/style.css tests/web/test_base.py tests/web/e2e/test_nav_menu.py
git commit -m "feat: collapse main nav into a hamburger menu on narrow screens (#34)"
```

---

### Task 3: Responsive card tables

**Files:**
- Modify: `app/web/templates/history.html`
- Modify: `app/web/templates/jobs.html`
- Modify: `app/web/templates/sources_list.html`
- Modify: `app/web/static/style.css` (new rules near `.table-scroll`/`table`, ~line 306-334)
- Test: `tests/web/test_history.py`, `tests/web/test_jobs.py`, `tests/web/test_sources_list.py`, `tests/web/test_base.py`
- Test (e2e): Create `tests/web/e2e/test_card_tables.py`

**Interfaces:**
- Produces: `data-label="..."` attribute on every `<td>` in the three tables, matching each column's header text exactly (used by the CSS `::before` rule and by tests/JS in later tasks — Task 6/7's history fragment reuses these same `data-label` values, in particular `data-label="Finished"`).

- [ ] **Step 1: Write the failing unit tests**

Add to `tests/web/test_history.py`:

```python
def test_history_table_cells_have_data_labels(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_job_count=3, failed_sources=["Bad Co"])

    resp = client.get("/history")

    assert 'data-label="Started"' in resp.text
    assert 'data-label="Finished"' in resp.text
    assert 'data-label="New jobs"' in resp.text
    assert 'data-label="Failed sources"' in resp.text
```

Add to `tests/web/test_jobs.py`:

```python
def test_jobs_table_cells_have_data_labels(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job()], db.start_run(conn))

    resp = client.get("/jobs")

    for label in ("Company", "Search name", "Title", "Location", "Date found",
                  "Removed", "Age (days)", "Emailed", "Summary"):
        assert f'data-label="{label}"' in resp.text
```

Add to `tests/web/test_sources_list.py`:

```python
def test_sources_table_cells_have_data_labels(client):
    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme (Greenhouse)", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.get("/sources")

    for label in ("Name", "Type", "Company", "Edit", "Delete"):
        assert f'data-label="{label}"' in resp.text
```

Add to `tests/web/test_base.py`:

```python
def test_style_css_defines_card_table_breakpoint(client):
    resp = client.get("/static/style.css")

    assert resp.status_code == 200
    assert "@media (max-width: 40rem)" in resp.text
    assert "attr(data-label)" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_history.py tests/web/test_jobs.py tests/web/test_sources_list.py tests/web/test_base.py -k data_label -v`
Expected: FAIL — no `data-label` attributes exist yet.

- [ ] **Step 3: Add `data-label` to `history.html`**

In `app/web/templates/history.html`, replace the row body:

```html
  {% for run in runs %}
  <tr>
    <td>{{ run.started_at }}</td>
    <td>{{ run.finished_at or "in progress" }}</td>
    <td>{{ run.new_job_count }}</td>
    <td>{{ run.failed_sources | join(", ") }}</td>
  </tr>
  {% endfor %}
```

with:

```html
  {% for run in runs %}
  <tr>
    <td data-label="Started">{{ run.started_at }}</td>
    <td data-label="Finished">{{ run.finished_at or "in progress" }}</td>
    <td data-label="New jobs">{{ run.new_job_count }}</td>
    <td data-label="Failed sources">{{ run.failed_sources | join(", ") }}</td>
  </tr>
  {% endfor %}
```

- [ ] **Step 4: Add `data-label` to `jobs.html`**

In `app/web/templates/jobs.html`, replace the row body:

```html
  {% for job in jobs %}
  <tr class="{{ "removed" if job.removed_at else "" }}">
    <td>{{ job.company or "—" }}</td>
    <td>{{ job.source_name }}</td>
    <td><a href="{{ job.safe_url }}">{{ job.title }}</a></td>
    <td>{{ job.location or "—" }}</td>
    <td>{{ job.first_seen_at }}</td>
    <td>{{ job.removed_at or "—" }}</td>
    <td>{{ job.age_days }}</td>
    <td>{{ job.emailed_at or "Not sent" }}</td>
    <td>{{ job.summary or "—" }}</td>
  </tr>
  {% endfor %}
```

with:

```html
  {% for job in jobs %}
  <tr class="{{ "removed" if job.removed_at else "" }}">
    <td data-label="Company">{{ job.company or "—" }}</td>
    <td data-label="Search name">{{ job.source_name }}</td>
    <td data-label="Title"><a href="{{ job.safe_url }}">{{ job.title }}</a></td>
    <td data-label="Location">{{ job.location or "—" }}</td>
    <td data-label="Date found">{{ job.first_seen_at }}</td>
    <td data-label="Removed">{{ job.removed_at or "—" }}</td>
    <td data-label="Age (days)">{{ job.age_days }}</td>
    <td data-label="Emailed">{{ job.emailed_at or "Not sent" }}</td>
    <td data-label="Summary">{{ job.summary or "—" }}</td>
  </tr>
  {% endfor %}
```

- [ ] **Step 5: Add `data-label` to `sources_list.html`**

In `app/web/templates/sources_list.html`, replace the header and row body:

```html
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
```

with:

```html
  <tr><th scope="col">Name</th><th scope="col">Type</th><th scope="col">Company</th><th scope="col">Edit</th><th scope="col">Delete</th></tr>
  {% for s in sources %}
  <tr>
    <td data-label="Name">{{ s.name }}</td>
    <td data-label="Type">{{ s.type }}</td>
    <td data-label="Company">{{ s.company or "" }}</td>
    <td data-label="Edit"><a href="/sources/{{ s.id }}/edit">Edit</a></td>
    <td data-label="Delete">
      <form method="post" action="/sources/{{ s.id }}/delete" style="display:inline">
        <button type="submit">Delete</button>
      </form>
    </td>
  </tr>
  {% endfor %}
```

(This also gives the two previously-empty action `<th>`s real text, which is a minor desktop-visible improvement — no existing test asserts those headers are empty.)

- [ ] **Step 6: Add card-layout CSS**

In `app/web/static/style.css`, after the existing `.table-scroll { ... }` / `table { ... }` / `th, td { ... }` / `tr:last-child td { ... }` / `th { ... }` / `tbody tr:hover { ... }` / `tr.removed td { ... }` rules (ending around line 338), add:

```css
@media (max-width: 40rem) {
  .table-scroll {
    border: none;
    overflow-x: visible;
  }

  .table-scroll table,
  .table-scroll thead,
  .table-scroll tbody,
  .table-scroll th,
  .table-scroll td,
  .table-scroll tr {
    display: block;
    width: 100%;
  }

  .table-scroll thead {
    position: absolute;
    left: -9999px;
  }

  .table-scroll tr {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: var(--space-3);
  }

  .table-scroll td {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-3);
    text-align: right;
    border-bottom: 1px solid var(--border);
  }

  .table-scroll tr td:last-child {
    border-bottom: none;
  }

  .table-scroll td::before {
    content: attr(data-label);
    font-weight: 600;
    text-align: left;
    color: var(--fg-muted);
  }
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/web/test_history.py tests/web/test_jobs.py tests/web/test_sources_list.py tests/web/test_base.py -v`
Expected: all PASS, including pre-existing tests in these files (e.g. `test_sources_table_has_scoped_headers_and_scroll_wrapper`, `test_jobs_table_has_scoped_headers_and_scroll_wrapper`).

- [ ] **Step 8: Write e2e tests**

Create `tests/web/e2e/test_card_tables.py`:

```python
def test_history_table_is_grid_at_desktop_width(live_server, page):
    page.goto(live_server + "/history")

    thead_display = page.eval_on_selector(
        '.table-scroll thead, .table-scroll tr:first-child',
        "el => getComputedStyle(el).display",
    )
    assert thead_display != "none"


def test_history_table_becomes_cards_at_narrow_width(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/history")

    label_content = page.eval_on_selector(
        '.table-scroll td',
        "el => getComputedStyle(el, '::before').content",
    )
    assert label_content not in (None, "none", '""')


def test_no_horizontal_overflow_on_history_at_narrow_viewport(live_server, page):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(live_server + "/history")

    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    inner_width = page.evaluate("window.innerWidth")
    assert scroll_width <= inner_width
```

- [ ] **Step 9: Run e2e tests**

Run: `pytest tests/web/e2e/test_card_tables.py -v`
Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add app/web/templates/history.html app/web/templates/jobs.html app/web/templates/sources_list.html app/web/static/style.css tests/web/test_history.py tests/web/test_jobs.py tests/web/test_sources_list.py tests/web/test_base.py tests/web/e2e/test_card_tables.py
git commit -m "feat: switch tables to a stacked card layout on narrow screens (#34)"
```

---

### Task 4: Email validation (client + server)

**Files:**
- Modify: `app/web/templates/settings_preferences.html`
- Modify: `app/web/routes_settings.py`
- Test: `tests/web/test_settings.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `app.web.routes_settings._is_valid_email(addr: str) -> bool`, used by both `save_preferences` and `_parse_preferences_import` in this same task (no cross-task dependency).

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_settings.py`:

```python
def test_post_preferences_rejects_malformed_email_and_does_not_save(client):
    resp = client.post("/settings/preferences", data={
        "email_days": ["mon"], "email_to": ["not-an-email"],
    })

    assert resp.status_code == 400
    assert "Invalid email address" in resp.text

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings is None or settings["email_to"] != "not-an-email"


def test_post_preferences_accepts_well_formed_emails(client):
    resp = client.post("/settings/preferences", data={
        "email_days": ["mon"], "email_to": ["good@x.test"],
    }, follow_redirects=False)

    assert resp.status_code == 303

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_to"] == "good@x.test"


def test_post_preferences_invalid_email_preserves_submitted_days_and_addresses(client):
    resp = client.post("/settings/preferences", data={
        "email_days": ["mon", "wed"], "email_to": ["good@x.test", "not-an-email"],
    })

    assert resp.status_code == 400
    assert 'value="good@x.test"' in resp.text
    assert 'value="mon" checked' in resp.text
    assert 'value="wed" checked' in resp.text


def test_settings_preferences_recipient_inputs_are_required(client):
    resp = client.get("/settings/preferences")

    assert resp.text.count(' required') >= 2


def test_post_import_settings_with_malformed_email_drops_it_but_keeps_others(client):
    import json

    payload = json.dumps({
        "sources": [],
        "preferences": {
            "email_days": ["mon"],
            "resend_jobs": False,
            "email_to": ["good@x.test", "not-an-email"],
        },
    }).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
        follow_redirects=False,
    )

    assert resp.status_code == 303

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_to"] == "good@x.test"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_settings.py -k "email or required" -v`
Expected: FAIL — no validation exists yet, no `required` attribute yet.

- [ ] **Step 3: Add `_is_valid_email` and wire it into `save_preferences`**

In `app/web/routes_settings.py`, add near the top (after the `import` block, before `_str_field`):

```python
import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _is_valid_email(addr: str) -> bool:
    return bool(EMAIL_RE.match(addr))
```

Replace the existing `save_preferences`:

```python
@router.post("/settings/preferences")
async def save_preferences(request: Request):
    form = await request.form()
    selected_days = set(_str_list_field(form, "email_days")) & set(DAY_CODES)
    email_days = ",".join(day for day in DAY_CODES if day in selected_days)
    resend_jobs = "resend_jobs" in form
    email_to = ",".join(addr.strip() for addr in _str_list_field(form, "email_to") if addr.strip())
    db.save_preferences(request.app.state.conn, email_days, resend_jobs, email_to)
    return RedirectResponse(url="/settings/preferences", status_code=303)
```

with:

```python
@router.post("/settings/preferences")
async def save_preferences(request: Request):
    form = await request.form()
    selected_days = set(_str_list_field(form, "email_days")) & set(DAY_CODES)
    email_days = ",".join(day for day in DAY_CODES if day in selected_days)
    resend_jobs = "resend_jobs" in form
    submitted_emails = [addr.strip() for addr in _str_list_field(form, "email_to") if addr.strip()]

    invalid = [addr for addr in submitted_emails if not _is_valid_email(addr)]
    if invalid:
        settings = db.get_settings(request.app.state.conn)
        return templates.TemplateResponse(
            request, "settings_preferences.html",
            {
                "settings": settings,
                "email_days_selected": selected_days,
                "email_to_list": submitted_emails or [""],
                "error": f"Invalid email address: {invalid[0]}",
            },
            status_code=400,
        )

    email_to = ",".join(submitted_emails)
    db.save_preferences(request.app.state.conn, email_days, resend_jobs, email_to)
    return RedirectResponse(url="/settings/preferences", status_code=303)
```

- [ ] **Step 4: Make `_parse_preferences_import` drop malformed addresses**

In `app/web/routes_settings.py`, in `_parse_preferences_import`, replace:

```python
    raw_emails = preferences.get("email_to")
    emails = raw_emails if isinstance(raw_emails, list) else []
    email_to = ",".join(addr.strip() for addr in emails if isinstance(addr, str) and addr.strip())
```

with:

```python
    raw_emails = preferences.get("email_to")
    emails = raw_emails if isinstance(raw_emails, list) else []
    email_to = ",".join(
        addr.strip() for addr in emails
        if isinstance(addr, str) and addr.strip() and _is_valid_email(addr.strip())
    )
```

- [ ] **Step 5: Add the error banner and `required` attribute to `settings_preferences.html`**

In `app/web/templates/settings_preferences.html`, after `<h1>Preferences</h1>`, add:

```html
{% if error %}
<div class="error">{{ error }}</div>
{% endif %}
```

And add `required` to both recipient `<input type="email">` elements:

```html
        <input type="email" name="email_to" value="{{ email }}" placeholder="name@example.com" required>
```

```html
        <input type="email" name="email_to" placeholder="name@example.com" required>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/web/test_settings.py -v`
Expected: all PASS, including every pre-existing test in this file (validate no regressions from the `save_preferences` rewrite, e.g. `test_post_preferences_saves_days_resend_and_recipients`, `test_post_preferences_drops_blank_recipient_rows`, `test_post_import_settings_with_malformed_preferences_falls_back_to_defaults`).

- [ ] **Step 7: Commit**

```bash
git add app/web/routes_settings.py app/web/templates/settings_preferences.html tests/web/test_settings.py
git commit -m "feat: validate recipient email addresses client- and server-side (#34)"
```

---

### Task 5: Import confirmation

**Files:**
- Modify: `app/web/templates/settings_data.html`
- Test: `tests/web/test_settings.py`
- Test (e2e): Create `tests/web/e2e/test_import_confirmation.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing unit test**

Add to `tests/web/test_settings.py`:

```python
def test_settings_data_import_form_has_confirm_guard(client):
    resp = client.get("/settings/data")

    assert 'id="import-form"' in resp.text
    assert "confirm(" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_settings.py::test_settings_data_import_form_has_confirm_guard -v`
Expected: FAIL.

- [ ] **Step 3: Add the id and inline confirm-guard script**

In `app/web/templates/settings_data.html`, change:

```html
<form method="post" action="/settings/data/import" enctype="multipart/form-data">
```

to:

```html
<form method="post" action="/settings/data/import" enctype="multipart/form-data" id="import-form">
```

Then, right before `{% endblock %}`, add:

```html
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/web/test_settings.py::test_settings_data_import_form_has_confirm_guard -v`
Expected: PASS

- [ ] **Step 5: Write e2e tests**

Create `tests/web/e2e/test_import_confirmation.py`:

```python
import json


def test_confirming_dialog_allows_import_to_proceed(live_server, page):
    page.goto(live_server + "/settings/data")
    page.on("dialog", lambda dialog: dialog.accept())

    payload = json.dumps({"sources": []}).encode()
    page.set_input_files('input[name="file"]', {
        "name": "settings.json", "mimeType": "application/json", "buffer": payload,
    })
    page.click('#import-form button[type="submit"]')
    page.wait_for_url("**/settings/data?imported=0")


def test_dismissing_dialog_cancels_import(live_server, page):
    page.goto(live_server + "/settings/data")
    page.on("dialog", lambda dialog: dialog.dismiss())

    payload = json.dumps({"sources": []}).encode()
    page.set_input_files('input[name="file"]', {
        "name": "settings.json", "mimeType": "application/json", "buffer": payload,
    })
    page.click('#import-form button[type="submit"]')

    page.wait_for_timeout(300)
    assert page.url.endswith("/settings/data")
    assert "imported" not in page.url
```

- [ ] **Step 6: Run e2e tests**

Run: `pytest tests/web/e2e/test_import_confirmation.py -v`
Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add app/web/templates/settings_data.html tests/web/test_settings.py tests/web/e2e/test_import_confirmation.py
git commit -m "feat: confirm before importing settings replaces the source list (#34)"
```

---

### Task 6: History fragment endpoint (`GET /history/rows`)

**Files:**
- Create: `app/web/templates/_history_rows.html`
- Modify: `app/web/templates/history.html`
- Modify: `app/web/routes_history.py`
- Test: `tests/web/test_history.py`

**Interfaces:**
- Consumes: `data-label="Started"/"Finished"/"New jobs"/"Failed sources"` from Task 3.
- Produces: `GET /history/rows?page=` (HTML fragment, same shape as `_history_rows.html`); `#history-rows` container with `data-page="{{ pagination.page }}"`. Task 7's `history.js` depends on both.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_history.py`:

```python
def test_history_rows_endpoint_returns_fragment_without_page_chrome(client):
    resp = client.get("/history/rows")

    assert resp.status_code == 200
    assert 'id="history-rows"' in resp.text
    assert 'aria-label="Main"' not in resp.text
    assert "<html" not in resp.text


def test_history_rows_endpoint_paginates_like_history_page(client):
    conn = client.app.state.conn
    for i in range(30):
        run_id = db.start_run(conn)
        db.finish_run(conn, run_id, new_job_count=i, failed_sources=[])

    page1 = client.get("/history/rows?page=1")
    page2 = client.get("/history/rows?page=2")

    assert "Page 1 of 2" in page1.text
    assert "Page 2 of 2" in page2.text


def test_history_rows_endpoint_invalid_page_param_clamps(client):
    resp = client.get("/history/rows?page=not-a-number")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_history_rows_reflects_run_status_change(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)

    in_progress = client.get("/history/rows")
    assert 'data-label="Finished">in progress' in in_progress.text

    db.finish_run(conn, run_id, new_job_count=2, failed_sources=[])
    finished = client.get("/history/rows")
    assert 'data-label="Finished">in progress' not in finished.text


def test_history_page_includes_refresh_button_and_status_region(client):
    resp = client.get("/history")

    assert 'id="refresh-history"' in resp.text
    assert 'id="history-status"' in resp.text
    assert 'aria-live="polite"' in resp.text
    assert 'id="history-rows"' in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_history.py -k "rows or refresh_button" -v`
Expected: FAIL — `/history/rows` 404s, `history.html` has no refresh button.

- [ ] **Step 3: Create the fragment template**

Create `app/web/templates/_history_rows.html` (no `{% extends %}` — this is included, not rendered top-level):

```html
<div id="history-rows" data-page="{{ pagination.page }}">
<div class="table-scroll">
<table>
  <tr><th scope="col">Started</th><th scope="col">Finished</th><th scope="col">New jobs</th><th scope="col">Failed sources</th></tr>
  {% for run in runs %}
  <tr>
    <td data-label="Started">{{ run.started_at }}</td>
    <td data-label="Finished">{{ run.finished_at or "in progress" }}</td>
    <td data-label="New jobs">{{ run.new_job_count }}</td>
    <td data-label="Failed sources">{{ run.failed_sources | join(", ") }}</td>
  </tr>
  {% endfor %}
</table>
</div>
<nav aria-label="Pagination">
  {% if pagination.has_prev %}<a href="/history?page={{ pagination.page - 1 }}">Previous</a>{% endif %}
  <span>Page {{ pagination.page }} of {{ pagination.total_pages }}</span>
  {% if pagination.has_next %}<a href="/history?page={{ pagination.page + 1 }}">Next</a>{% endif %}
</nav>
</div>
```

- [ ] **Step 4: Rewrite `history.html` to include the fragment**

Replace the entire contents of `app/web/templates/history.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1>Run history</h1>
<div class="history-toolbar">
  <button type="button" id="refresh-history">Refresh</button>
  <span id="history-status" class="sr-only" aria-live="polite"></span>
</div>
{% include "_history_rows.html" %}
{% endblock %}
```

- [ ] **Step 5: Refactor `routes_history.py` and add the fragment route**

Replace the contents of `app/web/routes_history.py`:

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app import db
from app.web.pagination import paginate
from app.web.templating import templates

router = APIRouter()

PAGE_SIZE = 25


def _history_context(request: Request, page: str) -> dict:
    total = db.count_runs(request.app.state.conn)
    pagination = paginate(total, page, PAGE_SIZE)
    runs = db.list_runs(request.app.state.conn, limit=PAGE_SIZE, offset=pagination.offset)
    return {"runs": runs, "pagination": pagination}


@router.get("/history", response_class=HTMLResponse)
def history(request: Request, page: str = "1"):
    return templates.TemplateResponse(request, "history.html", _history_context(request, page))


@router.get("/history/rows", response_class=HTMLResponse)
def history_rows(request: Request, page: str = "1"):
    return templates.TemplateResponse(request, "_history_rows.html", _history_context(request, page))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/web/test_history.py -v`
Expected: all PASS, including every pre-existing test (`test_history_lists_past_runs`, `test_history_second_page_shows_older_runs`, `test_history_invalid_page_param_clamps_instead_of_erroring`, etc.) — `history.html`'s rendered output for `runs`/`pagination` is unchanged, just now assembled via `{% include %}`.

- [ ] **Step 7: Commit**

```bash
git add app/web/templates/_history_rows.html app/web/templates/history.html app/web/routes_history.py tests/web/test_history.py
git commit -m "feat: add GET /history/rows fragment endpoint for client-side refresh (#34)"
```

---

### Task 7: History auto-refresh JS + Refresh button styling

**Files:**
- Create: `app/web/static/history.js`
- Modify: `app/web/templates/base.html` (script tag)
- Modify: `app/web/static/style.css` (`.history-toolbar` layout rule)
- Test: `tests/web/test_history.py`
- Test (e2e): Create `tests/web/e2e/test_history_refresh.py`

**Interfaces:**
- Consumes: `#history-rows[data-page]`, `#refresh-history`, `#history-status`, `GET /history/rows?page=` (all from Task 6); `td[data-label="Finished"]` values `"in progress"` vs. a timestamp (from Task 3/6).

- [ ] **Step 1: Write the failing unit test**

Add to `tests/web/test_history.py`:

```python
def test_history_js_is_served(client):
    resp = client.get("/static/history.js")

    assert resp.status_code == 200
    assert "history-rows" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_history.py::test_history_js_is_served -v`
Expected: FAIL — `/static/history.js` 404s.

- [ ] **Step 3: Create `app/web/static/history.js`**

```javascript
(function () {
  var container = document.getElementById("history-rows");
  var refreshButton = document.getElementById("refresh-history");
  var status = document.getElementById("history-status");
  if (!container || !refreshButton) return;

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
    return fetch("/history/rows?page=" + encodeURIComponent(page))
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

  refreshButton.addEventListener("click", refresh);
  managePolling();
})();
```

- [ ] **Step 4: Wire the script tag and toolbar CSS**

In `app/web/templates/base.html`, add after `<script src="/static/nav.js" defer></script>`:

```html
  <script src="/static/history.js" defer></script>
```

In `app/web/static/style.css`, add (near `.hint`/`.card` utility rules):

```css
.history-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/web/test_history.py::test_history_js_is_served -v`
Expected: PASS

- [ ] **Step 6: Write e2e tests using network mocking (deterministic, no DB seeding needed)**

Create `tests/web/e2e/test_history_refresh.py`:

```python
def test_refresh_button_swaps_table_content(live_server, page):
    page.goto(live_server + "/history")

    page.route("**/history/rows*", lambda route: route.fulfill(
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
    page.goto(live_server + "/history")

    page.route("**/history/rows*", lambda route: route.fulfill(
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

    page.route("**/history/rows*", handler)
    page.goto(live_server + "/history")

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
    page.goto(live_server + "/history")

    page.route("**/history/rows*", lambda route: route.fulfill(
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

- [ ] **Step 7: Run e2e tests**

Run: `pytest tests/web/e2e/test_history_refresh.py -v`
Expected: all PASS (the auto-poll test takes up to ~15s due to the real 10s `POLL_MS` timer — this is expected, not flaky, given the fixed interval; no `pytest-timeout` plugin is installed, so no `--timeout` flag is needed or available).

- [ ] **Step 8: Commit**

```bash
git add app/web/static/history.js app/web/templates/base.html app/web/static/style.css tests/web/test_history.py tests/web/e2e/test_history_refresh.py
git commit -m "feat: auto-refresh history page while a run is in progress (#34)"
```

---

### Task 8: Version bump and documentation

**Files:**
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`
- Modify: `docs/USAGE.md`
- Modify: `README.md`
- Modify: `ROADMAP.md`
- Test: `tests/web/test_base.py` (existing `test_footer_shows_app_name_and_version` already asserts against `importlib.metadata.version`, no test change needed — verifies automatically)

**Interfaces:**
- Consumes: nothing (pure doc/version task, run last so it can describe everything above accurately).

- [ ] **Step 1: Bump the version**

In `pyproject.toml`, change:

```toml
version = "0.9.0"
```

to:

```toml
version = "0.10.0"
```

- [ ] **Step 2: Verify the footer picks it up**

Run: `pip install -e . --no-deps --quiet && pytest tests/web/test_base.py::test_footer_shows_app_name_and_version -v`
Expected: PASS (this test derives its expectation from `importlib.metadata.version("careerspyder")`, so it passes against whatever version is installed — reinstalling the package after the `pyproject.toml` edit is what makes the running code's metadata match).

- [ ] **Step 3: Add a CHANGELOG entry**

In `CHANGELOG.md`, insert a new section between `## [Unreleased]` and `## [0.9.0] — 2026-08-16`:

```markdown
## [0.10.0] — 2026-08-16

### Added

- Main navigation collapses into a hamburger menu below a `40rem`
  viewport width; History, Jobs, and Sources tables switch to a
  stacked card layout at the same breakpoint (issue #34).
- Recipient email addresses (Preferences tab) are now validated both
  in the browser (`required` + native `type="email"` checking) and on
  the server — a malformed address is rejected with an inline error on
  save, and silently dropped (rather than failing the whole import) if
  present in an imported `preferences.email_to` list (issue #34).
- Importing settings now asks for confirmation before replacing the
  entire source list (issue #34).
- The History page has a **Refresh** button and auto-polls every 10
  seconds while any listed run is still in progress, stopping once it
  finishes (issue #34).

### Fixed

- Recipient email inputs now pick up the app's dark-mode styling —
  previously `input[type="email"]` was missing from the shared input
  CSS rule and fell back to browser-default (light) styling (issue
  #34).
```

- [ ] **Step 4: Update `docs/USAGE.md`**

In the "Web UI tour" table, update the History, Preferences, and Data rows. Replace:

```markdown
| History (`/history`) | Table of past runs — start/finish time, new job count, failed source names. |
```

with:

```markdown
| History (`/history`) | Table of past runs — start/finish time, new job count, failed source names. A **Refresh** button re-fetches the latest rows, and the page auto-refreshes itself every 10 seconds while a run is still in progress. |
```

Replace:

```markdown
| Settings → Data (`/settings/data`) | Clear the job dedup cache, and export/import `sources.json`. |
```

with:

```markdown
| Settings → Data (`/settings/data`) | Clear the job dedup cache, and export/import `sources.json`. Importing asks for confirmation before replacing the source list. |
```

Replace:

```markdown
| Settings → Preferences (`/settings/preferences`) | Theme, which days to check for jobs, resend behavior, and digest recipients. |
```

with:

```markdown
| Settings → Preferences (`/settings/preferences`) | Theme, which days to check for jobs, resend behavior, and digest recipients (validated email addresses). |
```

Then, right after the "Web UI tour" table (before "## Source types & examples"), add:

```markdown
On narrow screens (phones, small tablets) the main menu collapses
behind a menu button in the header, and tables switch from a
horizontally-scrolling grid to a stacked card layout — tap the button
to open the menu, and scroll normally to read table rows.
```

- [ ] **Step 5: Update `README.md`**

In the web UI routes table, replace:

```markdown
| `/settings/data` | Clear the job dedup cache (the next run will re-report every currently known job as new and may send a large digest email), and export/import `sources.json` (import replaces the entire source list). |
```

with:

```markdown
| `/settings/data` | Clear the job dedup cache (the next run will re-report every currently known job as new and may send a large digest email), and export/import `sources.json` (import replaces the entire source list, and asks for confirmation before doing so). |
```

Replace:

```markdown
| `/settings/preferences` | Light/Dark/System theme choice (client-side, `localStorage` only). Also: which days of the week to check for jobs and send a digest, whether a still-listed job is resent every digest or emailed once ever, and one or more recipient addresses (server-stored). |
```

with:

```markdown
| `/settings/preferences` | Light/Dark/System theme choice (client-side, `localStorage` only). Also: which days of the week to check for jobs and send a digest, whether a still-listed job is resent every digest or emailed once ever, and one or more recipient addresses (server-stored, validated client- and server-side). |
```

- [ ] **Step 6: Update `ROADMAP.md`**

In the "Features" section, replace:

```markdown
- **Richer frontend (from design spec).** v1 is deliberately
  server-rendered, full-page-reload HTML with no SPA and no JS build step.
  A live-updating dashboard (e.g. via polling or SSE for in-progress "Run
  now" status) is a reasonable next step if the current UX feels too
  static, but isn't needed for the core job-digest use case.
```

with:

```markdown
- **Richer frontend (from design spec).** v1 is deliberately
  server-rendered, full-page-reload HTML with no SPA and no JS build step.
  The History page now polls for in-progress-run updates (issue #34); a
  similar live-updating indicator on the Dashboard's "Run now" button is
  a reasonable next step if the current UX feels too static there too,
  but isn't needed for the core job-digest use case.
```

- [ ] **Step 7: Verify the full test suite still passes**

Run: `pytest -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml CHANGELOG.md docs/USAGE.md README.md ROADMAP.md
git commit -m "chore: bump version to 0.10.0 and document FED responsiveness changes (#34)"
```

---

### Task 9: Final verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full unit/integration suite**

Run: `pytest tests/ -v --ignore=tests/web/e2e`
Expected: all PASS.

- [ ] **Step 2: Run the full e2e suite**

Run: `pytest tests/web/e2e -v`
Expected: all PASS (this includes the pre-existing theme-toggle, keyboard-navigation, and responsive-layout specs, confirming no regressions).

- [ ] **Step 3: Manually smoke-test in a browser**

Start the app locally (check `README.md`'s "Local development" section for the exact command, typically `uvicorn app.web.main:app --reload`), then in a browser:
- Resize below `640px` width: confirm the hamburger button appears, opens/closes the menu, and History/Jobs/Sources tables become stacked cards.
- Toggle dark mode (`/settings/preferences`) and confirm the recipient email field now matches the dark theme.
- On `/settings/preferences`, submit a malformed email and confirm the inline error appears without saving.
- On `/settings/data`, click Import and confirm the browser's confirmation dialog appears; cancel it and confirm nothing happens; accept it and confirm the import proceeds.
- On `/history`, click **Refresh** and confirm the table updates; trigger a run from the Dashboard and confirm the History page's status auto-updates without a manual reload.

- [ ] **Step 4: Report results to the user**

Summarize: full test counts (unit/integration + e2e), any manual smoke-test findings, and confirm the branch (`34`) is ready for review/PR.
