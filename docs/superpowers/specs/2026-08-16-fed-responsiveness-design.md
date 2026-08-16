# FED — Better Responsiveness/UI/UX — Design Spec

Date: 2026-08-16
Status: Approved for planning

## Purpose

Closes GH #34. The issue bundles six loosely-specified UI/UX
complaints against the existing web UI (`7d30269` "Enhanced FED UI:
responsive, dark mode, a11y, pagination" and later work):

1. No dropdown for the main menu — it just wraps on narrow screens.
2. Table UI/UX could be better on narrow screens.
3. The recipient email field looks wrong in dark mode.
4. Email fields aren't validated.
5. Importing settings (which replaces the whole source list) has no
   confirmation step.
6. The history page is static — a run's status doesn't update without
   a manual page reload.

Each sub-item was scoped with the user before writing this spec (see
below); none of them individually is a large change, but the issue
touches most of the shared layout (`base.html`, `style.css`) plus three
page templates and two routers, so they're planned as one spec.

## Scope decisions (confirmed with user)

- **Main menu**: hamburger menu below a breakpoint. Nav links stay a
  normal inline list above the breakpoint (no change to desktop
  behavior or the existing keyboard-tab-order test).
- **Tables**: responsive card layout below the same breakpoint — each
  row becomes a stacked label/value card instead of a
  horizontally-scrolling table. Applies to History, Jobs, and Sources
  tables.
- **Email validation**: both client-side (`required` on top of the
  existing `type="email"` browser validation) and server-side
  (reject malformed addresses on `POST /settings/preferences`; drop
  malformed addresses when importing, consistent with how malformed
  `email_days`/`resend_jobs` are already handled on import).
- **History refresh**: manual "Refresh" button plus auto-polling while
  any visible run is in progress (no `finished_at`), stopping once
  nothing is in progress.
- **Import confirmation**: a plain `confirm()` dialog before submit —
  decided without a user round-trip, since it matches the issue's
  literal "Are you sure?" wording and the app's existing
  no-JS-framework, minimal-script style (`theme.js`, `preferences.js`
  are both small vanilla IIFEs with no confirmation-modal precedent to
  match instead).

A single new breakpoint, `40rem` (640px), is introduced for both the
hamburger nav and the card tables — the existing `30rem` breakpoint in
`style.css` is unrelated (it only stacks the header's brand/nav flex
row) and is left as-is.

## Current state

- `app/web/templates/base.html` renders `nav[aria-label="Main"]` as six
  plain links; `style.css` has no breakpoint that changes nav layout
  besides the `30rem` header-stacking rule.
- `app/web/static/style.css` has one shared rule for
  `input[type="text"], input[type="number"], select` (background,
  border, sizing) — `input[type="email"]` (used in
  `settings_preferences.html`'s recipient rows) is *not* included, so
  it falls back to UA default styling, which doesn't follow
  `--bg`/`--fg`/`--border` tokens and looks broken in dark mode.
- `app/web/routes_settings.py::save_preferences` writes whatever
  `email_to` values it receives with no format check;
  `_parse_preferences_import` is similarly permissive. Neither
  `settings_preferences.html`'s inputs have `required`.
- `app/web/templates/history.html`, `jobs.html`, `sources_list.html`
  each wrap a `<table>` in `.table-scroll` (horizontal scroll on
  overflow) with no narrow-screen alternative layout.
- `app/web/routes_history.py::history` is the only history route —
  full page render only, no fragment/JSON endpoint, no client script.
- `app/web/templates/settings_data.html`'s import `<form>` submits
  directly with no confirmation step; `POST
  /settings/data/import` replaces the entire source list
  (`config.import_sources_json`) unconditionally on success.

## 1. Hamburger main menu

- `base.html`: add a toggle `<button id="nav-toggle" aria-expanded="false" aria-controls="main-nav" class="nav-toggle">` inside `<header>`, before `<nav>`. Give the nav `id="main-nav"`.
- New `app/web/static/nav.js` (vanilla IIFE, same pattern as
  `theme.js`): on click, toggle `.open` on the nav and flip
  `aria-expanded`; close on outside click and on `Escape`; close (and
  reset state) on window resize back above the breakpoint so state
  doesn't get stuck open on desktop.
- `style.css`: `.nav-toggle` is `display: none` above `40rem` (matches
  current desktop appearance exactly — the existing keyboard-nav e2e
  test, which runs at the default/desktop viewport and expects exactly
  6 nav links between the skip-link and "Run now" in tab order, is
  unaffected). Below `40rem`, `.nav-toggle` becomes visible
  (hamburger icon via CSS, no new SVG needed — reuse a simple
  three-line unicode/CSS-drawn icon) and `nav[aria-label="Main"]` is
  hidden (`display: none` or off-canvas) unless `.open`, at which point
  it renders as a dropdown panel anchored under the header.
- `base.html` include order: `nav.js` loads `defer`, same as the other
  two scripts.

## 2. Responsive card tables

- Each table's `<td>` gets `data-label="{{ column header text }}"`
  (Jinja string literals, matching each `<th>`'s text) in
  `history.html`, `jobs.html`, `sources_list.html`.
- `style.css`: below `40rem`, `.table-scroll table`, `thead`, `tbody`,
  `th`, `td`, `tr` switch to `display: block`; `thead` is hidden
  (`display: none`); each `td` becomes a flex row with
  `td::before { content: attr(data-label); font-weight: 600; }` to
  show the label; each `tr` gets a card treatment (border, radius,
  margin) reusing `--border`/`--radius` tokens already defined.
- `.table-scroll` and its class stay in the markup exactly as today —
  `tests/web/test_history.py::test_history_table_has_scoped_headers_and_scroll_wrapper`
  asserts on it directly, and it's harmless once the table becomes
  `display: block` (overflow-x simply has nothing left to scroll).
- Sources table's two empty `<th></th>` action-column headers (Edit /
  Delete) need explicit `data-label` text (e.g. `"Actions"` reused for
  both, or `"Edit"`/`"Delete"` respectively) so the card view doesn't
  render a blank label above the edit link / delete button.

## 3. Email field dark-mode fix

One-line change: add `input[type="email"]` to the existing shared
selector in `style.css`:

```css
input[type="text"], input[type="email"], input[type="number"], select {
```

No markup or behavior change.

## 4. Email validation

- **Client-side**: add `required` to both the templated recipient row's
  `<input type="email">` and the one inside `<template
  id="email-recipient-template">` in `settings_preferences.html`. The
  existing `app/web/static/preferences.js` (add/remove recipient rows)
  needs no change — it clones the `<template>` content verbatim, so a
  `required` attribute added to the template markup is present on every
  cloned row automatically.
- **Server-side** (`routes_settings.py`):
  - Add `_is_valid_email(addr: str) -> bool` using a small regex
    (`^[^@\s]+@[^@\s]+\.[^@\s]+$` — deliberately loose, matching the
    level of rigor already used elsewhere in this codebase, e.g.
    `safe_url_scheme`; this is not meant to be RFC-5322-complete).
  - `save_preferences`: validate every non-blank `email_to` entry;
    if any fail, re-render `settings_preferences.html` with
    `status_code=400` and an `error` message instead of saving —
    mirroring the existing `import_settings` error-rendering pattern.
    This is a behavior change (previously any string was accepted) —
    intentional, matches the issue.
  - `_parse_preferences_import`: drop malformed addresses from the
    imported list rather than rejecting the whole import — consistent
    with its existing "lenient, defaults on bad data" handling of
    `email_days`/`resend_jobs`.

## 5. Import confirmation

- New tiny script (or inline `<script>` in `settings_data.html`,
  matching the file's existing lack of a dedicated JS file): wire the
  import `<form>`'s `submit` event to `confirm("Importing will
  replace your entire source list. Continue?")`, calling
  `event.preventDefault()` if the user cancels.
- No backend change — this is purely a client-side guard;
  server-side behavior (whole-list replace) is unchanged and already
  covered by existing tests.

## 6. History auto-refresh

- Extract the `<table>` + pagination `<nav>` block out of
  `history.html` into `app/web/templates/_history_rows.html`;
  `history.html` becomes a thin wrapper that includes it inside a
  `<div id="history-rows">` and adds a `<button id="refresh-history"
  type="button">Refresh</button>` plus an `aria-live="polite"` status
  span for screen-reader announcements ("Updated" / timestamp).
- `routes_history.py`: add `GET /history/rows?page=` returning just
  the rendered `_history_rows.html` fragment (same `paginate`/
  `list_runs` logic as `history`, factored into a shared helper to
  avoid duplicating the query/pagination code).
- New `app/web/static/history.js`: on load, `fetch('/history/rows?page='+currentPage)`
  and replace `#history-rows`'s content on manual button click. If any
  row in the current response has no "Finished" value (i.e. still
  showing "in progress"), start a 10s `setInterval` poll that re-fetches
  and re-swaps; clear the interval once no row is in progress. Current
  page number is read from the pagination `<span>` text or a
  `data-page` attribute set on the wrapper (simplest: template renders
  `data-page="{{ pagination.page }}"` on `#history-rows`, JS reads it
  fresh after each swap since the fragment re-renders it).

## Version and docs

- `pyproject.toml`: `0.9.0` → `0.10.0` (footer auto-updates via
  `importlib.metadata`, no template change needed).
- `CHANGELOG.md`: new `## [0.10.0]` entry summarizing all six changes,
  issue #34.
- `docs/USAGE.md`: update wherever it currently describes navigating
  the main menu, reading tables, or importing settings, to mention the
  hamburger menu / card layout on mobile, email validation, the import
  confirmation, and the history refresh button.

## Testing

Both positive and negative cases, per component:

- **Email validation** (`tests/web/test_settings.py`): valid address
  saves; malformed address on `POST /settings/preferences` returns 400
  with an error and does *not* save; malformed address inside an
  imported `preferences.email_to` list is silently dropped (import
  still succeeds) rather than rejecting the whole import.
- **Dark-mode CSS fix**: a lightweight assertion that
  `input[type="email"]` appears in the same CSS rule as
  `input[type="text"]` in `style.css` (string-level check, no browser
  needed) — plus the existing theme-toggle e2e coverage exercises the
  page it's on.
- **History fragment endpoint** (`tests/web/test_history.py`):
  `GET /history/rows` returns 200 with the same run rows as `/history`
  but without the outer page chrome (e.g. no `<nav aria-label="Main">`);
  pagination on the fragment endpoint behaves the same as today's
  `/history` pagination tests (page clamp on invalid/negative page).
- **Import confirmation**: a unit test asserting the confirm-guard
  script is present/wired on `/settings/data`'s page (string-level, e.g.
  `confirm(` appears associated with the import form); a Playwright e2e
  test that accepts the browser's `confirm()` dialog (import proceeds)
  and one that dismisses it (import does not proceed, page unchanged).
- **Hamburger menu (e2e, narrow viewport)**: toggle button is hidden at
  desktop width and visible at narrow width; clicking it reveals the
  nav and sets `aria-expanded="true"`; clicking again, pressing
  `Escape`, or clicking outside collapses it; all nav links remain
  reachable and operable via keyboard when open.
- **Card tables (e2e, narrow viewport)**: at `<40rem` a data cell's
  `data-label` renders next to its value (visual/DOM check, e.g. the
  `::before` content or an equivalent DOM-visible marker); at desktop
  width the table renders in its current grid form (no regression).
- **History auto-refresh**: unit test that `/history/rows` reflects a
  run's status change between two calls (start a run → fragment shows
  "in progress"; finish it → next fragment shows the finish time); e2e
  test (or a fast-timer unit test against the JS logic via a headless
  DOM, if practical) that polling stops once no run is in progress, and
  that the manual refresh button works even when nothing is in
  progress.
- Full existing suite (`pytest`, all Playwright e2e specs) must
  continue to pass unmodified except where this spec explicitly says a
  test's expectation changes (none do — all changes are additive or
  hidden above the `40rem` breakpoint).
