# CareerSpyder

CareerSpyder is a self-hosted job search assistant. It periodically checks a
list of company career pages, ATS platforms, and job boards for new postings
matching your interests, dedupes them against everything it's already seen,
and emails you a digest of what's new. You maintain the list of sources
through a small web UI (or by hand-editing a JSON file) — no code changes
are needed to add a new source of a type CareerSpyder already supports.

It runs as a single long-lived Docker container: one process serves both
the web UI and the daily background scrape, with no external cron
dependency and no separate frontend build.

## Features

- **Eleven source types**, one adapter each:
  - `greenhouse` / `lever` / `infor` / `healthcaresource` / `talentbrew` /
    `workday` / `phenompeople` / `findly` — call each ATS/career-site
    platform's own JSON API directly. No HTML parsing, no browser; stable
    and low-maintenance.
  - `generic_html` — fetch any careers page via plain HTTP (or a headless
    Chromium render when the page needs JavaScript) and extract listings
    with CSS selectors you define.
  - `linkedin` / `indeed` — best-effort, Playwright-based scraping of public
    job search result pages. Explicitly fragile (blocking, layout changes,
    CAPTCHAs); isolated so their breakage never affects the other sources.
  - See [Field reference](#sourcesjson) below for per-type required fields.
- **Per-source keyword filters** — optional `include_keywords` /
  `exclude_keywords` on every source, matched case-insensitively against the
  job title.
- **Per-source failure isolation** — one source erroring out (site down,
  selector no longer matches, platform blocked the request) never blocks
  the others; failures are logged and surfaced in the run history and in
  the digest email.
- **Dedup that persists** — every job is keyed by the platform's own job ID
  where one exists (Greenhouse, Lever, HealthcareSource, TalentBrew,
  Workday, PhenomPeople, Findly), the job's own URL (LinkedIn, Indeed), or
  a composite of company + title + link/location for platforms with
  neither (`generic_html`, Infor) — so a job is only ever reported "new"
  once, even across container restarts.
- **Job lifecycle tracking** — the `/jobs` page shows every job ever
  found, when it was first seen, when it was marked removed (its source
  scraped successfully without it, or the source was deleted), and
  whether it was included in a digest email.
- **Email digest** — sent only when a run finds at least one new job or at
  least one source failure; a clean run with nothing to report stays
  silent. Each job line shows its status when one is set and its source;
  the email also includes the run's search timestamp and, if
  `PUBLIC_BASE_URL` is configured, a link back to the `/jobs` page.
- **Server-rendered web UI** — dashboard, run history, source management
  (add/edit/delete with a live "test this source" preview before saving),
  and settings — no SPA, no JS build step, full page reloads.
- **Settings: Email, Data, and Preferences tabs** — `/settings/email` holds
  the SMTP transport config; `/settings/data` adds a job-cache clear
  (clearing it makes the next run re-report every currently known job as
  new, which can trigger a large digest email) and sources.json
  import/export (import replaces the entire source list; export downloads
  the current one); `/settings/preferences` holds the Light/Dark/System
  theme choice plus which days to check for jobs, whether a still-listed
  job is resent in every digest or only ever emailed once, one or
  more digest recipient addresses, and whether Not Interested jobs are
  hidden from the jobs map (on by default).
- **No database migration story to manage** — a single SQLite file holds
  dedup state, run history, and settings; it lives on a persistent Docker
  volume so it survives redeploys.

## Architecture

```
                    ┌──────────────────┐
                    │  Web UI (FastAPI) │◄──── you, via browser
                    │  dashboard/config │
                    │  /settings        │
                    └─────────┬────────┘
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

The web UI and the scheduler run inside the same FastAPI process — the
scheduler is an in-process APScheduler background job, not a separate
service. There is one container, one process.

| Layer | Module(s) | Responsibility |
|---|---|---|
| Adapters | `app/adapters/*.py` | Fetch + normalize one source type into `Job` objects. Every adapter has the shape `fetch(source, **injectable_io) -> list[Job]`, so tests can inject fakes instead of hitting the network or a real browser. |
| Orchestrator | `app/orchestrator.py` | Runs every configured source, applies keyword filters, dedupes across sources within a run, dedupes against SQLite, and records run history. Serializes concurrent runs with a lock so an overlapping "Run now" and daily cron can't double-report jobs. |
| Dedup store | `app/db.py` | SQLite: `jobs` (seen-before keys, status), `runs` (history), `settings` (SMTP host/port/from, recipient list, check days, resend flag, hide-Not-Interested-on-map flag — **not** the password, see [Secrets](#secrets)). |
| Digest | `app/digest.py` | Builds an HTML email body from "new jobs this run" (grouped by company, showing each job's status/source when set) and "sources that failed this run," plus the run's search timestamp and an optional "View all jobs" link. Returns `None` (no email sent) when there are no new jobs and no failures. All scraped text is HTML-escaped before landing in the email. |
| Emailer | `app/emailer.py` | Sends the digest via SMTP (STARTTLS, 30s timeout). |
| Scheduler | `app/scheduler.py` | APScheduler cron job, once daily at a configurable hour/timezone. Skips the scan and email entirely on days not selected in Preferences. Swallows and logs any email-send failure so a bad SMTP config can never crash the process or block future runs. |
| Web UI | `app/web/*.py` + `app/web/templates/*.html` | FastAPI routes + Jinja2 templates for `/`, `/jobs`, `/jobs/map`, `/sources`, `/settings`. |

## Quick start (Docker)

```bash
git clone <this repo>
cd CareerSpyder
docker build -t careerspyder:latest .
```

Copy `.env.example` to `.env` (gitignored — never commit real credentials)
and fill in at least your SMTP password:

```bash
cp .env.example .env
```

Then:

```bash
docker compose up -d
```

Open `http://localhost:32600/`, add a source or two under **Sources**, and
click **Run now** on the dashboard to trigger an immediate scrape. The
scheduler will otherwise run once a day on the `RUN_CRON` schedule in `TZ`.

## Configuration

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `SMTP_PASSWORD` | Yes, to send email | The SMTP account password. **Container env var only** — never written to disk, never shown or editable in the UI. See [Secrets](#secrets). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `EMAIL_FROM`, `EMAIL_TO` | No | First-boot defaults only. They seed the `settings` table the very first time the database is empty; after that, `/settings` is the source of truth and these env vars are ignored. |
| `RUN_CRON` | No (default `0 7 * * *`) | Cron expression (5 fields: `min hour dom month dow`) controlling when the daily scrape runs. `0 7 * * *` means 07:00 every day in `TZ`. See [crontab.guru](https://crontab.guru) for reference. |
| `TZ` | No (default `UTC`) | Timezone the scheduler and `RUN_CRON` are interpreted in. |
| `CAREERSPYDER_DB_PATH` | No (default `/app/data/state.db`) | SQLite file location. |
| `CAREERSPYDER_SOURCES_PATH` | No (default `/app/config/sources.json`) | Source list location. |
| `PUBLIC_BASE_URL` | No | The site's own public URL (e.g. `https://jobs.example.com`), used to build the "View all jobs" link in digest emails. Without it, the link is omitted. |

### `sources.json`

Mounted at `/app/config/sources.json` (`./config/sources.json` in the
provided `docker-compose.yml`). It's the single source of truth for what
gets scraped — edit it by hand or through the `/sources` UI, and it's
re-read on every run, no rebuild or restart needed. If the file doesn't
exist yet, CareerSpyder treats it as an empty source list rather than
failing.

Every source has a generated `id` (used by the UI for edit/delete links),
a `type` that determines which adapter handles it and which other fields
are required, and two optional keyword filters:

```json
{
  "sources": [
    {
      "id": "a1b2c3d4e5f6",
      "name": "Acme Corp (Greenhouse)",
      "company": "Acme Corp",
      "type": "greenhouse",
      "board_token": "acme",
      "include_keywords": ["engineer"],
      "exclude_keywords": ["senior", "staff"]
    },
    {
      "id": "b2c3d4e5f6a7",
      "name": "Beta Inc (Lever)",
      "company": "Beta Inc",
      "type": "lever",
      "board_token": "beta"
    },
    {
      "id": "c3d4e5f6a7b8",
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
      "id": "d4e5f6a7b8c9",
      "name": "LinkedIn - Backend Remote",
      "type": "linkedin",
      "url": "https://www.linkedin.com/jobs/search/?keywords=backend+engineer&f_WT=2"
    },
    {
      "id": "e5f6a7b8c9d0",
      "name": "Indeed - Backend Remote",
      "type": "indeed",
      "url": "https://www.indeed.com/jobs?q=backend+engineer&sc=0kf%3Aattr%28DSQF7%29%3B"
    }
  ]
}
```

Field reference:

| Type | Required fields | Notes |
|---|---|---|
| `greenhouse`, `lever` | `board_token` | The token in the ATS's board URL, e.g. `boards.greenhouse.io/<board_token>`. |
| `generic_html` | `url`, `selectors.job_card`, `selectors.title`, `selectors.link` | `selectors.location` is optional. Set `render_js: true` if the page needs JavaScript to populate listings (uses headless Chromium instead of a plain HTTP GET). |
| `linkedin`, `indeed` | `url` | Point at a job search results URL. Always uses headless Chromium — see the caveat below. |
| `infor` | `url` | For employers on Infor's Global HR / CandidateSelfService platform. `url` is the full listing page URL. `max_pages` (default 3) bounds how many pages of results are crawled per run — the board is sorted newest-first by default, so this captures the newest postings without a slow full-catalog crawl. There is no per-job link on this platform (confirmed via direct investigation): the digest links to the listing page itself, not the individual posting. |
| `healthcaresource` | `site_id` | For employers on the HealthcareSource/symplr talent platform (e.g. `pm.healthcaresource.com/CS/<site_id>`). Calls a directly-callable JSON API — no browser needed. Unlike `infor`, this platform has real per-job URLs and fetches every posting in one call (no pagination limit needed). |
| `talentbrew` | `base_url` | For employers on Radancy's TalentBrew career-site platform (e.g. `jobs.nm.org`). `base_url` is just the site's origin. Calls the platform's own internal AJAX results endpoint with an explicit Title-A-Z sort — the default "Relevancy" sort was found to paginate unreliably (heavily overlapping pages), so this adapter deliberately avoids it. Paginates automatically up to the platform's own reported total page count, capped by `max_pages` (default 60) as a safety backstop. A live smoke test found a small (~0.5%) rate of duplicate job keys even with the deterministic sort, likely from ties in title text at page boundaries on a constantly-changing live board — harmless, since the orchestrator already dedupes by key before persisting. |
| `workday` | `career_site_url` | For employers on Workday's recruiting platform — one of the largest ATS platforms, and this adapter works identically for any Workday tenant, not just the one it was built against. `career_site_url` is the full career site URL (e.g. `https://<tenant>.wd1.myworkdayjobs.com/<site>`); the API URL and job-detail links are both derived from it. No auth, no browser needed. Two verified API quirks are handled internally: the reported result total is only trustworthy on the first page (later pages report 0 regardless), and requesting a page past the real end silently wraps back to page 1 instead of returning empty — the adapter freezes the total from page 1 and never crosses that computed boundary. |
| `phenompeople` | `career_site_url` | For employers on Phenom People's "CareerConnect" career-site platform (e.g. `jobs.ascension.org`). Calls the platform's own internal, unauthenticated JSON search endpoint (`POST {career_site_url}/widgets`) — no cookies, CSRF token, or tenant ID needed; verified directly to work with a cookie-free request. A single call with a generously large page size returns every matching job at once, same tradeoff as `healthcaresource`. The optional `state` field maps to the platform's own "State" facet (e.g. `"Illinois"`) — worth setting explicitly, since the site's *unfiltered* search results are personalized to the requester's own IP-geolocated location rather than being a stable nationwide list. Job-detail URLs are built as `{career_site_url}/us/en/job/{job_id}` — verified the platform ignores any title-slug suffix entirely, so none is generated. |
| `findly` | `org_id`, `career_site_url` | For employers on the Findly/Radancy career-site platform (e.g. Advocate Health at `careers.aah.org`, WordPress sites running the "CWS" plugin). Calls the platform's shared, cross-tenant, unauthenticated JSON API (`jobsapi-internal.m-cloud.io/api/job`) — no cookies or site-specific auth needed, just the numeric `org_id` tenant identifier (found in the target site's `cws_opts` JS object). Paginates in fixed pages of 500 (the platform's own cap — larger `Limit` values silently return zero results) up to `max_pages` (default 20), always with an explicit `open_date`/descending sort — a live smoke test found the API's *default* ordering is unstable across pages (210 duplicate job keys, ~8%, without an explicit sort; zero with one). Each record already carries an absolute, resolvable job-detail `url`, so no slug reconstruction is needed. `career_site_url` is captured for documentation only; the adapter doesn't read it. |

`include_keywords` / `exclude_keywords` are optional on every type and
default to no additional filtering beyond what the source itself returns.
`board_token`, `url`, and the required `selectors` fields must be
non-empty — the web form rejects blanks (including whitespace-only
values) before saving.

### Secrets

The SMTP **password** stays a container env var (`SMTP_PASSWORD`) only —
never written to SQLite, never shown or editable in the UI. Every other
setting (host, port, from/to addresses) is editable at runtime through
`/settings`, persisted in the database, and survives restarts and
redeploys.

## Web UI

Every save, update, or delete action across these pages shows a brief
toast confirmation in the top-right corner. Dates are stored as UTC but
displayed in your browser's local timezone.

| Page | Purpose |
|---|---|
| `/` (Dashboard) | A **Run now** button (always triggers an immediate scrape, regardless of configured check days) at the top, plus a paginated, auto-refreshing, sortable table of past runs — start/finish time, new job count, failed source names — filterable by whether a run had failed sources. |
| `/jobs` | Every job CareerSpyder has ever found — company, search name, linked title (opens in a new tab), location, dates found/removed, age, emailed status, status (Applied/Ignored/Accepted/Rejected/Not Interested, with a per-job change history), and a summary where available. Sortable by company, title, date found, or age; filterable by company, source, location, state, zip/radius (geocoded haversine), removed/emailed status, and status. **Defaults to Active jobs only** (select "All" in the Status filter to see removed jobs too). A **Map view** link shows the same filtered jobs as pins on a map. |
| `/jobs/map` | The same filtered jobs as clustered pins (via Leaflet + Leaflet.markercluster) with a per-location job list popup, plus a fixed home-location marker. The initial view fits itself to whatever's plotted. **Defaults to Active jobs only**, same as the table. Shares the same state and zip/radius filter controls as the Jobs table. Jobs marked Not Interested are excluded by default (toggle in `/settings/preferences`); jobs whose location couldn't be resolved are excluded from the map but still filterable/visible in the table under "Other / Unresolved". |
| `/sources` | Sortable (name/type/company) and type-filterable table of configured sources with Edit/Delete actions (delete asks for confirmation via a themed dialog) and an **Add source** button. |
| `/sources/new`, `/sources/{id}/edit` | A form for one source; the `type` field determines which other fields are shown. Includes a **Test this source** button that runs the adapter once against the in-progress (unsaved) form values and previews the jobs it currently finds — useful for validating `generic_html` selectors before committing. |
| `/settings/email` | SMTP host/port/from address. The SMTP password is intentionally not present here (see [Secrets](#secrets)). |
| `/settings/data` | Clear the job dedup cache (the next run will re-report every currently known job as new and may send a large digest email), and export/import `sources.json` (import replaces the entire source list, and asks for confirmation via a themed dialog before doing so). |
| `/settings/preferences` | Light/Dark/System theme choice (client-side, `localStorage` only). Also: which days of the week to check for jobs and send a digest, whether a still-listed job is resent every digest or emailed once ever, one or more recipient addresses (server-stored, validated client- and server-side), and whether Not Interested jobs are hidden from `/jobs/map` (on by default). |

There is no authentication in v1 — this is meant for a trusted home/private
network only (see [ROADMAP.md](ROADMAP.md)).

CareerSpyder can also be installed as an app from your browser's
install/Add to Home Screen prompt, for a standalone window and app icon.

## CI & Security

Every pull request runs five GitHub Actions workflows: `lint` (Ruff), `typecheck` (mypy), `test` (pytest), `dependency-audit` (pip-audit), and `trivy-fs` (Trivy filesystem/dependency scan). A separate `docker.yml` job builds the image, runs a Trivy CRITICAL/HIGH container scan, and smoke-tests all public routes. `codeql.yml` runs CodeQL SAST on push/PR and weekly on a schedule. All Trivy and CodeQL findings are uploaded as SARIF to the repository's **Security → Code scanning** dashboard.

[Dependabot](https://docs.github.com/en/code-security/dependabot) automatically opens weekly PRs for pip, GitHub Actions, and Docker base-image updates. All Dependabot PRs go through the same CI gates before merging.

## Development

Requirements: Python 3.12+.

```bash
pip install -e ".[dev]"
pytest
```

The test suite has no live network calls and never launches a real
browser — every adapter's `fetch()` takes injectable `http_get` /
`html_renderer` parameters, and tests pass in fakes/fixtures. That also
means `pytest` runs fast and works offline.

Run the app locally without Docker:

```bash
export CAREERSPYDER_DB_PATH=./data/state.db
export CAREERSPYDER_SOURCES_PATH=./config/sources.json
export SMTP_PASSWORD=dummy   # only needed if a run finds something to email
uvicorn app.web.main:app --reload --port 8080
```

`playwright install --with-deps chromium` is required locally if you want
to exercise `linkedin`, `indeed`, or a `generic_html` source with
`render_js: true` outside the Docker image (which installs it during
build).

## Deployment

Every push to `master` that passes `docker.yml`'s build/scan/smoke-test job
publishes the image to Docker Hub as
[`jasonkryst/careerspyder`](https://hub.docker.com/r/jasonkryst/careerspyder),
tagged both `:latest` and with the version from `pyproject.toml` (bump that
version before merging a release-worthy change — otherwise the next push
just overwrites the same version tag).

Two compose files, for two different purposes:

- **`docker-compose.yml`** — builds the image from source (`build: .`).
  Used by local development and by `docker.yml`'s CI job, which needs to
  test *this* PR's code, not whatever's currently published.
- **`docker-compose.prod.yml`** — pulls `jasonkryst/careerspyder:latest`
  instead of building. Use this one for a Portainer stack on a
  Proxmox-hosted Docker host (or anywhere else Docker runs) — no build
  context, no Playwright/Chromium install on the deploy host, just a pull
  and restart:
  ```bash
  docker compose -f docker-compose.prod.yml pull
  docker compose -f docker-compose.prod.yml up -d
  ```

Both files mount the same two paths for persistent state:

- `/app/config` — `sources.json`.
- `/app/data` — `state.db` (dedup store, run history, settings).

`docker-compose.yml` bind-mounts these from `./config` and `./data`
(relative to the checkout) — fine for local dev and CI, which always run
from a fresh, known directory. `docker-compose.prod.yml` uses named Docker
volumes (`careerspyder_config`, `careerspyder_data`) instead — Docker keys
these by name rather than host path, so they survive pulls and container
recreation regardless of where or how `docker compose` is invoked, which
matters for a manually managed deploy host. Docker creates them
automatically on first `up -d`; no host directory setup needed. To inspect
or back up the files directly, e.g.:
```bash
docker run --rm -v careerspyder_data:/data -v "$PWD":/backup alpine \
  cp /data/state.db /backup/
```

Exposed port: `32600` (mapped to the container's internal port 8080).

The server itself runs as a fixed non-root user (uid/gid `1000:1000`), not
root. No manual host setup is required for this: `docker-entrypoint.sh`
runs once as root on every container start, `chown -R`s `./config` and
`./data` to `1000:1000` regardless of their prior ownership on the host,
then hands off to the app user via `setpriv` before starting uvicorn — so
mismatched host directory ownership never breaks a deploy.

## Project structure

```
app/
  models.py          Job dataclass
  db.py               SQLite: jobs / runs / settings
  config.py           sources.json schema + CRUD (pydantic models)
  filters.py           include/exclude keyword filtering
  textutils.py          HTML-to-plain-text summaries + safe-URL-scheme helper
  adapters/
    greenhouse.py, lever.py      ATS JSON API adapters
    generic_html.py               CSS-selector HTML adapter
    linkedin.py, indeed.py        best-effort Playwright adapters
    browser.py                    shared Playwright render helper
  orchestrator.py      runs all sources, dedupes, records run history
  digest.py             builds the HTML email body
  emailer.py             sends the digest via SMTP
  scheduler.py           APScheduler daily job + run-and-notify wiring
  web/
    main.py              FastAPI app + startup wiring
    routes_*.py           one router per UI section
    source_form.py        form <-> pydantic model translation
    templating.py         shared Jinja2Templates instance
    templates/*.html      server-rendered pages
tests/                  mirrors app/ layout; adapters/ and web/ subpackages
docs/superpowers/
  specs/                 design spec this was built from
  plans/                 the task-by-task implementation plan
```

## Further reading

- [docs/USAGE.md](docs/USAGE.md) — usage guide with example values for
  every source type; also available in-app at `/guide`.
- [CHANGELOG.md](CHANGELOG.md) — what's shipped so far.
- [ROADMAP.md](ROADMAP.md) — known limitations and what's planned next.
- [docs/audits/2026-08-19-app-audit.md](docs/audits/2026-08-19-app-audit.md)
  — a security/UI-UX/accessibility audit of the app; its actionable
  findings are tracked in ROADMAP.md.
- [AGENTS.md](AGENTS.md) — conventions and commands for AI coding agents
  working in this repo.
- `docs/superpowers/specs/2026-08-09-careerspyder-design.md` — the original
  design spec.
- `docs/superpowers/plans/2026-08-09-careerspyder-v1.md` — the task-by-task
  implementation plan this codebase was built from (includes documented
  deviations discovered during implementation).
