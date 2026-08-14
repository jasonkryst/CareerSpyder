# Enhanced FED UI — Design Spec

Date: 2026-08-13
Status: Approved for planning

## Purpose

GitHub issue #12 asks for a better front-end: responsive layout, light/dark
mode, accessibility, pagination on large tables, an app name + version
footer, and positive/negative test coverage for the above. The issue left
the tech choice open ("react.js or vanilla js").

## Current state

CareerSpyder's web UI (`app/web/`) is five FastAPI routes rendering Jinja2
templates that all extend `templates/base.html`. `base.html` today has no
`<meta viewport>` tag, no CSS, no JS, and no `static/` directory exists at
all — every page is unstyled, browser-default HTML. The README and
ROADMAP explicitly record the v1 design decision to stay server-rendered
with full page reloads and no JS build step ("Richer frontend" is listed
as deliberately deferred, not accidental). `/history` queries up to 50 rows
with no pagination UI; `/sources` loads and renders every configured source
with no limit at all.

## Decision: vanilla CSS/JS, not React

React would require introducing a build step (bundler, node toolchain,
build artifacts to serve or bake into the Docker image) — a real
architecture change from the current single-container, full-page-reload
model, not just a UI change. This spec stays within the existing
architecture: hand-written CSS plus small, targeted vanilla JS (theme
toggle, the existing per-source-type field show/hide already in
`source_form.html`). No new runtime dependencies.

## Architecture additions

```
app/web/
  static/
    style.css     responsive layout, CSS custom properties for theming, a11y styles
    theme.js      toggle button wiring + localStorage persistence
  main.py          + app.mount("/static", StaticFiles(...))
  templating.py    + templates.env.globals["app_version"] set once at import time
  pagination.py    NEW — shared paginate(total, page, page_size) helper
```

`pyproject.toml`'s `[tool.setuptools.package-data]` currently ships only
`"app.web" = ["templates/*.html"]`. This spec adds `"static/*"` to that
list — otherwise `style.css`/`theme.js` would work in a source checkout
but go missing from the installed package / Docker image, since that's the
only mechanism that ships non-`.py` files under `app/`.

## Foundation: layout, theming, accessibility, footer

`base.html` changes:

- `<html lang="en">` and a `<meta name="viewport" content="width=device-width, initial-scale=1">` — missing today, and the root cause responsive layout doesn't work at all currently (mobile browsers render the desktop layout zoomed out instead of reflowing).
- A skip-to-content link (`<a class="skip-link" href="#main">Skip to content</a>`) as the first focusable element.
- Semantic landmarks: `<header>` (nav + theme toggle), `<nav aria-label="Main">`, `<main id="main">` wrapping `{% block content %}`, `<footer>`.
- Nav links get `aria-current="page"` on whichever matches the current path, computed from `request.url.path` (already available — every route already passes `request` into `TemplateResponse`).
- Footer: `CareerSpyder v{{ app_version }}`. `app_version` is read once via `importlib.metadata.version("careerspyder")` in `templating.py` and set as a Jinja global, so no individual route needs to pass it.
- A theme toggle `<button id="theme-toggle" aria-pressed="...">` in the header.
- A small **inline, non-deferred** `<script>` in `<head>` (before `style.css` loads) that reads `localStorage.getItem("theme")` and sets `data-theme` on `<html>` immediately. This has to run synchronously in `<head>`, not in the deferred `theme.js`, or a dark-mode user sees a flash of the light palette before the external script downloads and runs.

`style.css`:

- CSS custom properties on `:root` for colors/spacing; a `prefers-color-scheme: dark` media query redefines them; `[data-theme="dark"]`/`[data-theme="light"]` attribute selectors let the toggle override the OS preference. Palette chosen for WCAG AA contrast in both modes.
- Fluid container (`max-width` + padding, no fixed px layout), nav that wraps to multiple lines on narrow viewports instead of overflowing.
- Every `<table>` wrapped in a `<div class="table-scroll">` with `overflow-x: auto`, so a wide table scrolls within itself on narrow screens instead of breaking the page layout (the "must never scroll the whole page horizontally" rule).
- `:focus-visible` outlines kept visible (never `outline: none` without a replacement) — this is the single highest-impact a11y fix given the current UI has zero custom focus styling to begin with.

`theme.js`: click handler on `#theme-toggle` that flips `data-theme`, updates `aria-pressed`, and writes the choice to `localStorage`.

All five templates (`dashboard`, `history`, `sources_list`, `source_form`,
`settings`) get `<th scope="col">` on their table headers — currently
absent everywhere.

## Pagination

- `app/db.py`: `list_runs` gains `offset: int = 0`; new `count_runs(conn) -> int`.
- `app/web/pagination.py`: `paginate(total: int, page_int_or_str, page_size: int = 25) -> Pagination`, a small dataclass with `page`, `total_pages`, `offset`, `has_prev`, `has_next`. Invalid input (page `< 1`, non-integer, or `> total_pages`) **clamps** to the nearest valid page rather than raising — a bad `?page=` value degrades to a valid page instead of a 500 or a blank table. `total_pages` is always at least `1` (even when `total == 0`), so an empty table renders "Page 1 of 1" rather than "Page 1 of 0".
- `routes_history.py`: reads `?page=`, calls `count_runs` + `list_runs(limit=25, offset=...)`.
- `routes_sources.py`: reads `?page=`, slices the already-loaded `config.load_sources(...)` list in Python (it's a JSON file read, not a DB query — no `config.py` changes needed).
- Both templates get a `<nav aria-label="Pagination">` with Prev/Next links (disabled/omitted at the ends) and "Page X of Y" text. No numbered page list — simpler to build, fully keyboard/screen-reader operable, and avoids an unbounded row of page links for a very large table.

## Testing

**Extends `tests/web/` (TestClient, matches existing pattern):**

- Pagination: page 1 and page 2 show the expected, non-overlapping rows; `page=0`, negative, and non-numeric `page` values all clamp to page 1 instead of erroring; a `page` beyond the last page clamps to the last page.
- Footer contains the app name and the version string from `importlib.metadata`.
- `<th scope="col">` present on each table.
- Active nav link carries `aria-current="page"` on each of the five routes.

**New `tests/web/e2e/` (Playwright, no new dependency — already installed for the scraping adapters, just not the `pytest-playwright` plugin):**

- A session-scoped fixture starts the FastAPI app via `uvicorn.Server` on a background thread against a random localhost port, and launches one Playwright Chromium instance for the session; a function-scoped fixture opens/closes a fresh page per test.
- Theme toggle: click it, assert `data-theme` flips and the computed background color changes; reload the page and assert the choice persisted.
- Keyboard navigation: `Tab` from the top of the page reaches the skip link, then nav links, then the theme toggle, in that order.
- Responsive: at a 375px-wide viewport, assert `document.documentElement.scrollWidth <= window.innerWidth` (no horizontal page overflow) on a page with a table.

## Explicitly out of scope for this iteration

- **Authentication.** Unrelated to this issue; already tracked in ROADMAP.md.
- **Numbered pagination controls / configurable page size.** Prev/Next + "Page X of Y" covers the stated need; a query-param page size or jump-to-page control can be added later if wanted.
- **React or any JS build step.** Explicitly rejected above in favor of staying inside the current architecture.
- **Live-updating dashboard (polling/SSE for "Run now" status).** Already tracked separately in ROADMAP.md as "Richer frontend"; unrelated to this issue's scope.
