# CareerSpyder — Design Spec

Date: 2026-08-09
Status: Approved for planning

## Purpose

CareerSpyder is a self-hosted job search assistant. It periodically checks a
list of company career pages, ATS platforms, and job boards for new postings
matching the user's interests, and emails a digest of newly found listings.
The user maintains the list of sources to check via a JSON config file — no
per-site scraping code should need to change when adding a new source of a
type CareerSpyder already supports.

## Deployment target

- Runs as a single long-lived Docker container, deployed via Portainer stack
  on a Proxmox-hosted Docker host.
- No external cron dependency — scheduling is internal to the app.

## Architecture

```
                    ┌────────────────┐
                    │  Web UI (FastAPI)│◄──── you, via browser
                    │  dashboard/config│
                    │  /settings       │
                    └────────┬────────┘
                             │ triggers / reads
                             v
Scheduler (daily) -> Orchestrator -> Adapters (per source type)
                           |
                           v
                    Dedup Store (SQLite: jobs, runs, settings)
                           |
                           v (new jobs + failed sources)
                    Digest Builder -> Emailer (SMTP)
```

The web UI and the scheduler run inside the same FastAPI process (scheduler
as a background task) — one container, one process, no separate frontend
build or additional services.

### Components

- **Web UI**: server-rendered pages (FastAPI + Jinja2) for viewing results,
  managing sources, triggering runs, and editing email settings. See "Web UI"
  section below for details.
- **Scheduler**: in-process (APScheduler), triggers one run per day at a
  configurable hour/timezone. The container stays running continuously.
- **Orchestrator**: loads `sources.json`, dispatches each source to the
  adapter matching its `type`, normalizes results into a common `Job` shape
  (`title`, `company`, `location`, `url`, `posted_date`, `source_name`),
  and isolates failures per-source (one bad source never blocks others).
- **Adapters** (one module per `type`):
  - `greenhouse` — calls Greenhouse's public JSON board API directly
    (`boards-api.greenhouse.io/v1/boards/{board_token}/jobs`). No HTML
    parsing; stable and low-maintenance.
  - `lever` — calls Lever's public JSON API directly
    (`api.lever.co/v0/postings/{board_token}`). Same rationale as Greenhouse.
  - `generic_html` — fetches `url` via plain HTTP by default, or via
    Playwright when `render_js: true` is set on the source; extracts
    listings using CSS selectors defined in the source config.
  - `linkedin` / `indeed` — Playwright-based, explicitly best-effort.
    Isolated from other adapters so breakage here (blocking, CAPTCHA,
    layout changes) never affects ATS/custom sources. Expected to need
    ongoing maintenance; a future iteration may replace these with official
    APIs/RSS feeds where available.
- **Dedup Store (SQLite, on a mounted volume)**: three tables:
  - `jobs` — one row per job, keyed by:
    - the platform's own job ID for `greenhouse`/`lever` (authoritative), or
    - a hash of `company + title + link URL` for `generic_html`/`linkedin`/
      `indeed` (best available stable identifier).
    A job is "new" if its key has not been seen in a prior run. New keys
    are recorded at the end of a successful run.
  - `runs` — one row per scheduled/manual run: `id`, `started_at`,
    `finished_at`, `new_job_count`, `failed_sources` (JSON list of source
    names). Powers the `/history` and `/` dashboard pages.
  - `settings` — single-row table holding SMTP host/port/from/to, edited
    via `/settings`.
- **Digest Builder**: builds an email body from "new jobs this run" (grouped
  by company/source) and "sources that failed this run". Produces nothing
  (no email sent) if both lists are empty.
- **Emailer**: sends the digest via SMTP. Host/port/from/to addresses come
  from the persisted settings store (editable via the UI); the SMTP
  password remains a container env var only (see "Web UI" and "Secrets"
  below).

## Web UI

No authentication in v1 — the container is only reachable on the trusted
home/Proxmox network. Auth can be added later if that changes.

- **`/` (Dashboard)**: last run time, new jobs found this run (grouped by
  company), failed sources this run, and a "Run now" button that triggers
  the orchestrator as a background task without blocking the page.
- **`/history`**: table of past runs — timestamp, new job count, failed
  source names.
- **`/sources`**: table of all configured sources with Edit/Delete actions
  and an "Add source" button.
- **`/sources/new` and `/sources/{id}/edit`**: structured form for one
  source at a time. The `type` field drives which other fields are shown
  (`board_token` for `greenhouse`/`lever`; `url` + four selector fields for
  `generic_html`; `url` only for `linkedin`/`indeed`), plus
  `include_keywords`/`exclude_keywords` as simple tag inputs on every type.
  Includes a **"Test this source"** button that runs the source's adapter
  once (using the in-progress form values, not yet saved) and shows a
  preview list of jobs it currently finds — lets you validate a new source
  (especially `generic_html` selectors) before committing it. Saving writes
  the change back to `sources.json` after re-validating the full file
  against the schema.
- **`/settings`**: form for SMTP host, port, from address, and recipient
  address. These are persisted in a `settings` table in SQLite (env vars
  are used only as first-boot defaults if the table is empty). The SMTP
  **password** is intentionally not editable here — see "Secrets" below.

### Secrets

The SMTP password stays a container env var (`SMTP_PASSWORD`) only — never
written to SQLite or shown/edited in the UI. Every other setting (host,
port, from/to addresses) is editable at runtime through `/settings`. This
avoids persisting a credential in plaintext on disk while still letting the
rest of the config be managed without a redeploy.

## Config schema (`/app/config/sources.json`, mounted volume)

Editable via the UI (`/sources`) or by hand; picked up on the next
scheduled run — no rebuild needed.

```json
{
  "sources": [
    {
      "name": "Acme Corp (Greenhouse)",
      "company": "Acme Corp",
      "type": "greenhouse",
      "board_token": "acme",
      "include_keywords": ["engineer"],
      "exclude_keywords": ["senior", "staff"]
    },
    {
      "name": "Beta Inc (Lever)",
      "company": "Beta Inc",
      "type": "lever",
      "board_token": "beta"
    },
    {
      "name": "Custom Co Careers",
      "company": "Custom Co",
      "type": "generic_html",
      "url": "https://customco.com/careers?q=backend+engineer",
      "render_js": false,
      "selectors": {
        "job_card": ".job-listing",
        "title": ".job-title",
        "link": "a.job-link",
        "location": ".job-location"
      }
    },
    {
      "name": "LinkedIn - Backend Remote",
      "company": null,
      "type": "linkedin",
      "url": "https://www.linkedin.com/jobs/search/?keywords=backend+engineer&f_WT=2"
    }
  ]
}
```

Rules:
- `type` determines which adapter handles the entry and which other fields
  are required (`board_token` for `greenhouse`/`lever`; `url` + `selectors`
  for `generic_html`; `url` only for `linkedin`/`indeed`).
- `include_keywords` / `exclude_keywords` are optional on every source type.
  If omitted, no additional filtering is applied beyond what the source
  itself returns (the URL/API query is trusted as-is).
- There is no global job-title list; each source carries its own optional
  filters, since scope can legitimately differ per source.

## Deployment details

- Docker image: Python slim base + FastAPI/Uvicorn + Playwright's Chromium
  dependency (required for `linkedin`/`indeed`/any `generic_html` source
  using `render_js: true`).
- Exposed port: `8080` (web UI), mapped in `docker-compose.yml`.
- Volumes:
  - `/app/config/sources.json` — source list (editable via UI or by hand).
  - `/app/data/state.db` — SQLite: dedup store, run history, and settings
    (excluding SMTP password); persists across restarts and redeploys.
- Environment variables (set via Portainer stack env or `.env`):
  `SMTP_PASSWORD` (required, never persisted elsewhere), plus first-boot
  defaults `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `EMAIL_FROM`, `EMAIL_TO`
  (only used to seed the `settings` table if it's empty — afterwards edit
  via `/settings`), `RUN_HOUR`, `TZ`.
- Ships with a `docker-compose.yml` usable directly as a Portainer stack
  definition.

## Error handling

- Each source is fetched inside its own try/except in the orchestrator;
  a single source failing (site down, selector no longer matches, platform
  blocked the request) never stops other sources from being processed.
- Failures are logged to stdout (visible via Portainer container logs) and
  collected into a short "Sources that failed this run" section appended to
  the digest email.
- Email send rule: send if there are new jobs OR failures to report; stay
  silent only when the run was clean with zero new jobs and zero failures.

## Testing plan

- Unit tests per adapter against saved fixture data (sample API JSON
  responses / sample HTML) — no live network calls in tests, so adapter
  logic is verified independent of live site availability.
- Unit tests for the dedup store: inserting a job twice reports "not new"
  the second time; a genuinely new job reports "new".
- Unit tests for include/exclude keyword filtering.
- One integration-style test running the full orchestrator against a fake
  config + mocked adapters, verifying digest content and the "skip email
  when nothing to report" behavior.
- Manual smoke test against real Greenhouse/Lever endpoints and one real
  `generic_html` page before first production deploy, since live-site
  behavior isn't fully captured by fixtures.
- Unit tests for source create/edit/delete round-tripping through
  `sources.json`, including schema validation rejecting an invalid save.
- One test covering the settings table's first-boot seeding from env vars,
  and that subsequent UI edits persist across a simulated restart.

## Explicitly out of scope for this iteration

- LinkedIn/Indeed official API or RSS integration (noted as a likely future
  replacement for the best-effort Playwright adapters).
- Authentication/access control on the web UI (trusted home network only
  for v1).
- Editing the SMTP password from the UI (stays env-var only; see
  "Secrets").
- Multi-user support — single recipient email address.
- Richer/async frontend (e.g. live-updating dashboard, SPA) — v1 is
  server-rendered pages with full page reloads.
