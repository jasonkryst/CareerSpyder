# Usage Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give CareerSpyder a usage guide reachable both as a written doc (`docs/USAGE.md`) and as a page inside the running web UI (`/guide`), plus example-value hints on the source-add/edit form, closing GitHub issue #13.

**Architecture:** A new FastAPI route (`app/web/routes_guide.py`) renders a new, hand-written Jinja2 template (`app/web/templates/guide.html`) that extends the existing `base.html` — same nav/header/footer/theme as every other page. A parallel, independently hand-written `docs/USAGE.md` covers the same three sections (getting started, web UI tour, source types & examples) for readers outside the app. `source_form.html`'s existing per-type `div#fields-{type}` blocks each gain a small `.hint` box with one or two example field values and a link to the matching `/guide#type-{type}` anchor.

**Tech Stack:** Python 3.12, FastAPI, Jinja2 (existing `Jinja2Templates` instance in `app/web/templating.py`), pytest + FastAPI `TestClient`. No new dependencies.

## Global Constraints

- No new runtime dependency — `docs/USAGE.md` and `/guide` are hand-written independently, not generated from one another (no markdown-parsing library).
- Match the existing site theme: `/guide` extends `base.html`, uses only existing CSS custom properties and classes (`.card`, `.table-scroll`, `table`/`th`/`td`) plus the new `.hint`/`code` rules this plan adds — no new colors or fonts.
- New template files are already covered by `pyproject.toml`'s `"app.web" = ["templates/*.html", "static/*"]` glob — no `pyproject.toml` change needed.
- Follow the existing one-router-per-section pattern (`app/web/routes_dashboard.py` etc.) for the new `/guide` route.
- Every new source-type example value must match an existing, already-published example in this repo (README's field-reference table or an adapter test fixture) — no invented domains beyond the one placeholder noted in Task 2 for `infor` (which has no concrete example anywhere yet).

---

### Task 1: `/guide` route, skeleton template, and nav link

**Files:**
- Create: `app/web/routes_guide.py`
- Create: `app/web/templates/guide.html` (skeleton only — full content in Task 2)
- Modify: `app/web/main.py`
- Modify: `app/web/templates/base.html:33-38`
- Test: `tests/web/test_guide.py` (new)
- Test: `tests/web/test_base.py` (extend)

**Interfaces:**
- Produces: `GET /guide` route returning HTML built from `guide.html`. `guide.html` extends `base.html` and is addressable by later tasks (Task 2 fills in its content; Task 4's hint links point at `/guide#type-{type}` anchors Task 2 adds).

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_guide.py`:

```python
def test_guide_page_returns_200(client):
    resp = client.get("/guide")

    assert resp.status_code == 200
    assert "Usage Guide" in resp.text


def test_guide_nav_link_marks_current_page(client):
    resp = client.get("/guide")

    assert 'href="/guide" aria-current="page"' in resp.text
    assert 'href="/" aria-current="page"' not in resp.text
```

Add to `tests/web/test_base.py` (append at end of file):

```python
def test_nav_includes_guide_link(client):
    resp = client.get("/")

    assert 'href="/guide"' in resp.text
    assert ">Guide<" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/web/test_guide.py tests/web/test_base.py::test_nav_includes_guide_link -v`
Expected: FAIL — `test_guide_page_returns_200` and `test_guide_nav_link_marks_current_page` fail with 404 (no `/guide` route yet); `test_nav_includes_guide_link` fails because the nav has no `Guide` link yet.

- [ ] **Step 3: Create the route**

Create `app/web/routes_guide.py`:

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web.templating import templates

router = APIRouter()


@router.get("/guide", response_class=HTMLResponse)
def guide(request: Request):
    return templates.TemplateResponse(request, "guide.html", {})
```

- [ ] **Step 4: Create the skeleton template**

Create `app/web/templates/guide.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1>Usage Guide</h1>
{% endblock %}
```

- [ ] **Step 5: Register the router**

Modify `app/web/main.py` — add the import alongside the other route imports (after line 13, `from app.web.routes_sources import router as sources_router`):

```python
from app.web.routes_guide import router as guide_router
```

And add the include alongside the other `include_router` calls (after line 52, `app.include_router(settings_router)`):

```python
app.include_router(guide_router)
```

- [ ] **Step 6: Add the nav link**

Modify `app/web/templates/base.html` lines 33-38, adding a fifth `<a>` after the Settings link:

```html
    <nav aria-label="Main">
      <a href="/" {% if request.url.path == "/" %}aria-current="page"{% endif %}>Dashboard</a>
      <a href="/history" {% if request.url.path == "/history" %}aria-current="page"{% endif %}>History</a>
      <a href="/sources" {% if request.url.path.startswith("/sources") %}aria-current="page"{% endif %}>Sources</a>
      <a href="/settings" {% if request.url.path.startswith("/settings") %}aria-current="page"{% endif %}>Settings</a>
      <a href="/guide" {% if request.url.path == "/guide" %}aria-current="page"{% endif %}>Guide</a>
    </nav>
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/web/test_guide.py tests/web/test_base.py -v`
Expected: PASS (all tests in both files)

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS, no regressions (216 existing + 3 new = 219 passed)

- [ ] **Step 9: Commit**

```bash
git add app/web/routes_guide.py app/web/templates/guide.html app/web/main.py app/web/templates/base.html tests/web/test_guide.py tests/web/test_base.py
git commit -m "feat: add /guide route and nav link"
```

---

### Task 2: Guide page content — getting started, web UI tour, source-type reference

**Files:**
- Modify: `app/web/templates/guide.html` (replace skeleton body from Task 1)
- Test: `tests/web/test_guide.py` (extend)

**Interfaces:**
- Consumes: `guide.html` skeleton from Task 1 (extends `base.html`, registered at `/guide`).
- Produces: One `id="type-{type}"` anchor per source type for all 11 types (`greenhouse`, `lever`, `generic_html`, `linkedin`, `indeed`, `infor`, `healthcaresource`, `talentbrew`, `workday`, `phenompeople`, `findly`) — Task 4's hint links (`/guide#type-{type}`) depend on these exact anchor IDs existing.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_guide.py`:

```python
import pytest

ALL_SOURCE_TYPES = [
    "greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor",
    "healthcaresource", "talentbrew", "workday", "phenompeople", "findly",
]


@pytest.mark.parametrize("source_type", ALL_SOURCE_TYPES)
def test_guide_has_anchor_for_every_source_type(client, source_type):
    resp = client.get("/guide")

    assert f'id="type-{source_type}"' in resp.text


def test_guide_has_getting_started_and_web_ui_tour_sections(client):
    resp = client.get("/guide")

    assert "Getting started" in resp.text
    assert "Web UI tour" in resp.text
    assert "Source types" in resp.text


def test_guide_shows_example_values(client):
    resp = client.get("/guide")

    assert 'board_token: "acme"' in resp.text
    assert 'career_site_url: "https://jobs.ascension.org"' in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/web/test_guide.py -v`
Expected: FAIL — the 11 parametrized anchor tests, the sections test, and the example-values test all fail (skeleton template has none of this content).

- [ ] **Step 3: Write the full guide content**

Replace the contents of `app/web/templates/guide.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1>Usage Guide</h1>

<h2>Getting started</h2>
<ol>
  <li>Open the web UI and go to <a href="/sources">Sources</a>.</li>
  <li>Click <strong>Add source</strong>, pick a <strong>Type</strong>, and fill in its fields
    &mdash; see <a href="#source-types">Source types &amp; examples</a> below for example
    values.</li>
  <li>Click <strong>Test this source</strong> to preview the jobs it currently finds before
    saving.</li>
  <li>Click <strong>Save</strong>.</li>
  <li>Go to the <a href="/">Dashboard</a> and click <strong>Run now</strong> to trigger an
    immediate scrape.</li>
  <li>Check <a href="/history">History</a> for the run's result, or wait for the digest email
    if new jobs were found.</li>
</ol>
<p>After that, CareerSpyder scrapes automatically once a day at the configured hour &mdash; no
  further action needed unless you're adding more sources or changing settings.</p>

<h2>Web UI tour</h2>
<div class="table-scroll">
<table>
  <tr><th scope="col">Page</th><th scope="col">Purpose</th></tr>
  <tr><td><a href="/">Dashboard</a></td><td>Last run time and new-job count, plus a
    <strong>Run now</strong> button.</td></tr>
  <tr><td><a href="/history">History</a></td><td>Table of past runs &mdash; start/finish time,
    new job count, failed source names.</td></tr>
  <tr><td><a href="/sources">Sources</a></td><td>Table of configured sources with Edit/Delete
    actions and an <strong>Add source</strong> button.</td></tr>
  <tr><td><a href="/settings/email">Settings &rarr; Email</a></td><td>SMTP host/port/from
    address (the password is a container env var, not editable here).</td></tr>
  <tr><td><a href="/settings/data">Settings &rarr; Data</a></td><td>Clear the job dedup cache,
    and export/import <code>sources.json</code>.</td></tr>
  <tr><td><a href="/settings/preferences">Settings &rarr; Preferences</a></td><td>Theme, which
    days to check for jobs, resend behavior, and digest recipients.</td></tr>
</table>
</div>

<h2 id="source-types">Source types &amp; examples</h2>
<p>Every source has a <strong>Type</strong> that determines which other fields are required.</p>

<div class="card" id="type-greenhouse">
<h3>greenhouse</h3>
<p>Calls Greenhouse's public JSON board API directly. Requires the token from the ATS's board
  URL (<code>boards.greenhouse.io/&lt;board_token&gt;</code>).</p>
<p><strong>Example:</strong> <code>board_token: "acme"</code></p>
</div>

<div class="card" id="type-lever">
<h3>lever</h3>
<p>Calls Lever's public JSON board API directly. Same shape as <code>greenhouse</code>.</p>
<p><strong>Example:</strong> <code>board_token: "beta"</code></p>
</div>

<div class="card" id="type-generic_html">
<h3>generic_html</h3>
<p>Fetches any careers page via plain HTTP (or a headless-Chromium render when the page needs
  JavaScript) and extracts listings with CSS selectors you define.</p>
<p><strong>Example:</strong></p>
<ul>
  <li><code>url: "https://customco.com/careers?q=backend+engineer"</code></li>
  <li><code>render_js: false</code> (set <code>true</code> if the page needs JavaScript to
    populate listings)</li>
  <li><code>selectors.job_card: ".job-listing"</code></li>
  <li><code>selectors.title: ".job-title"</code></li>
  <li><code>selectors.link: "a.job-link"</code></li>
  <li><code>selectors.location: ".job-location"</code> (optional)</li>
</ul>
</div>

<div class="card" id="type-linkedin">
<h3>linkedin</h3>
<p>Best-effort, Playwright-based scraping of a public LinkedIn job search results page.
  Fragile by nature (blocking, layout changes, CAPTCHAs); isolated so its breakage never
  affects other sources.</p>
<p><strong>Example:</strong>
  <code>url: "https://www.linkedin.com/jobs/search/?keywords=backend+engineer&amp;f_WT=2"</code></p>
</div>

<div class="card" id="type-indeed">
<h3>indeed</h3>
<p>Best-effort, Playwright-based scraping of a public Indeed job search results page. Same
  caveats as <code>linkedin</code>.</p>
<p><strong>Example:</strong>
  <code>url: "https://www.indeed.com/jobs?q=backend+engineer&amp;sc=0kf%3Aattr%28DSQF7%29%3B"</code></p>
</div>

<div class="card" id="type-infor">
<h3>infor</h3>
<p>For employers on Infor's Global HR / CandidateSelfService platform. There's no per-job link
  on this platform, so the digest links to the listing page itself.</p>
<p><strong>Example:</strong></p>
<ul>
  <li><code>url: "https://careers.example.com/go/All-Jobs/12345/"</code> (the full listing
    page URL)</li>
  <li><code>max_pages: 3</code> (default; bounds how many result pages are crawled per run)</li>
</ul>
</div>

<div class="card" id="type-healthcaresource">
<h3>healthcaresource</h3>
<p>For employers on the HealthcareSource/symplr talent platform (e.g.
  <code>pm.healthcaresource.com/CS/&lt;site_id&gt;</code>). Calls a directly-callable JSON API
  &mdash; no browser needed.</p>
<p><strong>Example:</strong> <code>site_id: "rcmc"</code></p>
</div>

<div class="card" id="type-talentbrew">
<h3>talentbrew</h3>
<p>For employers on Radancy's TalentBrew career-site platform (e.g. <code>jobs.nm.org</code>).
  <code>base_url</code> is just the site's origin.</p>
<p><strong>Example:</strong></p>
<ul>
  <li><code>base_url: "https://jobs.nm.org"</code></li>
  <li><code>max_pages: 60</code> (default safety cap)</li>
</ul>
</div>

<div class="card" id="type-workday">
<h3>workday</h3>
<p>For employers on Workday's recruiting platform &mdash; works identically for any Workday
  tenant. No auth, no browser needed.</p>
<p><strong>Example:</strong></p>
<ul>
  <li><code>career_site_url: "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly"</code></li>
  <li><code>max_pages: 60</code> (default)</li>
</ul>
</div>

<div class="card" id="type-phenompeople">
<h3>phenompeople</h3>
<p>For employers on Phenom People's "CareerConnect" career-site platform (e.g.
  <code>jobs.ascension.org</code>). No cookies, CSRF token, or tenant ID needed.</p>
<p><strong>Example:</strong></p>
<ul>
  <li><code>career_site_url: "https://jobs.ascension.org"</code></li>
  <li><code>state: "Illinois"</code> (optional; worth setting since unfiltered results are
    personalized to the requester's IP-geolocated location)</li>
</ul>
</div>

<div class="card" id="type-findly">
<h3>findly</h3>
<p>For employers on the Findly/Radancy career-site platform (e.g. Advocate Health at
  <code>careers.aah.org</code>). Needs the numeric tenant ID (<code>org_id</code>), found in
  the target site's <code>cws_opts</code> JS object.</p>
<p><strong>Example:</strong></p>
<ul>
  <li><code>org_id: "2297"</code></li>
  <li><code>career_site_url: "https://careers.aah.org"</code> (captured for documentation
    only; the adapter doesn't read it)</li>
  <li><code>max_pages: 20</code> (default)</li>
</ul>
</div>

<p><code>include_keywords</code> / <code>exclude_keywords</code> are optional on every type
  &mdash; case-insensitive title filters, matched against the job title only.</p>
{% endblock %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/web/test_guide.py -v`
Expected: PASS (all tests, including all 11 parametrized anchor cases)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add app/web/templates/guide.html tests/web/test_guide.py
git commit -m "feat: fill in guide page content with source-type examples"
```

---

### Task 3: `.hint` and `code` CSS

**Files:**
- Modify: `app/web/static/style.css`
- Test: `tests/web/test_base.py` (extend)

**Interfaces:**
- Produces: `.hint` class (used by Task 4's source-form example boxes and available for `guide.html` if needed) and a bare `code` element rule (used throughout `guide.html` from Task 2 and the hint boxes in Task 4).

- [ ] **Step 1: Write the failing test**

Add to `tests/web/test_base.py`:

```python
def test_style_css_defines_hint_and_code_rules(client):
    resp = client.get("/static/style.css")

    assert resp.status_code == 200
    assert ".hint {" in resp.text
    assert "code {" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_base.py::test_style_css_defines_hint_and_code_rules -v`
Expected: FAIL — neither rule exists in `style.css` yet.

- [ ] **Step 3: Add the CSS rules**

Modify `app/web/static/style.css` — insert after the existing `.type-fields` rule (after line 274, the closing `}` of `.type-fields`) and before the `fieldset` rule:

```css
.hint {
  background: var(--bg-elevated);
  border-left: 4px solid var(--accent);
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-3);
  margin-bottom: var(--space-3);
  font-size: 0.9375rem;
}

code {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 0.25rem;
  padding: 0.1rem 0.3rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.875em;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_base.py::test_style_css_defines_hint_and_code_rules -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add app/web/static/style.css tests/web/test_base.py
git commit -m "feat: add .hint and code styles"
```

---

### Task 4: Inline example hints on the source form

**Files:**
- Modify: `app/web/templates/source_form.html`
- Test: `tests/web/test_source_form.py` (extend)

**Interfaces:**
- Consumes: `.hint`/`code` CSS from Task 3; `/guide#type-{type}` anchors from Task 2.
- Produces: nothing consumed by later tasks — this is the last app-code task.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_source_form.py`:

```python
def test_new_source_form_shows_hint_for_every_type(client):
    resp = client.get("/sources/new")

    assert 'board_token: "acme"' in resp.text
    assert 'board_token: "beta"' in resp.text
    assert 'selectors.job_card: ".job-listing"' in resp.text
    assert "linkedin.com/jobs/search" in resp.text
    assert "indeed.com/jobs" in resp.text
    assert 'max_pages: 3' in resp.text
    assert 'site_id: "rcmc"' in resp.text
    assert 'base_url: "https://jobs.nm.org"' in resp.text
    assert 'career_site_url: "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly"' in resp.text
    assert 'career_site_url: "https://jobs.ascension.org"' in resp.text
    assert 'org_id: "2297"' in resp.text


def test_source_form_hints_link_to_guide_anchors(client):
    resp = client.get("/sources/new")

    assert 'href="/guide#type-greenhouse"' in resp.text
    assert 'href="/guide#type-findly"' in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/web/test_source_form.py::test_new_source_form_shows_hint_for_every_type tests/web/test_source_form.py::test_source_form_hints_link_to_guide_anchors -v`
Expected: FAIL — none of the hint content or `/guide#type-` links exist yet.

- [ ] **Step 3: Add a hint box to each `#fields-{type}` div**

Modify `app/web/templates/source_form.html` lines 17-54, adding one `<div class="hint">` as the first child of each `type-fields` div. Replace lines 17-54 with:

```html
  <div id="fields-greenhouse" class="type-fields">
    <div class="hint"><strong>Example:</strong> <code>board_token: "acme"</code> &mdash; <a href="/guide#type-greenhouse">full reference</a></div>
    <label>Board token <input type="text" name="board_token" value="{{ source.board_token if source and source.type in ['greenhouse', 'lever'] else '' }}"></label>
  </div>
  <div id="fields-lever" class="type-fields">
    <div class="hint"><strong>Example:</strong> <code>board_token: "beta"</code> &mdash; <a href="/guide#type-lever">full reference</a></div>
  </div>
  <div id="fields-generic_html" class="type-fields">
    <div class="hint"><strong>Example:</strong> <code>url: "https://customco.com/careers?q=backend+engineer"</code>, <code>selectors.job_card: ".job-listing"</code> &mdash; <a href="/guide#type-generic_html">full reference</a></div>
    <label>URL <input type="text" name="url" value="{{ source.url if source and source.type in ['generic_html', 'linkedin', 'indeed'] else '' }}"></label>
    <label>Render JS <input type="checkbox" name="render_js" {% if source and source.type == 'generic_html' and source.render_js %}checked{% endif %}></label>
    <label>Job card selector <input type="text" name="selector_job_card" value="{{ source.selectors.job_card if source and source.type == 'generic_html' else '' }}"></label>
    <label>Title selector <input type="text" name="selector_title" value="{{ source.selectors.title if source and source.type == 'generic_html' else '' }}"></label>
    <label>Link selector <input type="text" name="selector_link" value="{{ source.selectors.link if source and source.type == 'generic_html' else '' }}"></label>
    <label>Location selector <input type="text" name="selector_location" value="{{ source.selectors.location if source and source.type == 'generic_html' and source.selectors.location else '' }}"></label>
  </div>
  <div id="fields-linkedin" class="type-fields">
    <div class="hint"><strong>Example:</strong> <code>url: "https://www.linkedin.com/jobs/search/?keywords=backend+engineer&amp;f_WT=2"</code> &mdash; <a href="/guide#type-linkedin">full reference</a></div>
  </div>
  <div id="fields-indeed" class="type-fields">
    <div class="hint"><strong>Example:</strong> <code>url: "https://www.indeed.com/jobs?q=backend+engineer&amp;sc=0kf%3Aattr%28DSQF7%29%3B"</code> &mdash; <a href="/guide#type-indeed">full reference</a></div>
  </div>
  <div id="fields-infor" class="type-fields">
    <div class="hint"><strong>Example:</strong> <code>url: "https://careers.example.com/go/All-Jobs/12345/"</code>, <code>max_pages: 3</code> &mdash; <a href="/guide#type-infor">full reference</a></div>
    <label>URL <input type="text" name="infor_url" value="{{ source.url if source and source.type == 'infor' else '' }}"></label>
    <label>Max pages <input type="number" name="max_pages" value="{{ source.max_pages if source and source.type == 'infor' else 3 }}"></label>
  </div>
  <div id="fields-healthcaresource" class="type-fields">
    <div class="hint"><strong>Example:</strong> <code>site_id: "rcmc"</code> &mdash; <a href="/guide#type-healthcaresource">full reference</a></div>
    <label>Site ID <input type="text" name="site_id" value="{{ source.site_id if source and source.type == 'healthcaresource' else '' }}"></label>
  </div>
  <div id="fields-talentbrew" class="type-fields">
    <div class="hint"><strong>Example:</strong> <code>base_url: "https://jobs.nm.org"</code> &mdash; <a href="/guide#type-talentbrew">full reference</a></div>
    <label>Base URL <input type="text" name="base_url" value="{{ source.base_url if source and source.type == 'talentbrew' else '' }}"></label>
    <label>Max pages <input type="number" name="max_pages" value="{{ source.max_pages if source and source.type == 'talentbrew' else 60 }}"></label>
  </div>
  <div id="fields-workday" class="type-fields">
    <div class="hint"><strong>Example:</strong> <code>career_site_url: "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly"</code> &mdash; <a href="/guide#type-workday">full reference</a></div>
    <label>Career site URL <input type="text" name="career_site_url" value="{{ source.career_site_url if source and source.type == 'workday' else '' }}"></label>
    <label>Max pages <input type="number" name="max_pages" value="{{ source.max_pages if source and source.type == 'workday' else 60 }}"></label>
  </div>
  <div id="fields-phenompeople" class="type-fields">
    <div class="hint"><strong>Example:</strong> <code>career_site_url: "https://jobs.ascension.org"</code>, <code>state: "Illinois"</code> &mdash; <a href="/guide#type-phenompeople">full reference</a></div>
    <label>Career site URL <input type="text" name="phenompeople_career_site_url" value="{{ source.career_site_url if source and source.type == 'phenompeople' else '' }}"></label>
    <label>State <input type="text" name="state" value="{{ source.state if source and source.type == 'phenompeople' and source.state else '' }}"></label>
  </div>
  <div id="fields-findly" class="type-fields">
    <div class="hint"><strong>Example:</strong> <code>org_id: "2297"</code>, <code>career_site_url: "https://careers.aah.org"</code> &mdash; <a href="/guide#type-findly">full reference</a></div>
    <label>Org ID <input type="text" name="org_id" value="{{ source.org_id if source and source.type == 'findly' else '' }}"></label>
    <label>Career site URL <input type="text" name="findly_career_site_url" value="{{ source.career_site_url if source and source.type == 'findly' else '' }}"></label>
    <label>Max pages <input type="number" name="max_pages" value="{{ source.max_pages if source and source.type == 'findly' else 20 }}"></label>
  </div>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/web/test_source_form.py -v`
Expected: PASS (all tests in the file, including the two new ones)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add app/web/templates/source_form.html tests/web/test_source_form.py
git commit -m "feat: show example values on the source form for every type"
```

---

### Task 5: `docs/USAGE.md` and README link

**Files:**
- Create: `docs/USAGE.md`
- Modify: `README.md` (Further reading section)

**Interfaces:**
- Consumes: nothing from earlier tasks (independent artifact per the spec's "hand-written independently" decision).
- Produces: nothing consumed by other tasks — this is the last task in the plan.

- [ ] **Step 1: Write `docs/USAGE.md`**

Create `docs/USAGE.md`:

```markdown
# Usage Guide

A walkthrough of CareerSpyder's web UI, plus example configuration values
for every source type. For architecture and full configuration reference,
see [README.md](../README.md).

## Getting started

1. Open the web UI and go to **Sources**.
2. Click **Add source**, pick a **Type**, and fill in its fields — see
   [Source types & examples](#source-types--examples) below for example
   values.
3. Click **Test this source** to preview the jobs it currently finds
   before saving.
4. Click **Save**.
5. Go to the **Dashboard** and click **Run now** to trigger an immediate
   scrape.
6. Check **History** for the run's result, or wait for the digest email
   if new jobs were found.

After that, CareerSpyder scrapes automatically once a day at the
configured hour — no further action needed unless you're adding more
sources or changing settings.

## Web UI tour

| Page | Purpose |
|---|---|
| Dashboard (`/`) | Last run time and new-job count, plus a **Run now** button. |
| History (`/history`) | Table of past runs — start/finish time, new job count, failed source names. |
| Sources (`/sources`) | Table of configured sources with Edit/Delete actions and an **Add source** button. |
| Settings → Email (`/settings/email`) | SMTP host/port/from address (the password is a container env var, not editable here). |
| Settings → Data (`/settings/data`) | Clear the job dedup cache, and export/import `sources.json`. |
| Settings → Preferences (`/settings/preferences`) | Theme, which days to check for jobs, resend behavior, and digest recipients. |

This app also has an in-app copy of this page at `/guide`, one click from
any page's nav bar.

## Source types & examples

Every source has a **Type** that determines which other fields are
required.

### greenhouse

Calls Greenhouse's public JSON board API directly. Requires the token
from the ATS's board URL (`boards.greenhouse.io/<board_token>`).

**Example:** `board_token: "acme"`

### lever

Calls Lever's public JSON board API directly. Same shape as `greenhouse`.

**Example:** `board_token: "beta"`

### generic_html

Fetches any careers page via plain HTTP (or a headless-Chromium render
when the page needs JavaScript) and extracts listings with CSS selectors
you define.

**Example:**
- `url: "https://customco.com/careers?q=backend+engineer"`
- `render_js: false` (set `true` if the page needs JavaScript to populate
  listings)
- `selectors.job_card: ".job-listing"`
- `selectors.title: ".job-title"`
- `selectors.link: "a.job-link"`
- `selectors.location: ".job-location"` (optional)

### linkedin

Best-effort, Playwright-based scraping of a public LinkedIn job search
results page. Fragile by nature (blocking, layout changes, CAPTCHAs);
isolated so its breakage never affects other sources.

**Example:** `url: "https://www.linkedin.com/jobs/search/?keywords=backend+engineer&f_WT=2"`

### indeed

Best-effort, Playwright-based scraping of a public Indeed job search
results page. Same caveats as `linkedin`.

**Example:** `url: "https://www.indeed.com/jobs?q=backend+engineer&sc=0kf%3Aattr%28DSQF7%29%3B"`

### infor

For employers on Infor's Global HR / CandidateSelfService platform.
There's no per-job link on this platform, so the digest links to the
listing page itself.

**Example:**
- `url: "https://careers.example.com/go/All-Jobs/12345/"` (the full
  listing page URL)
- `max_pages: 3` (default; bounds how many result pages are crawled per
  run)

### healthcaresource

For employers on the HealthcareSource/symplr talent platform (e.g.
`pm.healthcaresource.com/CS/<site_id>`). Calls a directly-callable JSON
API — no browser needed.

**Example:** `site_id: "rcmc"`

### talentbrew

For employers on Radancy's TalentBrew career-site platform (e.g.
`jobs.nm.org`). `base_url` is just the site's origin.

**Example:**
- `base_url: "https://jobs.nm.org"`
- `max_pages: 60` (default safety cap)

### workday

For employers on Workday's recruiting platform — works identically for
any Workday tenant. No auth, no browser needed.

**Example:**
- `career_site_url: "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly"`
- `max_pages: 60` (default)

### phenompeople

For employers on Phenom People's "CareerConnect" career-site platform
(e.g. `jobs.ascension.org`). No cookies, CSRF token, or tenant ID needed.

**Example:**
- `career_site_url: "https://jobs.ascension.org"`
- `state: "Illinois"` (optional; worth setting since unfiltered results
  are personalized to the requester's IP-geolocated location)

### findly

For employers on the Findly/Radancy career-site platform (e.g. Advocate
Health at `careers.aah.org`). Needs the numeric tenant ID (`org_id`),
found in the target site's `cws_opts` JS object.

**Example:**
- `org_id: "2297"`
- `career_site_url: "https://careers.aah.org"` (captured for
  documentation only; the adapter doesn't read it)
- `max_pages: 20` (default)

---

`include_keywords` / `exclude_keywords` are optional on every type —
case-insensitive title filters, matched against the job title only.
```

- [ ] **Step 2: Link it from README.md**

Modify `README.md`'s "Further reading" list (lines 326-336) — add one line right after the opening `- [CHANGELOG.md](CHANGELOG.md)` entry:

```markdown
## Further reading

- [docs/USAGE.md](docs/USAGE.md) — usage guide with example values for
  every source type; also available in-app at `/guide`.
- [CHANGELOG.md](CHANGELOG.md) — what's shipped so far.
```

(Leave the rest of the existing list — ROADMAP.md, AGENTS.md, and the two `docs/superpowers/` references — unchanged below it.)

- [ ] **Step 3: Verify the new file and link**

Run: `python -m pytest -q`
Expected: PASS, no regressions (this task touches only markdown, so the full suite result is unchanged from Task 4)

Check the new file's structure directly:

Run: `grep -c "^### " docs/USAGE.md`
Expected: `11` (one `###` heading per source type)

Run: `grep -c "type-" docs/USAGE.md`
Expected: `0` (USAGE.md has no HTML anchors — those are `guide.html`-only; confirms the two files weren't accidentally merged)

- [ ] **Step 4: Commit**

```bash
git add docs/USAGE.md README.md
git commit -m "docs: add docs/USAGE.md usage guide, link from README"
```

---

## Final verification

After all five tasks:

- [ ] Run `python -m pytest -q` — expect the original 216 tests plus: 3 (Task 1) + 13 (Task 2: 11 parametrized + 2) + 1 (Task 3) + 2 (Task 4) = 235 passed, 0 failed.
- [ ] Start the app locally (`uvicorn app.web.main:app --reload --port 8080` with the env vars from `AGENTS.md`'s Commands section) and manually check: the `Guide` nav link appears on every page and highlights on `/guide`; `/guide` renders with all 11 source-type cards; `/sources/new` shows a hint box for the default-selected type and the boxes read correctly after switching `Type` in the dropdown; each hint's "full reference" link jumps to the matching `/guide#type-...` anchor; light and dark theme both render the `.hint`/`code` styling with readable contrast.
