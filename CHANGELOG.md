# Changelog

All notable changes to CareerSpyder are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.51.0] — 2026-08-31

### Fixed

- **"None" in Company field after a validation error (audit U1).** Submitting the Add
  Source form with Company left blank, then hitting a validation error, re-rendered the
  form with the literal text "None" in the Company input — `echo_source()` coerces a
  blank company to `None`, and the template's `{{ source.company if source else '' }}`
  rendered it because the echo object itself is always truthy. Fixed with
  `{{ source.company or '' }}`.
- **"Clear job cache" had no confirmation dialog (audit U3).** Every other destructive
  action on the Settings → Data page (Delete source, Import settings) used the app's
  `data-confirm-*` modal before submitting; Clear job cache was the lone exception
  despite its own warning about triggering a large digest email. Now wired to the same
  confirm-modal pattern.
- **Jobs Map container had no accessible name (audit A2).** The Leaflet `<div id="map">`
  had no `aria-label`, leaving the interactive region unnamed for screen-reader landmark
  navigation. Added `aria-label="Job locations map"`.

## [0.50.0] — 2026-08-30

### Added

- Dependabot

## [0.45.0] — 2026-08-25

### Added

- **State filter:** a State dropdown on the Jobs page and Jobs Map filters results by
  geocoded region (`geocoded_locations.region` as set by Nominatim). Populated dynamically
  from already-resolved job locations — no extra geocoding required.
- **Zip/location + radius filter:** a text input (zip code or city) paired with a miles
  dropdown (10 / 25 / 50 / 100 mi) on the Jobs page and Jobs Map. The input is geocoded
  on each filtered request via the existing Nominatim geocoder; jobs are filtered by
  haversine distance against their geocoded lat/lng. An inline warning is shown when the
  location string cannot be resolved, and the radius filter is skipped gracefully.
  Haversine distance is computed inside SQLite via a registered Python scalar function
  (`haversine_miles`) registered at DB init time.

### Changed

- **Live row updates** (issue #97): status, remove, duplicate, and location-override
  actions on the Jobs page now update in place via AJAX without refreshing the page,
  preserving active filters and sort state.
  - All four POST endpoints detect `Accept: application/json` and return a JSON response
    (`ok`, `message`, plus action-specific fields) instead of a redirect, so the existing
    HTML form fallback continues to work unchanged.
  - The status-change select submits via `fetch` on change; the remove trash-button
    intercepts form submit; the duplicate modal form submits via `fetch`; the
    location-override modal (which already used `fetch`) no longer calls
    `window.location.reload()`.
  - On success a toast notification is shown (using the existing `window.showToast` helper
    added to `toast.js`). On error the toast shows the server's detail message, and the
    status select reverts to its previous value.
  - Rows whose new state no longer matches the active filter (e.g. marked removed while
    the "Active" filter is on, or marked duplicate while duplicates are hidden) are dimmed
    to `opacity: 0.45` via a new `tr.filter-mismatch` CSS class rather than disappearing,
    so the user can keep acting on them.
  - A new `base_location` field is returned by `db.list_jobs` and exposed as a
    `data-base-location` attribute on the location cell, so the location override modal
    can restore the original geocoded location when an override is cleared.

### Added

- **Failed Source Links** (issue #93): failed sources are now clickable links in both
  the email digest and the web dashboard.
  - Each failed source name is rendered as a hyperlink to the source's career site:
    Greenhouse (`boards.greenhouse.io/<token>`), Lever (`jobs.lever.co/<token>`),
    HealthcareSource (`pm.healthcaresource.com/CS/<site_id>`), and any source type that
    carries an explicit URL field.
  - Email links open in a new tab (`target="_blank" rel="noopener noreferrer"`).
  - Web dashboard links use the existing `_external_link` macro (new tab + arrow glyph +
    screen-reader hint) and are rendered as a `<ul>` list rather than comma-separated text.
  - Backward-compatible: old runs with plain-string failed source records in the database
    are deserialized gracefully (name preserved, URL shown as absent).

### Added

- **Job Duplication & Secondary Sources** (issue #82):
  - Any job can now be manually marked as a duplicate via a flag button (&#128258;) in the
    Title column. An optional "duplicate of" note records what the canonical listing is.
    Duplicate jobs are hidden from `/jobs`, `/jobs/map`, and the email digest by default;
    a new **Duplicates** filter dropdown lets you include or view only duplicates.
    Clearing the flag restores a job to normal visibility.
  - Sources can be designated **Secondary** (e.g. Indeed, LinkedIn) via a checkbox in the
    source form. Jobs from secondary sources are tagged with a **2°** badge in the Jobs table.
    The email digest appends `[Secondary]` to the source attribution for those jobs.
    Secondary jobs that are marked duplicate are silently excluded from the digest even when
    `resend_jobs` is enabled.

- **Location Override** (issue #84): a map-pin button (&#128205;) in each job's Location cell
  opens a modal where you can type a replacement location. The location is validated against
  the geocoding provider before saving — if it cannot be resolved to map coordinates the save
  is rejected with an error. Overridden locations are flagged with a pencil icon (&#9998;) in
  the Jobs table and in each job's map popup. Clicking the pin on an already-overridden row
  pre-fills the current override and offers a **Clear override** button to revert.

### Changed

- Both `/jobs` and `/jobs/map` now default the Status filter to **Active** (non-removed jobs
  only) on first load. The filter dropdown and URL reflect this default; selecting "All" in
  the dropdown overrides it. "Clear filters" resets to the same Active default (issue #85).

### Added

- A full application audit covering security, UI/UX, and accessibility —
  see [docs/audits/2026-08-19-app-audit.md](docs/audits/2026-08-19-app-audit.md).
  No Critical findings; one High (SSRF via user-configured source URLs,
  gated by a Medium CSRF finding) plus several Medium/Low UX, robustness,
  and accessibility gaps, now tracked in [ROADMAP.md](ROADMAP.md).
- Jobs map now defaults to a view fitted to whatever's plotted (instead of always opening
  centered on the continental US at a fixed zoom), and always shows a fixed home-location
  pin.
- A **Not Interested** job status, alongside the existing Applied/Ignored/Accepted/Rejected
  set on the Jobs page.
- A "hide Not Interested jobs on the map" preference (Settings > Preferences), on by
  default, so marking a job Not Interested also drops its pin from `/jobs/map`.
- Digest emails now show each job's status (when one is set), its source name, a "View all
  jobs" link back to the web app (requires the new `PUBLIC_BASE_URL` env var — omitted
  when unset), and the timestamp of the run that produced the digest.
- Job location map (`/jobs/map`, linked from the Jobs page): background geocoding of job
  locations via a swappable provider (Nominatim/OpenStreetMap by default, no API key), a
  cache of resolved coordinates, and a Leaflet-based map with clustered markers and a
  per-location job list popup. The Jobs table also gains a Location filter and cleaner
  location display, deduping scraped location text variants into one normalized name
  (issue #49).
- PWA install support: CareerSpyder can now be installed from the browser's
  Add to Home Screen / install prompt (manifest, app icons, standalone
  window). A minimal service worker shows a branded offline page when the
  network is unavailable; it does not cache job/source data or enable
  offline browsing, since that data is always live. The app also gains a
  favicon for the first time.

### Changed

- The Jobs page's Map view link, the Jobs Map page's Table view link, and the Sources
  page's Add source link are now prominent buttons in the top-right of the page title
  instead of plain text links, via new reusable `.page-header`/`.btn` styles.

### Fixed

- On mobile/narrow viewports the last table row (which renders as a stacked card)
  now shows row separators between its fields. Previously, the global CSS rule that
  strips the bottom border from the last desktop table row also removed all internal
  separators inside the last mobile card (issue #83).

- `docker-compose.prod.yml` now mounts `/app/config` and `/app/data` from
  named Docker volumes (`careerspyder_config`, `careerspyder_data`) instead
  of fixed absolute host-path bind mounts. A bind mount still ties
  persistence to a specific host directory existing and staying put; named
  volumes are keyed by name and Docker creates them automatically, which is
  a better fit for a manually managed deploy host. `docker-compose.yml`
  (local dev/CI) is unaffected — it keeps its relative bind mounts, since
  it always runs from a known checkout directory.
- Docs (`README.md`, `docs/USAGE.md`, the in-app `/guide` page, and the Settings → Data
  import/export hint) now mention the Not Interested job status, the "hide Not Interested
  jobs on the map" preference, and the `/jobs/map` page, all of which had shipped without
  being reflected in these references.

## [0.17.0] — 2026-08-17

### Added

- Baseline security response headers (`X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, `Content-Security-Policy`) applied
  app-wide via `app/web/security_headers.py`. Defense-in-depth only — the
  app still has no authentication, by design (see ROADMAP.md).
- `pytest-cov` coverage reporting in CI (`ci.yml`'s `test` job), and ruff's
  bandit-derived `S` rule set enabled in `pyproject.toml` for security
  linting.
- Docker image hardening: the server process now runs as a fixed
  non-root user (`1000:1000`), the `python:3.12-slim` base image is
  pinned by digest, and a `HEALTHCHECK` was added. A new
  `docker-entrypoint.sh` runs as root only long enough to `chown` the
  bind-mounted `./config`/`./data` to `1000:1000` on every start (so
  mismatched host ownership never breaks a deploy — no manual `chown`
  needed), then drops to the app user via `setpriv` before starting
  uvicorn. `docker.yml` now also lints the `Dockerfile` with hadolint
  and asserts the running server process isn't root (via `docker compose
  top`, since the image's default exec user is still root for the
  entrypoint's benefit). `dependabot.yml` now tracks the base image via
  the `docker` ecosystem. Closes ROADMAP's "Docker image hardening" item.
- `SECURITY.md` — vulnerability reporting and the project's documented
  security posture (trusted-network-only, no auth in v1).
- A real end-to-end `run_and_notify` test (`tests/test_scheduler.py`)
  exercising the actual orchestrator and digest builder together, rather
  than mocking both — closes ROADMAP's "scheduler test still mocks the
  orchestrator and digest builder" gap.

## [0.16.0] — 2026-08-17

### Changed

- Dates in the web UI (Jobs page found/removed/emailed/status-history
  timestamps, Dashboard run start/finish times) now display in the
  viewer's local timezone and locale instead of raw UTC. Formatting
  happens client-side, so the underlying data stays UTC and a
  JS-disabled browser still sees the original ISO timestamp. The digest
  email is unchanged (still UTC) since email clients can't reliably run
  JavaScript.

## [0.15.0] — 2026-08-16

### Added

- Job status tracking on the Jobs page — mark a job as Applied, Ignored,
  Accepted, or Rejected (or clear it back to no status) from an inline
  dropdown per row. Every change is timestamped and kept in a per-job
  history, viewable via an expandable "History" section on each row. A
  new Status filter narrows the table to a given status or to jobs with
  no status set (issue #48).

## [0.14.0] — 2026-08-16

### Added

- A toast confirmation appears after every save, update, or delete
  action (adding/editing/deleting a source, saving email or preference
  settings, clearing the job cache, importing settings) — auto-dismisses
  after a few seconds or can be closed manually (issue #45).
- Job posting links on the Jobs page now open in a new tab and show a
  `↗` icon indicating they leave the app (issue #46).

## [0.13.0] — 2026-08-16

### Added

- Column sorting (click a column header to sort ascending/descending)
  and light filters on the Jobs, Dashboard, and Sources tables — Jobs
  filters by company, source, removed/emailed status; Dashboard filters
  by whether a run had failed sources; Sources filters by type. All
  server-side and encoded in the URL, so results are correct across
  pagination and links are bookmarkable (issue #33).

## [0.12.0] — 2026-08-16

### Fixed

- "Run now" on the Dashboard silently did nothing on any day not
  included in the configured "check days" (Preferences) — the same
  day-of-week gate meant for the scheduled daily cron was incorrectly
  applied to the manual button too. Run now now always triggers a scrape
  regardless of the configured days (issue #42).
- Long unbroken strings (e.g. source URLs) on the Guide page overflowed
  their container instead of wrapping, widening the page past the
  viewport (issue #41).

### Added

- The Dashboard now shows past run executions in a paginated,
  auto-refreshing responsive table (reusing the former History page's
  table), with the Run now button at the top; the separate History page
  and nav link have been removed (issue #42).
- A themed, reusable confirm-modal dialog replaces the native
  `confirm()` popup previously used before importing settings, and now
  also guards source deletion, which previously had no confirmation at
  all (issue #40).

## [0.11.0] — 2026-08-16

### Fixed

- The source form had no visible URL field for `linkedin`/`indeed` sources
  — the only URL input lived inside the (hidden, for those types)
  `generic_html` fields panel, so there was no way to enter or edit one
  (issue #35). URL, and separately `max_pages`, are now each a single
  shared input revealed for every type that uses it.
- `max_pages` silently reverted to a type's default on save. Each of
  `infor`/`talentbrew`/`workday`/`findly` rendered its own `<input
  name="max_pages">`; a browser submits every same-named field in the DOM
  regardless of visibility, so on save the last one in document order
  silently overwrote whichever type was actually selected (issue #36).
  Consolidated to one shared field per the fix above.

### Added

- The "Test this source" preview on the source form now renders results
  as a table (Title, URL) instead of a long bullet list, paginated at 25
  rows per page (issue #37). Result URLs are scheme-sanitized
  server-side before being linked, matching the existing `/jobs`-page
  treatment of scraped URLs.

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

## [0.9.0] — 2026-08-16

### Added

- Settings export/import (Data tab) now also covers Preferences-tab
  settings — check days, resend behavior, and digest recipients —
  alongside the existing source list, in one `settings.json` file
  (issue #29). `preferences` is optional in an uploaded file; if
  absent, stored preferences are left untouched, so old sources-only
  exports still import cleanly.

## [0.8.0] — 2026-08-14

### Added

- `/jobs` page (issue #28) listing every job CareerSpyder has ever found —
  company, search name, linked title, location, date found, date removed
  (if no longer found), age in days, whether/when it was included in a
  digest email, and a summary (first 250 characters) where available.
- Removal tracking: a job is marked removed when its source scrapes
  successfully but no longer returns it, or when its source is deleted
  from `sources.json` entirely. A removed job that reappears in a later
  run is automatically reactivated. Reconciliation uses each source's
  unfiltered results, so tightening `include_keywords`/`exclude_keywords`
  can never make a still-live posting look removed.
- Email tracking: a job's emailed timestamp is set only when the digest
  email containing it actually sends successfully.
- `summary` field for `greenhouse` and `lever` sources — both APIs
  already return a job description (Greenhouse needs `content=true` on
  the request; Lever returns it by default), truncated to 250 characters.
  Other source types don't populate it, since that would require an
  extra per-job HTTP request.

### Security

- Hardened `app/textutils.py::safe_url_scheme` (shared by the digest
  email and the new `/jobs` page) against a scheme-detection bypass: a
  control character or Unicode whitespace embedded inside a scheme name
  (e.g. a raw vertical tab in `"java<TAB>script:alert(1)"`, written
  mid-word) made the underlying URL parser fail to detect any scheme at
  all, letting the raw string through the http(s)-only allowlist
  unchecked.

## [0.7.0] — 2026-08-14

### Added

- Preferences tab: choose which days of the week to check for jobs and
  send a digest, choose whether a still-listed job is resent in every
  digest or emailed once ever, and add multiple digest recipients. The
  "To address" field moved from the Email tab to Preferences as part of
  this; the Email tab now holds SMTP transport config only.

## [0.6.0] — 2026-08-14

### Added

- Form layout and CSS polish: labels stack above their inputs (checkboxes
  and radios stay inline), `select`/checkbox/radio/file inputs now match
  the styled text inputs instead of rendering as unstyled browser
  defaults, and the source form's per-type fields get a visual grouping
  border so it's clear which fields apply to the selected source type.

## [0.5.0] — 2026-08-14

### Added

- Modernized the web UI's visual theme (red/white/black palette, card
  layout, primary-button styling) and moved the Light/Dark theme toggle
  out of the header into a new `/settings/preferences` tab, expanded to a
  three-way Light/Dark/System choice.
- `docker.yml`'s build/scan/smoke-test job now publishes the image to Docker
  Hub (`jasonkryst/careerspyder`, tagged `:latest` and with the
  `pyproject.toml` version) on every push to `master`, after the existing
  Trivy scan and smoke test pass — never on PRs.
- `docker-compose.prod.yml` — a pull-only compose file for Portainer/production
  deployment, separate from `docker-compose.yml` (which still builds from
  source, since CI needs to test each PR's actual code).
- `infor` source type, for employers on Infor's Global HR /
  CandidateSelfService platform (e.g. Rush University Medical Center).
  Drives Playwright directly to reach job listings nested in a
  same-origin iframe and paginated via a JS grid — no public API or
  static HTML is available on this platform. No per-job link exists on
  this platform; the digest links to the listing page itself.
- `healthcaresource` source type, for employers on the
  HealthcareSource/symplr talent platform (e.g. Rush Copley Medical
  Center). Calls a directly-callable JSON API (no browser needed) and
  fetches every posting in one call — real per-job URLs, unlike the
  `infor` source type.
- `talentbrew` source type, for employers on Radancy's TalentBrew
  career-site platform (e.g. Northwestern Medicine). Calls the
  platform's internal AJAX results endpoint with an explicit Title-A-Z
  sort for deterministic pagination — the default "Relevancy" sort was
  verified to produce heavily overlapping, unreliable pages on a real
  site. Paginates up to the platform's own reported total page count.
- `workday` source type, for employers on Workday's recruiting platform
  (e.g. Duly Health and Care). Calls Workday's public CXS jobs API
  directly — no auth, no browser, and the same adapter works for any
  Workday tenant. Handles two verified pagination quirks: the reported
  result total is only trustworthy on the first page, and paging past
  the real end silently wraps back to page 1 instead of returning empty.
- `phenompeople` source type, for employers on Phenom People's
  "CareerConnect" career-site platform (e.g. Ascension Health). Calls
  the platform's own internal, unauthenticated JSON search endpoint —
  no cookies, no CSRF token, no browser — and fetches every matching job
  in a single call. An optional `state` field scopes results to one of
  the platform's own facets, since the unfiltered listing was found to
  be personalized to the requester's own IP-geolocated location rather
  than a stable nationwide list.
- `findly` source type, for employers on the Findly/Radancy career-site
  platform (e.g. Advocate Health). Calls the platform's shared,
  cross-tenant JSON API directly (no browser needed), paginating in
  fixed pages of 500 up to a configurable `max_pages`, with an explicit
  deterministic sort — a live smoke test found the API's default
  ordering shifts across paginated requests, producing duplicate jobs
  without one.
- Enhanced web UI (#12): responsive layout down to narrow/mobile viewports,
  light/dark theme (follows `prefers-color-scheme` by default, with a
  manual toggle that persists via `localStorage`), accessibility
  improvements (skip-to-content link, semantic landmarks, scoped table
  headers, visible focus outlines, `aria-current` on the active nav link),
  server-side pagination on the `/history` and `/sources` tables (25 rows
  per page via `?page=`), and a footer showing the app name and version.
- Settings page Data tab (#14): `/settings/data` adds a job-cache clear
  (empties the `jobs` dedup table so the next run re-reports every
  currently known job as new) and sources.json import/export (export
  downloads the current source list; import validates and replaces it
  entirely, rejecting bad JSON or schema-invalid sources without touching
  the file on disk). The existing SMTP settings form moved to
  `/settings/email`; `/settings` now redirects there.

## [0.1.0] — 2026-08-11

Initial release. A self-hosted Docker app that scrapes configured job
sources daily, dedupes against SQLite, emails a digest of new postings, and
provides a server-rendered web UI for managing sources and settings. Built
from `docs/superpowers/specs/2026-08-09-careerspyder-design.md` via
`docs/superpowers/plans/2026-08-09-careerspyder-v1.md`.

### Added

- `Job` model and a SQLite-backed store (`jobs`, `runs`, `settings` tables)
  with dedup-by-key, run-history tracking, and first-boot settings seeding
  from environment variables.
- `sources.json` config schema (pydantic, discriminated by `type`) with
  CRUD helpers, and per-source `include_keywords` / `exclude_keywords`
  filtering.
- Five source adapters, all sharing the `fetch(source, **injectable_io) ->
  list[Job]` signature so tests never touch the network or launch a real
  browser:
  - `greenhouse` and `lever` — direct calls to each ATS's public JSON board
    API.
  - `generic_html` — CSS-selector scraping over plain HTTP, or over a
    headless-Chromium render when `render_js: true`.
  - `linkedin` and `indeed` — best-effort headless-Chromium scraping,
    isolated from the other adapters so their breakage can't cascade.
- Orchestrator that runs every configured source, applies keyword filters,
  dedupes new jobs against the store, and records per-run history with
  per-source failure isolation (one bad source never blocks the rest).
- Digest builder (new jobs grouped by company + a failed-sources section)
  and an SMTP emailer; the digest is sent only when a run has at least one
  new job or one failure, and stays silent on a clean run.
- In-process daily scheduler (APScheduler) wired to the orchestrator and
  emailer.
- FastAPI web UI: dashboard with a "Run now" button, run history, a
  sources list with add/edit/delete, a source form with a live "test this
  source" preview endpoint, and a settings page for SMTP host/port/from/to
  (the SMTP password is intentionally never shown or editable here — env
  var only).
- Docker packaging (`Dockerfile`, `docker-compose.yml`, `.dockerignore`)
  for deployment as a Portainer stack, verified via a manual smoke test
  against a real public Greenhouse board.

### Fixed

Found by a whole-branch code review after the initial build and addressed
before this release:

- A fresh deploy had no `sources.json`, which 500'd every source-management
  page and crashed the daily cron job; missing config is now treated as an
  empty source list.
- Required source fields (`board_token`, `url`, CSS selectors) accepted
  empty strings from the source form, since hidden fields for other source
  types are still submitted by the browser; these fields now reject blank
  values, and blank/whitespace input re-renders the form with an error
  instead of saving a broken source or crashing at scrape time.
- Invalid form submissions and unknown source IDs returned raw HTTP 500s
  instead of a re-rendered form or a 404.
- The "test this source" preview endpoint ran its adapter call
  synchronously inside an `async def` handler, which could block all HTTP
  handling on the single Uvicorn process for the duration of a slow
  scrape or a Playwright launch.
- `smtplib.SMTP()` had no connect timeout, so a single wedged SMTP
  connection could permanently stall every future scheduled run (given
  APScheduler's default of one job instance at a time); email-send
  failures are now caught and logged instead of propagating.
- The shared SQLite connection had no lock around a run, so an overlapping
  "Run now" click and daily cron (or two "Run now" clicks) could both see
  the same jobs as new and send duplicate digest emails.
- Scraped URLs from the `indeed` and `generic_html` adapters were stored
  as-is, producing dead relative links in digest emails; they're now
  resolved to absolute URLs against the source's URL.
- `sources.json` was rewritten non-atomically (direct truncate-and-write),
  risking a corrupted config file on a crash or full disk mid-write; saves
  now write to a temp file and atomically swap it in.
- Jinja2 templates were loaded from a path relative to the process's
  current working directory and weren't included in the installed
  package's package data, so an installed (non-source-tree) deployment of
  the package would have no templates to render.
