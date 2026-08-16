# Themed Confirm Modal, Guide Overflow, Dashboard Run History — Design Spec

Date: 2026-08-16
Status: Approved for planning

## Purpose

Closes GH #40, #41, #42.

- **#40**: `/settings/data`'s import-settings confirmation uses a native
  `window.confirm()` — jarring, unthemed, inconsistent with the rest of
  the UI.
- **#41**: long unbroken strings (URLs) on the Guide page overflow their
  container instead of wrapping, pushing the page wider than the
  viewport.
- **#42**: the Dashboard's "Run now" button appears to do nothing. Also
  requests the Dashboard show past executions in a responsive table with
  Run now at the top.

Also fixes a bug found while investigating #42 (see below) and, per
review during brainstorming, adds a delete confirmation to the Sources
page using the same new modal component (previously had none at all).

## #41 — Guide page overflow

**Root cause:** `app/web/static/style.css`'s `code` rule (~line 332) sets
no `overflow-wrap`/`word-break`. Long unbroken strings inside `<code>` on
`guide.html` (e.g. the Indeed example URL, line 87) have no break
opportunity, so they overflow their `.card`/`main` container instead of
wrapping.

**Fix:**
- Add `overflow-wrap: anywhere;` to the `code` rule.
- Add `overflow-wrap: break-word;` to `main` as a defensive fallback for
  any other long token outside `<code>`.

No markup or template changes.

## #40 — Themed confirm modal

No modal/dialog component exists anywhere in the app (confirmed by
repo-wide grep for `modal`, `confirm(`, `<dialog`). Building a generic,
reusable component rather than a one-off, since it will immediately have
two call sites (import, delete) and likely more later.

**Component:**
- `app/web/templates/base.html`: one shared `<dialog id="confirm-modal"
  class="modal">` (heading, message paragraph, Cancel button, Confirm
  button), added once near the end of `<body>` so it's present on every
  page.
- `app/web/static/confirm-modal.js` (new): a single document-level
  `submit` event listener (submit events bubble, so this needs no
  per-form wiring). On submit of any `<form data-confirm-message="...">`:
  `preventDefault()`, populate the dialog from `data-confirm-title`
  (optional) / `data-confirm-message`, remember the form, `showModal()`.
  Confirm button re-submits the remembered form (marking it
  pre-confirmed via a dataset flag so the same listener doesn't
  re-intercept it) and closes the dialog; Cancel button and the dialog's
  native `cancel` event (Escape key) just close it and forget the form.
  If `HTMLDialogElement`/`showModal` isn't supported, the listener
  no-ops early and forms submit natively (no regression from today's
  behavior for that edge case).
- `app/web/static/style.css`: `dialog.modal` + `dialog.modal::backdrop` +
  `.modal-actions`, themed with the existing `--bg-elevated`, `--border`,
  `--radius`, `--shadow`, `--space-*` variables — same visual language as
  `.card`, not an OS dialog.
- `base.html`: add `<script src="/static/confirm-modal.js" defer>`.

**Call sites:**
- `app/web/templates/settings_data.html`: `#import-form` gets
  `data-confirm-title="Import settings"` /
  `data-confirm-message="Importing will replace your entire source
  list. Continue?"`. The old inline `<script>` with `confirm(...)` is
  deleted entirely.
- `app/web/templates/sources_list.html`: each per-row delete `<form>`
  gets `data-confirm-title="Delete source"` /
  `data-confirm-message="Delete '{{ s.name }}'? This can't be undone."`
  — closes a pre-existing gap where source deletion had zero
  confirmation.

## #42 — Dashboard: run-now bug fix + merge with History

### The actual bug behind "Run now does nothing"

`app/scheduler.py::run_and_notify()` is shared by the daily cron job
*and* `POST /run-now`. It opens with:

```python
if settings is not None and _today_code(tz) not in (settings["email_days"] or "").split(","):
    return
```

This day-of-week gate exists so the *scheduled* cron only fires on
configured "check days." But `run_now()` in `routes_dashboard.py` calls
the same function, so manually clicking Run now on a day that isn't in
`email_days` returns immediately — no `orchestrator.run_once`, no `runs`
row, no scrape. This is a functional bug, not just a feedback gap.

**Fix:** add `force: bool = False` to `run_and_notify`; the gate becomes
`if not force and settings is not None and ...`. The cron job
(`create_scheduler`) keeps `force=False`. `routes_dashboard.py::run_now`
calls it with `force=True`, so a manual Run now always actually runs.

### Merge with History

Per product decision: Dashboard absorbs History's table + polling;
`/history` is removed rather than duplicated.

- `app/web/routes_dashboard.py`:
  - `GET /` builds the same paginated context History used to
    (`db.count_runs` + `db.list_runs(limit=PAGE_SIZE, offset=...)` via
    `app.web.pagination.paginate`), rendering `dashboard.html` with a
    Run now button/status region at top, then the existing
    `_history_rows.html` partial (unchanged internals) below it.
  - New `GET /rows` mirrors the old `/history/rows` — same context,
    renders `_history_rows.html` alone (no page chrome) for AJAX
    refresh/pagination.
  - `POST /run-now`: unchanged background-task/redirect shape (still
    works with JS disabled), but now calls `run_and_notify(..., force=True)`.
- `app/web/templates/_history_rows.html`: its two pagination links
  (`/history?page=...`) become `/?page=...` — it's now only ever
  included from the Dashboard.
- Delete `app/web/routes_history.py`, `app/web/templates/history.html`,
  and the router registration/import in `app/web/main.py`.
- `app/web/static/history.js` → renamed `app/web/static/dashboard.js`:
  keeps its existing refresh/pagination/poll-while-in-progress logic
  (fetch target updates from `/history/rows` to `/rows`), and gains a
  submit handler on `#run-now-form`: `preventDefault()`, disable the
  button and set a status message, `fetch(form.action, {method:
  "POST"})`, then `refresh()` and resume the existing
  `managePolling()` loop (which will now find the new "in progress" row
  and keep polling every 10s until it finishes — same mechanism History
  already had, just reused). This replaces the full-page-reload
  redirect flow with an in-place update when JS is available.
- `app/web/templates/base.html`: remove the `/history` nav link; point
  the script tag at `dashboard.js` instead of `history.js`.

## Testing

TDD per this repo's convention — failing test, then implementation.

**#41**
- Positive: `code`/`main` rules in `style.css` contain the new
  `overflow-wrap` declarations (regression guard for the CSS fix
  landing/staying).
- Manual: load `/guide` in a real browser at a narrow viewport and
  confirm no horizontal scroll/overflow on the Indeed example.

**#40**
- Positive: `confirm-modal` dialog markup present in every page's
  response (spot-check a couple of routes); `/static/confirm-modal.js`
  served; `data-confirm-message` present on the import form and on each
  delete form in `/sources`.
- Negative: no `confirm(` call remains anywhere under `app/web`
  (grep-style assertion or just manual removal verification — the old
  inline script is deleted, not just neutered).
- Manual: exercise import and delete in a real browser — Cancel leaves
  the source list/sources untouched, Confirm proceeds, Escape closes
  without submitting.

**#42**
- Positive (`tests/test_scheduler.py`): `run_and_notify(conn,
  sources_path, force=True)` calls `orchestrator.run_once` even when
  `email_days` excludes today / is empty.
- Negative: `run_and_notify(conn, sources_path)` (default `force=False`)
  still skips the run in that case — existing
  `test_run_and_notify_skips_entire_run_when_no_days_selected` stays
  green unmodified.
- Positive (`tests/web/test_dashboard.py`, absorbing `test_history.py`'s
  cases): `GET /` and `GET /rows` paginate identically to what
  `/history`/`/history/rows` used to (page params, clamping, `data-label`
  cells, scoped headers, in-progress → finished transition); `POST
  /run-now` still 303-redirects to `/` for the no-JS path and is called
  with `force=True` (assert via monkeypatching
  `app.web.routes_dashboard.run_and_notify`).
- Negative: `GET /history` and `GET /history/rows` return 404 (route
  removed).
- Manual: click Run now in a real browser on a day not in configured
  `email_days`, confirm a run actually happens and the table updates via
  polling without a manual refresh.

## Documentation + version

- `CHANGELOG.md`: new `## [0.12.0]` entry under `Fixed` (#40, #41, #42
  — call out the run-now day-gate bug explicitly, it's the most
  significant fix) and `Added` (delete confirmation on Sources, as a
  side effect of building the modal).
- `pyproject.toml`: `0.11.0` → `0.12.0`.
- `README.md`: merge the `/history` row into the `/` row in the Web UI
  table; update the `/settings/data` row's confirmation wording; the
  Orchestrator table row already just says "records run history," no
  change needed there.
- `docs/USAGE.md` + `app/web/templates/guide.html` (the in-app copy of
  the same tour): same Web UI table merge; update the numbered
  "Getting started" step that currently says "Check **History**..." to
  point at the Dashboard instead.
- `ROADMAP.md`: remove the "a similar live-updating indicator on the
  Dashboard's Run now button is a reasonable next step" bullet (~line
  59-62) — this closes it.

## Explicitly out of scope

- Any other confirmation dialogs beyond import and source-delete (e.g.
  clear-job-cache already has no confirm; leaving as-is unless asked).
- Changing the day-of-week (`email_days`) gating semantics for the
  *scheduled* cron run — only the manual Run now path bypasses it.
- A "cancel a running scrape" control — out of scope, no such mechanism
  exists today for either path.
