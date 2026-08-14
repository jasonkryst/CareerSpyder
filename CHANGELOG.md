# Changelog

All notable changes to CareerSpyder are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

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
