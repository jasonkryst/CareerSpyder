# Toast Feedback & External Links — Design Spec

Date: 2026-08-16
Status: Approved for planning

## Purpose

Closes GH #45 ("Toast/Headings On Change" — "When a save/update/delete
Operation occurs, provide a toast dialog and/or heading text to provide
receipt") and GH #46 ("External Links - Open New Tab and Icon indicator
after link text when external").

Both issues were under-specified (#46 had no body at all). Scope was
clarified directly with the user — see Decisions below. The two features
are unrelated in mechanism but small enough, and touch enough of the same
shared files (`base.html`, `style.css`), to ship as one branch, matching
this repo's existing pattern of bundling a few small UI issues into one
PR (e.g. `#40, #41, #42`).

## Decisions (from user clarification)

| Question | Decision |
|---|---|
| #45 feedback mechanism | A new floating toast component (not just the existing inline `.success`/`.error` banner pattern) |
| #45 scope | Unify **every** mutating action under the new mechanism — including Settings/Data's `clear-cache`/`import`, which already had ad hoc inline banners |
| #46 scope | Only the Jobs table's title link (`job.safe_url`) — the only genuinely external link in the app today. Built as a reusable macro so future external links pick up the same treatment automatically |
| #46 icon | A plain unicode `↗` glyph, matching the repo's existing glyph-based indicators (▲/▼ sort arrows, `&rarr;` in `guide.html`) rather than an SVG |

## Toast notifications (#45)

### Mechanism

New `app/web/flash.py`:

```python
def flash_redirect(path: str, message: str, status_code: int = 303) -> RedirectResponse
```

Builds `f"{path}?{urlencode({'flash': message})}"` and returns a
`RedirectResponse`. No `category`/severity parameter — every current call
site is a success confirmation (validation failures never redirect, they
re-render the same page inline with `error` in context, unchanged by this
work), so a single visual style is all that's needed. Adding an unused
`category` param now would be speculative.

`base.html` reads `request.query_params.get("flash")` on every render. If
present, it renders inside a new `<div id="toast-container" aria-live="polite"
aria-atomic="true">` (placed once, near the end of `<body>`, alongside the
existing `#confirm-modal`):

```html
<div class="toast" role="status">
  {{ flash }}
  <button type="button" class="toast-close" aria-label="Dismiss">&times;</button>
</div>
```

New `app/web/static/toast.js` (vanilla JS IIFE, same shape as
`confirm-modal.js` — no build step, no dependencies):
- On load, if a `.toast` element exists: auto-dismiss (fade out, then
  remove from DOM) after 5 seconds.
- Wires the `.toast-close` button to dismiss immediately.
- Either way, uses `history.replaceState` to strip `flash` from the
  current URL so a page refresh or browser back/forward doesn't
  redisplay the same toast.
- Progressive enhancement: with JS disabled, the toast still renders as a
  static banner (acceptable fallback, same as today's `.success` divs);
  it just won't auto-dismiss or clean the URL.

Registered in `base.html` next to the other static script tags:
`<script src="/static/toast.js" defer></script>`.

### Coverage — every mutating route gets a message

| Route | Message |
|---|---|
| `POST /sources/new` (success) | `"Source added."` |
| `POST /sources/{id}/edit` (success) | `"Source saved."` |
| `POST /sources/{id}/delete` | `"Source deleted."` |
| `POST /settings/email` | `"Email settings saved."` |
| `POST /settings/preferences` (success) | `"Preferences saved."` |
| `POST /settings/data/clear-cache` | `"Job cache cleared. The next run will re-report every currently known job as new."` (unchanged copy, now delivered via `flash` instead of `?cleared=1`) |
| `POST /settings/data/import` (success) | `f"Imported {len(sources)} source(s)."`, or with `" and preferences."` appended when the upload included a `preferences` section (unchanged copy, now delivered via `flash` instead of `?imported=N&preferences=1`) |

`settings_data.html` loses its two `{% if request.query_params.get("cleared"|"imported") %}` blocks entirely — the global toast in `base.html` replaces them. The `{% if error %}` block in that template (and in `source_form.html`, `settings_preferences.html`) is untouched: those are synchronous re-renders on validation failure, not redirects, and stay exactly as they are.

Every route above currently returns `RedirectResponse(url=..., status_code=303)` directly; each becomes `return flash_redirect("<path>", "<message>")`.

### Styling

`app/web/static/style.css` additions:
- `.toast-container` — `position: fixed`, top-right corner, `z-index` above normal content, `display: flex; flex-direction: column; gap: var(--space-2);` so multiple toasts (edge case: rapid double-submit) stack rather than overlap.
- `.toast` — reuses the existing `--success-bg`/`--success-fg` tokens and `--radius`/`--shadow` (same visual language as today's `.success` banner, just floated), plus a `fadein`/`fadeout` keyframe animation and `display: flex; align-items: center; gap: var(--space-3);` to lay out the message and close button.
- `.toast-close` — minimal button reset (transparent background, inherits `--success-fg`, no border), matching the existing `.modal-actions` button conventions.

No new color tokens — everything comes from the existing `:root`/dark-theme variable set, so the toast is automatically theme-correct.

## External links (#46)

### Mechanism

New `app/web/templates/_external_link.html` (same macro pattern as the existing `_sort_header.html`):

```jinja
{% macro external_link(url, label) -%}
<a href="{{ url }}" target="_blank" rel="noopener noreferrer">{{ label }} <span aria-hidden="true">&#8599;</span><span class="sr-only"> (opens in new tab)</span></a>
{%- endmacro %}
```

- `rel="noopener noreferrer"` is mandatory alongside `target="_blank"` — without it, the newly opened page gets a `window.opener` handle back to the CareerSpyder tab (reverse-tabnabbing risk). Not a design choice, just correct practice.
- `↗` is `aria-hidden` (decorative); the actual "(opens in new tab)" signal for screen readers comes from the visually-hidden `.sr-only` span, reusing the class already defined in `style.css` (currently used for the nav hamburger's label).

`app/web/templates/jobs.html` imports it (`{% from "_external_link.html" import external_link %}`) and replaces the Title cell:

```jinja
<td data-label="Title">{{ external_link(job.safe_url, job.title) }}</td>
```

No other template changes — `guide.html`'s "full reference" links are same-origin anchors (`/guide#type-...`), and everything else in the nav/pagination/edit links is internal. Nothing else in the app currently links off-site.

### Styling

No new CSS strictly required — the icon is inline unicode text and inherits the surrounding link's color via `currentColor`. If the glyph reads too tight against the label during implementation, a small `margin-inline-start: var(--space-1)` on the icon span is a reasonable one-line addition, not a structural change.

## Testing

TDD per this repo's convention. Positive and negative cases:

**Toast** — split across existing per-route test files, matching current organization: Sources cases go in `tests/web/test_sources_list.py`, Settings cases (email/preferences/clear-cache/import) go in `tests/web/test_settings.py`.
- Positive: for each of the 7 routes above, `client.post(...)` with valid data → response is a 303 whose `Location` header contains `flash=`; following the redirect (`client.get` the `Location`, or `allow_redirects` if the test client already follows) renders the exact expected message text inside `.toast`.
- Negative: a validation failure (bad source form data, invalid email in preferences, non-JSON import file) does **not** redirect — asserts response status is `400` and the response body contains **no** `.toast`/`flash` markup (confirms failures stay on the inline-`error` path, untouched).
- Negative: a plain `GET` of any page with no `flash` query param renders no `.toast` element at all (guards against the toast always rendering regardless of the param).
- Negative: `GET /sources?flash=` (empty string) also renders no toast — mirrors the existing `query_url`/filter convention that an empty string means "absent".

**External link (`tests/web/test_jobs.py`)**
- Positive: `GET /jobs` with at least one job present — response contains `target="_blank"`, `rel="noopener noreferrer"`, and the `↗` glyph, all associated with the job's title link.
- Negative: an internal link on the same response (e.g. the "Clear filters" link, or a `Previous`/`Next` pagination link) does **not** carry `target="_blank"` — guards against the macro (or a copy-paste of its attributes) leaking onto internal links.

**e2e (`tests/web/e2e/`, Playwright)**
- Toast: submitting a source delete (or any one representative mutating action) shows a toast with the expected text; clicking its close button removes it; letting it sit for the auto-dismiss window confirms it disappears on its own (use a short-poll `wait_for_function` on the element being absent, not a hardcoded `sleep`, matching existing e2e conventions in this repo).
- External link: clicking a Jobs title link opens a **new** browser tab/page (Playwright's `context.expect_page()`) rather than navigating the current one — this is the one behavior a markup-only test can't fully confirm (a browser could theoretically ignore `target="_blank"`; real-browser e2e is the actual verification of "opens in new tab").

## Documentation + version

- `pyproject.toml`: `0.13.0` → `0.14.0`.
- `CHANGELOG.md`: new `## [0.14.0]` entry under `Added` — toast confirmations on every save/update/delete action (issue #45), and external job links opening in a new tab with an indicator icon (issue #46).
- `README.md`: mention toast confirmations and the external-link behavior in the `/jobs` row of the Web UI table (~line 232); no other rows need copy changes since the toast applies uniformly and isn't page-specific enough to call out per-row.
- `docs/USAGE.md`: mirror the same `/jobs` row wording.
- `app/web/templates/guide.html`: mirror the same Jobs row wording (this table's Jobs row was just added by the #33 branch, so this is a same-branch-adjacent touch, not a new gap).
- `ROADMAP.md`: no changes — nothing there references toasts or external links.

## Explicitly out of scope

- Toast messages for anything other than the 7 listed mutating routes (no toast on plain page loads, searches, or filter/sort navigation).
- Configurable auto-dismiss timing or toast position (fixed at 5s, top-right).
- A `category`/error-styled toast variant — nothing currently produces a flash-worthy failure path (all failures stay on the existing inline-`error` re-render), so building unused styling/plumbing for it now would be speculative.
- Detecting "external" generically by comparing hostnames — the app has exactly one external link today (job postings); the macro is reusable by future callers, but no host-comparison logic is being built ahead of a second real use case.
- Any change to `confirm-modal.js`'s delete-confirmation flow — the toast fires *after* a delete completes, it doesn't touch the existing confirm-then-submit behavior.
