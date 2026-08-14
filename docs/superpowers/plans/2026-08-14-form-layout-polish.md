# Form Layout & CSS Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stack form labels above their inputs, style the currently-unstyled `select`/checkbox/radio/file controls to match the red/white/black theme, and visually group `source_form.html`'s per-source-type fields — then ship it as 0.6.0.

**Architecture:** CSS-only layout change (labels already contain their input as a child, so `display: flex; flex-direction: column` stacks them with zero template changes) plus template whitespace cleanup (removing now-redundant `<br>` tags). No new routes, no new dependencies, no `name=`/`value=` changes.

**Tech Stack:** Jinja2 templates, vanilla CSS, pytest + `TestClient`.

## Global Constraints

- CSS and template whitespace/structure only — no new form fields, no validation changes, no `name=`/`value=`/`id=`/`action=` attribute changes anywhere (spec: `docs/superpowers/specs/2026-08-14-form-layout-polish-design.md`).
- `:has()` is fine to use — this app is explicitly for a trusted private network with no stated legacy-browser floor, and it's supported by every current evergreen browser.
- No custom-styled file input, no custom `<select>` popup styling — out of scope per spec.
- Run `pytest -q` after every task.

---

### Task 1: CSS — stacked labels, styled controls, type-fields grouping

**Files:**
- Modify: `app/web/static/style.css`
- Test: `tests/web/test_base.py`

**Interfaces:**
- Produces (relied on by Task 2's visual result, though Task 2 needs no CSS class names — this is a pure styling task): updated `label`, new `input[type="checkbox"], input[type="radio"]`, new `input[type="file"]`, `select` joining the existing text/number input rule, new `.type-fields` rule.

- [ ] **Step 1: Write the failing test**

Add to `tests/web/test_base.py`:

```python
def test_style_css_defines_form_polish_rules(client):
    resp = client.get("/static/style.css")

    assert resp.status_code == 200
    assert "flex-direction: column" in resp.text
    assert 'input[type="checkbox"]' in resp.text
    assert "accent-color: var(--accent)" in resp.text
    assert ".type-fields {" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_base.py::test_style_css_defines_form_polish_rules -v`
Expected: FAIL — none of these rules exist in `style.css` yet.

- [ ] **Step 3: Update `app/web/static/style.css`**

Replace:

```css
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
```

with:

```css
input[type="text"], input[type="number"], select {
  background: var(--bg);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 0.25rem;
  padding: 0.375rem 0.5rem;
  width: 100%;
  max-width: 28rem;
}

input[type="file"] {
  border: 1px solid var(--border);
  border-radius: 0.25rem;
  padding: 0.375rem 0.5rem;
}

input[type="checkbox"], input[type="radio"] {
  accent-color: var(--accent);
  width: 1.05rem;
  height: 1.05rem;
}

label {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-1);
  margin-bottom: var(--space-3);
}

label:has(> input[type="checkbox"]),
label:has(> input[type="radio"]) {
  flex-direction: row;
  align-items: center;
  gap: var(--space-2);
}
```

Then add this new rule directly after the `.card` rule (so it sits near the other grouping/container styles):

```css
.type-fields {
  border-left: 3px solid var(--border);
  padding-left: var(--space-4);
  margin-bottom: var(--space-4);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/web/test_base.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add app/web/static/style.css tests/web/test_base.py
git commit -m "feat: stack form labels and style select/checkbox/radio/file inputs"
```

---

### Task 2: Templates — remove redundant `<br>` tags, group source-form keywords

**Files:**
- Modify: `app/web/templates/source_form.html`
- Modify: `app/web/templates/settings_email.html`
- Modify: `app/web/templates/settings_data.html`
- Test: `tests/web/test_source_form.py`, `tests/web/test_settings.py`

**Interfaces:**
- Consumes: Task 1's stacked-label CSS (spacing now comes from `label`'s `margin-bottom`, so `<br>` is redundant) and `.card` (already existed before this plan).
- No new interfaces produced.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_source_form.py`:

```python
def test_source_form_has_no_br_tags(client):
    resp = client.get("/sources/new")

    assert "<br>" not in resp.text
```

Add to `tests/web/test_settings.py`:

```python
def test_settings_email_has_no_br_tags(client):
    resp = client.get("/settings/email")

    assert "<br>" not in resp.text


def test_settings_data_has_no_br_tags(client):
    resp = client.get("/settings/data")

    assert "<br>" not in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_source_form.py::test_source_form_has_no_br_tags tests/web/test_settings.py::test_settings_email_has_no_br_tags tests/web/test_settings.py::test_settings_data_has_no_br_tags -v`
Expected: FAIL — all three templates still contain `<br>` tags.

- [ ] **Step 3: Remove `<br>` tags from `app/web/templates/source_form.html`**

Every occurrence of `</label><br>` in the file becomes `</label>` (16
occurrences — after Name, Company, Type, URL, Render JS, Job card
selector, Title selector, Link selector, Infor URL, Base URL, Workday
career site URL, PhenomPeople career site URL, Findly Org ID, Findly
career site URL, Include keywords, Exclude keywords). Do a literal
find-and-replace of `</label><br>` → `</label>` across the whole file —
every instance follows this exact pattern with no exceptions.

- [ ] **Step 4: Wrap the trailing keyword fields in a card in `app/web/templates/source_form.html`**

Change:

```html
  <label>Include keywords (comma separated) <input type="text" name="include_keywords" value="{{ source.include_keywords | join(', ') if source else '' }}"></label>
  <label>Exclude keywords (comma separated) <input type="text" name="exclude_keywords" value="{{ source.exclude_keywords | join(', ') if source else '' }}"></label>

  <button type="button" onclick="testSource()">Test this source</button>
```

to:

```html
  <div class="card">
  <label>Include keywords (comma separated) <input type="text" name="include_keywords" value="{{ source.include_keywords | join(', ') if source else '' }}"></label>
  <label>Exclude keywords (comma separated) <input type="text" name="exclude_keywords" value="{{ source.exclude_keywords | join(', ') if source else '' }}"></label>
  </div>

  <button type="button" onclick="testSource()">Test this source</button>
```

- [ ] **Step 5: Remove `<br>` tags from `app/web/templates/settings_email.html`**

All 5 occurrences of `</label><br>` (after SMTP host, SMTP port, SMTP
user, From address, To address) become `</label>`.

- [ ] **Step 6: Remove the `<br>` tag from `app/web/templates/settings_data.html`**

Change:

```html
  <label>Import sources <input type="file" name="file" accept="application/json"></label><br>
```

to:

```html
  <label>Import sources <input type="file" name="file" accept="application/json"></label>
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/web/test_source_form.py tests/web/test_settings.py -v`
Expected: PASS (all tests in both files, including every pre-existing
field-value round-trip test — no `name=`/`value=` attributes changed).

- [ ] **Step 8: Commit**

```bash
git add app/web/templates/source_form.html app/web/templates/settings_email.html app/web/templates/settings_data.html tests/web/test_source_form.py tests/web/test_settings.py
git commit -m "fix: remove redundant <br> tags now that CSS drives field spacing"
```

---

### Task 3: Version bump, docs, and full-suite verification

**Files:**
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`

**Interfaces:** None — version/docs only.

- [ ] **Step 1: Bump the version in `pyproject.toml`**

Change:

```toml
version = "0.5.0"
```

to:

```toml
version = "0.6.0"
```

- [ ] **Step 2: Add a CHANGELOG entry**

`CHANGELOG.md` currently has no `## [Unreleased]` header — the previous
release (`0.5.0`) converted it directly to a dated section and nothing
has re-added it since. Insert a new `## [0.6.0]` section directly above
the existing `## [0.5.0] — 2026-08-14` line. Change:

```markdown
## [0.5.0] — 2026-08-14
```

to:

```markdown
## [0.6.0] — 2026-08-14

### Added

- Form layout and CSS polish: labels stack above their inputs (checkboxes
  and radios stay inline), `select`/checkbox/radio/file inputs now match
  the styled text inputs instead of rendering as unstyled browser
  defaults, and the source form's per-type fields get a visual grouping
  border so it's clear which fields apply to the selected source type.

## [0.5.0] — 2026-08-14
```

- [ ] **Step 3: Reinstall the local editable package so version metadata is fresh**

Run: `python -m pip install -e . --no-deps -q`

- [ ] **Step 4: Run the full test suite**

Run: `pytest -q`
Expected: PASS, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: bump version to 0.6.0"
```
