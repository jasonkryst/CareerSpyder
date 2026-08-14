# Modernized Theme + Preferences Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give CareerSpyder's web UI a distinctive red/white/black visual identity and move theme control out of the header into a new Preferences tab under Settings, with an explicit Light/Dark/System choice.

**Architecture:** Pure CSS-custom-property + vanilla-JS changes inside the existing server-rendered Jinja2/FastAPI app — no build step, no new dependencies, no new server-side storage. Theme choice stays client-side (localStorage), same mechanism as today, just relocated and expanded from a two-state button to a three-state radio group.

**Tech Stack:** FastAPI, Jinja2, vanilla CSS/JS, pytest + `TestClient` (backend), pytest-playwright (e2e, Chromium).

## Global Constraints

- No new runtime dependencies, no CDN/network fonts or icon sets, no JS build step — CSS/JS stays hand-written and served as-is from `app/web/static/`.
- No new server-side storage for preferences — theme selection remains `localStorage`-only.
- Color palette confined to red/white/black across both light and dark mode, AA-contrast checked (spec: `docs/superpowers/specs/2026-08-14-modernized-theme-preferences-design.md`).
- `.success` must never reuse `--accent` (which is now red) — it gets its own neutral gray tokens so it can't be mistaken for an error state.
- No "danger" red styling on Delete buttons — avoids overloading red, which already carries accent + error meaning.
- Email/Data tab request/response behavior (routes, form fields, validation) must not change — only markup/classes change on those templates.
- Run `pytest -q` (covers both `tests/web/*.py` TestClient tests and `tests/web/e2e/*.py` Playwright tests — `pyproject.toml`'s `testpaths = ["tests"]` includes both, no separate marker) after every task.

---

### Task 1: CSS foundation — palette, spacing, typography, components

**Files:**
- Modify: `app/web/static/style.css` (full rewrite)
- Test: `tests/web/test_base.py`

**Interfaces:**
- Produces (relied on by every later task): CSS custom properties `--bg`, `--bg-elevated`, `--fg`, `--fg-muted`, `--border`, `--accent`, `--accent-fg`, `--error-bg`, `--error-fg`, `--success-bg`, `--success-fg`, `--focus-ring`, `--radius`, `--shadow`, `--space-1`..`--space-6`; classes `.card`, `.btn-primary`, `.brand`.

- [ ] **Step 1: Write the failing test**

Add to `tests/web/test_base.py`:

```python
def test_style_css_defines_modernized_tokens(client):
    resp = client.get("/static/style.css")

    assert resp.status_code == 200
    assert "--accent: #b3101f" in resp.text
    assert "--radius" in resp.text
    assert "--space-4" in resp.text
    assert ".card {" in resp.text
    assert ".btn-primary {" in resp.text
    assert ".brand" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_base.py::test_style_css_defines_modernized_tokens -v`
Expected: FAIL — the current `style.css` has none of these tokens/classes.

- [ ] **Step 3: Replace `app/web/static/style.css` with:**

```css
:root {
  --bg: #ffffff;
  --bg-elevated: #f6f6f7;
  --fg: #171717;
  --fg-muted: #5c5c5f;
  --border: #dcdcde;
  --accent: #b3101f;
  --accent-fg: #ffffff;
  --error-bg: #fdeceb;
  --error-fg: #7a1810;
  --success-bg: #f2f2f3;
  --success-fg: #171717;
  --focus-ring: #b3101f;
  --radius: 0.5rem;
  --shadow: 0 1px 3px rgba(0, 0, 0, .12), 0 6px 16px rgba(0, 0, 0, .08);
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-5: 1.5rem;
  --space-6: 2.5rem;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d0d0e;
    --bg-elevated: #18181a;
    --fg: #f2f0ef;
    --fg-muted: #a8a6a5;
    --border: #302f31;
    --accent: #ff5b5b;
    --accent-fg: #1a0a0a;
    --error-bg: #3a1613;
    --error-fg: #ff9a90;
    --success-bg: #1c1c1e;
    --success-fg: #f2f0ef;
    --focus-ring: #ff5b5b;
    --shadow: none;
  }
}

:root[data-theme="dark"] {
  --bg: #0d0d0e;
  --bg-elevated: #18181a;
  --fg: #f2f0ef;
  --fg-muted: #a8a6a5;
  --border: #302f31;
  --accent: #ff5b5b;
  --accent-fg: #1a0a0a;
  --error-bg: #3a1613;
  --error-fg: #ff9a90;
  --success-bg: #1c1c1e;
  --success-fg: #f2f0ef;
  --focus-ring: #ff5b5b;
  --shadow: none;
}

:root[data-theme="light"] {
  --bg: #ffffff;
  --bg-elevated: #f6f6f7;
  --fg: #171717;
  --fg-muted: #5c5c5f;
  --border: #dcdcde;
  --accent: #b3101f;
  --accent-fg: #ffffff;
  --error-bg: #fdeceb;
  --error-fg: #7a1810;
  --success-bg: #f2f2f3;
  --success-fg: #171717;
  --focus-ring: #b3101f;
  --shadow: 0 1px 3px rgba(0, 0, 0, .12), 0 6px 16px rgba(0, 0, 0, .08);
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

h1 {
  font-size: 1.75rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  margin: 0 0 var(--space-4);
}

h2 {
  font-size: 1.25rem;
  font-weight: 600;
  margin: 0 0 var(--space-3);
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
  gap: var(--space-3);
  padding: var(--space-4);
  border-bottom: 2px solid var(--accent);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: 700;
  font-size: 1.125rem;
  color: var(--fg);
}

.brand svg {
  color: var(--accent);
  flex-shrink: 0;
}

nav[aria-label="Main"] {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

nav[aria-label="Main"] a,
nav[aria-label="Settings tabs"] a {
  color: var(--fg);
  text-decoration: none;
  font-size: 0.9375rem;
  font-weight: 500;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius);
}

nav[aria-label="Main"] a:hover,
nav[aria-label="Settings tabs"] a:hover {
  background: var(--bg-elevated);
}

nav[aria-label="Main"] a[aria-current="page"],
nav[aria-label="Settings tabs"] a[aria-current="page"] {
  background: var(--accent);
  color: var(--accent-fg);
  font-weight: 700;
}

nav[aria-label="Settings tabs"] {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-5);
}

main {
  max-width: 60rem;
  margin: 0 auto;
  padding: var(--space-5) var(--space-4);
}

footer {
  max-width: 60rem;
  margin: 0 auto;
  padding: var(--space-4);
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
  border-radius: var(--radius);
  padding: 0.5rem 0.875rem;
  cursor: pointer;
}

button:hover {
  border-color: var(--accent);
}

.btn-primary {
  background: var(--accent);
  color: var(--accent-fg);
  border: 1px solid var(--accent);
}

.btn-primary:hover {
  opacity: 0.9;
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
  margin-bottom: var(--space-3);
}

.card {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: var(--space-5);
  margin-bottom: var(--space-5);
}

fieldset {
  border: none;
  padding: 0;
  margin: 0;
}

legend {
  font-weight: 600;
  margin-bottom: var(--space-3);
  padding: 0;
}

.table-scroll {
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

table {
  border-collapse: collapse;
  width: 100%;
}

th, td {
  padding: var(--space-3);
  text-align: left;
  border-bottom: 1px solid var(--border);
}

tr:last-child td {
  border-bottom: none;
}

th {
  background: var(--bg-elevated);
  font-weight: 600;
}

tbody tr:hover {
  background: var(--bg-elevated);
}

.error {
  background: var(--error-bg);
  color: var(--error-fg);
  border-left: 4px solid var(--error-fg);
  border-radius: var(--radius);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-4);
}

.success {
  background: var(--success-bg);
  color: var(--success-fg);
  border-left: 4px solid var(--success-fg);
  border-radius: var(--radius);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-4);
}

nav[aria-label="Pagination"] {
  display: flex;
  gap: var(--space-4);
  align-items: center;
  margin-top: var(--space-4);
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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/web/test_base.py -v`
Expected: PASS (all tests in the file, including the pre-existing `test_static_assets_are_served`, which still checks for `"prefers-color-scheme"` — still present above).

- [ ] **Step 5: Commit**

```bash
git add app/web/static/style.css tests/web/test_base.py
git commit -m "feat: modernize theme CSS with red/white/black palette and components"
```

---

### Task 2: Preferences tab — route, template, tab nav link

**Files:**
- Modify: `app/web/routes_settings.py`
- Modify: `app/web/templates/settings_tabs.html`
- Create: `app/web/templates/settings_preferences.html`
- Test: `tests/web/test_settings.py`

**Interfaces:**
- Consumes: `.card` class from Task 1.
- Produces: `GET /settings/preferences` route rendering three radio inputs `name="theme"` with `value="light"|"dark"|"system"`, none checked server-side (Task 3's `theme.js` sets the checked state client-side based on `localStorage`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_settings.py`:

```python
def test_settings_preferences_page_shows_theme_radios(client):
    resp = client.get("/settings/preferences")

    assert resp.status_code == 200
    assert 'name="theme" value="light"' in resp.text
    assert 'name="theme" value="dark"' in resp.text
    assert 'name="theme" value="system"' in resp.text


def test_settings_tabs_include_preferences_link(client):
    resp = client.get("/settings/preferences")

    assert 'href="/settings/preferences" aria-current="page"' in resp.text
    assert 'href="/settings/email"' in resp.text
    assert 'href="/settings/data"' in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_settings.py::test_settings_preferences_page_shows_theme_radios tests/web/test_settings.py::test_settings_tabs_include_preferences_link -v`
Expected: FAIL — `/settings/preferences` doesn't exist yet (404).

- [ ] **Step 3: Add the Preferences link to `app/web/templates/settings_tabs.html`**

Replace the file's contents with:

```html
<nav aria-label="Settings tabs">
  <a href="/settings/email" {% if request.url.path == "/settings/email" %}aria-current="page"{% endif %}>Email</a>
  <a href="/settings/data" {% if request.url.path == "/settings/data" %}aria-current="page"{% endif %}>Data</a>
  <a href="/settings/preferences" {% if request.url.path == "/settings/preferences" %}aria-current="page"{% endif %}>Preferences</a>
</nav>
```

- [ ] **Step 4: Create `app/web/templates/settings_preferences.html`**

```html
{% extends "base.html" %}
{% block content %}
{% include "settings_tabs.html" %}
<h1>Preferences</h1>
<div class="card">
  <fieldset>
    <legend>Theme</legend>
    <label><input type="radio" name="theme" value="light"> Light</label>
    <label><input type="radio" name="theme" value="dark"> Dark</label>
    <label><input type="radio" name="theme" value="system"> Match system</label>
  </fieldset>
</div>
{% endblock %}
```

- [ ] **Step 5: Add the route to `app/web/routes_settings.py`**

Insert this route directly after `show_settings_data` (after line 45, before the `clear_cache` route):

```python
@router.get("/settings/preferences", response_class=HTMLResponse)
def show_settings_preferences(request: Request):
    return templates.TemplateResponse(request, "settings_preferences.html", {})
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/web/test_settings.py -v`
Expected: PASS (all tests in the file, including the existing Email/Data tests, which are unaffected).

- [ ] **Step 7: Commit**

```bash
git add app/web/routes_settings.py app/web/templates/settings_tabs.html app/web/templates/settings_preferences.html tests/web/test_settings.py
git commit -m "feat: add the Settings Preferences tab"
```

---

### Task 3: Theme control migration — header, theme.js, e2e tests

**Files:**
- Modify: `app/web/templates/base.html`
- Modify: `app/web/static/theme.js` (full rewrite)
- Modify: `tests/web/test_base.py`
- Modify: `tests/web/e2e/test_theme_toggle.py` (full rewrite)
- Modify: `tests/web/e2e/test_keyboard_navigation.py`

**Interfaces:**
- Consumes: `.brand` class (Task 1), `/settings/preferences` radios (Task 2).
- Produces: no more `#theme-toggle` button anywhere in the app; theme selection happens only via the three `input[name="theme"]` radios on `/settings/preferences`.

This task changes `base.html`, `theme.js`, and their tests together because they're tightly coupled — splitting the button removal from the JS rewrite and test updates would leave a task boundary where the app is broken (tests referencing a `#theme-toggle` that no longer exists).

- [ ] **Step 1: Write the failing backend tests**

In `tests/web/test_base.py`, replace the existing `test_theme_toggle_button_present` test with:

```python
def test_theme_toggle_button_removed_from_header(client):
    resp = client.get("/")

    assert 'id="theme-toggle"' not in resp.text


def test_brand_wordmark_present_in_header(client):
    resp = client.get("/")

    assert 'class="brand"' in resp.text
    assert "<svg" in resp.text
    assert "CareerSpyder" in resp.text


def test_theme_js_supports_three_way_choice(client):
    resp = client.get("/static/theme.js")

    assert resp.status_code == 200
    assert "system" in resp.text
    assert "removeItem" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_base.py -v`
Expected: `test_theme_toggle_button_removed_from_header` FAILs (button still present); `test_brand_wordmark_present_in_header` FAILs (no `.brand` yet); `test_theme_js_supports_three_way_choice` FAILs (old `theme.js` has no `"system"`/`removeItem`).

- [ ] **Step 3: Replace `app/web/templates/base.html` with:**

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
    <span class="brand">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
        <circle cx="10" cy="10" r="6"></circle>
        <line x1="14.5" y1="14.5" x2="20" y2="20"></line>
      </svg>
      CareerSpyder
    </span>
    <nav aria-label="Main">
      <a href="/" {% if request.url.path == "/" %}aria-current="page"{% endif %}>Dashboard</a>
      <a href="/history" {% if request.url.path == "/history" %}aria-current="page"{% endif %}>History</a>
      <a href="/sources" {% if request.url.path.startswith("/sources") %}aria-current="page"{% endif %}>Sources</a>
      <a href="/settings" {% if request.url.path.startswith("/settings") %}aria-current="page"{% endif %}>Settings</a>
    </nav>
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

(The anti-flash-of-unstyled-theme inline `<script>` in `<head>` is unchanged — it only ever special-cased `"dark"`/`"light"` and no-ops otherwise, which is still correct for `"system"`/absent.)

- [ ] **Step 4: Replace `app/web/static/theme.js` with:**

```js
(function () {
  var radios = document.querySelectorAll('input[name="theme"]');
  if (!radios.length) return;

  function storedTheme() {
    var stored = localStorage.getItem("theme");
    return stored === "light" || stored === "dark" ? stored : "system";
  }

  function applyTheme(theme) {
    if (theme === "system") {
      localStorage.removeItem("theme");
      document.documentElement.removeAttribute("data-theme");
    } else {
      localStorage.setItem("theme", theme);
      document.documentElement.setAttribute("data-theme", theme);
    }
  }

  var current = storedTheme();
  radios.forEach(function (radio) {
    radio.checked = radio.value === current;
    radio.addEventListener("change", function () {
      if (radio.checked) applyTheme(radio.value);
    });
  });
})();
```

- [ ] **Step 5: Run backend tests to verify they pass**

Run: `pytest tests/web/test_base.py -v`
Expected: PASS.

- [ ] **Step 6: Replace `tests/web/e2e/test_theme_toggle.py` with:**

```python
import pytest


@pytest.mark.parametrize("choice", ["dark", "light"])
def test_preferences_theme_radio_applies_and_persists(live_server, page, choice):
    page.goto(live_server + "/settings/preferences")

    page.check(f'input[name="theme"][value="{choice}"]')
    applied = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert applied == choice

    page.reload()
    persisted = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert persisted == choice
    assert page.is_checked(f'input[name="theme"][value="{choice}"]')


def test_preferences_system_choice_clears_explicit_override(live_server, page):
    page.goto(live_server + "/settings/preferences")

    page.check('input[name="theme"][value="dark"]')
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"

    page.check('input[name="theme"][value="system"]')
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") is None

    page.reload()
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") is None
    assert page.is_checked('input[name="theme"][value="system"]')
```

- [ ] **Step 7: Update `tests/web/e2e/test_keyboard_navigation.py`**

Replace `test_tab_order_reaches_theme_toggle_after_skip_link_and_nav` with:

```python
def test_tab_order_reaches_run_now_button_after_skip_link_and_nav(live_server, page):
    page.goto(live_server + "/")

    # skip-link, then the 4 nav links (Dashboard/History/Sources/Settings), then Run now
    for _ in range(6):
        page.keyboard.press("Tab")

    assert page.evaluate("document.activeElement.textContent.trim()") == "Run now"
```

(The `.brand` span in the header is not focusable, so the tab count from skip-link through the 4 nav links is unchanged from before; the 6th stop now lands on the first focusable element in `<main>` instead of the removed toggle button.)

- [ ] **Step 8: Run the e2e tests to verify they pass**

Run: `pytest tests/web/e2e -v`
Expected: PASS. (Requires Chromium via Playwright — if not already installed in this environment, run `playwright install --with-deps chromium` first.)

- [ ] **Step 9: Commit**

```bash
git add app/web/templates/base.html app/web/static/theme.js tests/web/test_base.py tests/web/e2e/test_theme_toggle.py tests/web/e2e/test_keyboard_navigation.py
git commit -m "feat: move theme control from a header toggle to the Preferences tab"
```

---

### Task 4: Visual polish — cards and primary buttons

**Files:**
- Modify: `app/web/templates/dashboard.html`
- Modify: `app/web/templates/settings_email.html`
- Modify: `app/web/templates/settings_data.html`
- Modify: `app/web/templates/source_form.html`
- Test: `tests/web/test_dashboard.py`, `tests/web/test_settings.py`, `tests/web/test_source_form.py`

**Interfaces:**
- Consumes: `.card`, `.btn-primary` classes from Task 1.
- No new interfaces produced — this task only changes markup/classes, not routes or template variables.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_dashboard.py`:

```python
def test_dashboard_run_now_button_is_primary(client):
    resp = client.get("/")

    assert 'class="btn-primary"' in resp.text
```

Add to `tests/web/test_settings.py`:

```python
def test_settings_email_save_button_is_primary(client):
    resp = client.get("/settings/email")

    assert 'class="btn-primary"' in resp.text


def test_settings_email_form_wrapped_in_card(client):
    resp = client.get("/settings/email")

    assert 'class="card"' in resp.text


def test_settings_data_page_wraps_sections_in_cards(client):
    resp = client.get("/settings/data")

    assert resp.text.count('class="card"') == 2
```

Add to `tests/web/test_source_form.py`:

```python
def test_source_form_save_button_is_primary(client):
    resp = client.get("/sources/new")

    assert 'class="btn-primary"' in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_dashboard.py tests/web/test_settings.py tests/web/test_source_form.py -v`
Expected: the 4 new tests FAIL (no `.card`/`.btn-primary` in current markup); all pre-existing tests in these files still PASS.

- [ ] **Step 3: Update `app/web/templates/dashboard.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>CareerSpyder</h1>
<form method="post" action="/run-now">
  <button type="submit" class="btn-primary">Run now</button>
</form>
<div class="card">
{% if last_run %}
  <p>Last run: {{ last_run.started_at }} — {{ last_run.new_job_count }} new job(s)</p>
  {% if last_run.failed_sources %}
    <p>Failed sources: {{ last_run.failed_sources | join(", ") }}</p>
  {% endif %}
{% else %}
  <p>No runs yet.</p>
{% endif %}
</div>
{% endblock %}
```

- [ ] **Step 4: Update `app/web/templates/settings_email.html`**

```html
{% extends "base.html" %}
{% block content %}
{% include "settings_tabs.html" %}
<h1>Email settings</h1>
<p>SMTP password is set via the <code>SMTP_PASSWORD</code> environment variable and is not editable here.</p>
<div class="card">
<form method="post" action="/settings/email">
  <label>SMTP host <input type="text" name="smtp_host" value="{{ settings.smtp_host }}"></label><br>
  <label>SMTP port <input type="number" name="smtp_port" value="{{ settings.smtp_port }}"></label><br>
  <label>SMTP user <input type="text" name="smtp_user" value="{{ settings.smtp_user }}"></label><br>
  <label>From address <input type="text" name="email_from" value="{{ settings.email_from }}"></label><br>
  <label>To address <input type="text" name="email_to" value="{{ settings.email_to }}"></label><br>
  <button type="submit" class="btn-primary">Save</button>
</form>
</div>
{% endblock %}
```

- [ ] **Step 5: Update `app/web/templates/settings_data.html`**

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

<div class="card">
<h2>Job cache</h2>
<p>Clears CareerSpyder's record of jobs it has already seen. The next run
will treat every currently known job as new and may send a large digest
email as a result.</p>
<form method="post" action="/settings/data/clear-cache">
  <button type="submit">Clear job cache</button>
</form>
</div>

<div class="card">
<h2>Sources</h2>
<p><a href="/settings/data/sources/export">Export sources</a></p>
<form method="post" action="/settings/data/sources/import" enctype="multipart/form-data">
  <label>Import sources <input type="file" name="file" accept="application/json"></label><br>
  <button type="submit">Import</button>
</form>
<p>Importing replaces the entire source list with the contents of the uploaded file.</p>
</div>
{% endblock %}
```

- [ ] **Step 6: Update the Save button in `app/web/templates/source_form.html`**

Change line 61 from:

```html
  <button type="submit">Save</button>
```

to:

```html
  <button type="submit" class="btn-primary">Save</button>
```

("Test this source" on line 59 keeps its default/secondary style — it's a preview action, not the page's primary action.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/web/test_dashboard.py tests/web/test_settings.py tests/web/test_source_form.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/web/templates/dashboard.html app/web/templates/settings_email.html app/web/templates/settings_data.html app/web/templates/source_form.html tests/web/test_dashboard.py tests/web/test_settings.py tests/web/test_source_form.py
git commit -m "feat: apply card and primary-button styling to Dashboard, Settings, and the source form"
```

---

### Task 5: Table cleanup — drop legacy inline attributes

**Files:**
- Modify: `app/web/templates/sources_list.html`
- Modify: `app/web/templates/history.html`
- Test: `tests/web/test_sources_list.py`, `tests/web/test_history.py`

**Interfaces:**
- Consumes: the `table`/`th`/`td` CSS from Task 1, which now owns all table borders/spacing (previously done via inline `border="1" cellpadding="4"` HTML attributes).
- No new interfaces produced.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_sources_list.py`:

```python
def test_sources_table_has_no_legacy_inline_attributes(client):
    resp = client.get("/sources")

    assert 'border="1"' not in resp.text
    assert 'cellpadding="4"' not in resp.text
```

Add to `tests/web/test_history.py`:

```python
def test_history_table_has_no_legacy_inline_attributes(client):
    resp = client.get("/history")

    assert 'border="1"' not in resp.text
    assert 'cellpadding="4"' not in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_sources_list.py::test_sources_table_has_no_legacy_inline_attributes tests/web/test_history.py::test_history_table_has_no_legacy_inline_attributes -v`
Expected: FAIL — both attributes are still present today.

- [ ] **Step 3: Update `app/web/templates/sources_list.html`**

Change line 6 from:

```html
<table border="1" cellpadding="4">
```

to:

```html
<table>
```

- [ ] **Step 4: Update `app/web/templates/history.html`**

Change line 5 from:

```html
<table border="1" cellpadding="4">
```

to:

```html
<table>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/web/test_sources_list.py tests/web/test_history.py -v`
Expected: PASS (including the pre-existing `test_sources_table_has_scoped_headers_and_scroll_wrapper` / `test_history_table_has_scoped_headers_and_scroll_wrapper`, unaffected).

- [ ] **Step 6: Commit**

```bash
git add app/web/templates/sources_list.html app/web/templates/history.html tests/web/test_sources_list.py tests/web/test_history.py
git commit -m "fix: drop legacy inline table attributes, styling now owned by CSS"
```

---

### Task 6: Docs and full-suite verification

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:** None — documentation only.

- [ ] **Step 1: Update the Features bullet in `README.md`**

Change (around line 42):

```markdown
- **Settings: Email and Data tabs** — `/settings/email` holds the SMTP
  config (unchanged); `/settings/data` adds a job-cache clear (clearing it
  makes the next run re-report every currently known job as new, which
  can trigger a large digest email) and sources.json import/export (import
  replaces the entire source list; export downloads the current one).
```

to:

```markdown
- **Settings: Email, Data, and Preferences tabs** — `/settings/email` holds
  the SMTP config (unchanged); `/settings/data` adds a job-cache clear
  (clearing it makes the next run re-report every currently known job as
  new, which can trigger a large digest email) and sources.json
  import/export (import replaces the entire source list; export downloads
  the current one); `/settings/preferences` holds the Light/Dark/System
  theme choice, previously a header toggle.
```

- [ ] **Step 2: Add a row to the Web UI table in `README.md`**

Change (around line 227-228):

```markdown
| `/settings/email` | SMTP host/port/from/recipient address. The SMTP password is intentionally not present here (see [Secrets](#secrets)). |
| `/settings/data` | Clear the job dedup cache (the next run will re-report every currently known job as new and may send a large digest email), and export/import `sources.json` (import replaces the entire source list). |
```

to:

```markdown
| `/settings/email` | SMTP host/port/from/recipient address. The SMTP password is intentionally not present here (see [Secrets](#secrets)). |
| `/settings/data` | Clear the job dedup cache (the next run will re-report every currently known job as new and may send a large digest email), and export/import `sources.json` (import replaces the entire source list). |
| `/settings/preferences` | Light/Dark/System theme choice. Stored in `localStorage` only, same as the header toggle it replaces — no server-side preference storage. |
```

- [ ] **Step 3: Add a CHANGELOG entry**

Add to the top of the `### Added` list under `## [Unreleased]` in `CHANGELOG.md`:

```markdown
- Modernized the web UI's visual theme (red/white/black palette, card
  layout, primary-button styling) and moved the Light/Dark theme toggle
  out of the header into a new `/settings/preferences` tab, expanded to a
  three-way Light/Dark/System choice.
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest -q`
Expected: PASS, 0 failures — this covers every backend (`TestClient`) and e2e (`Playwright`) test touched across Tasks 1-5, plus everything untouched (adapters, `db`, `config`, etc.).

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: document the Settings Preferences tab and theme redesign"
```
