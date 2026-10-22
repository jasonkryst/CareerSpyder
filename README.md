# CareerSpyder

CareerSpyder is a self-hosted job search assistant. It periodically checks a
list of company career pages, ATS platforms, and job boards for new postings
matching your interests, dedupes them against everything it's already seen,
and emails you a digest of what's new. You maintain the list of sources
through a small web UI — no code changes are needed to add a new source of a
type CareerSpyder already supports.

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
  - See [Field reference](#sources) below for per-type required fields.
- **Per-source keyword filters** — optional `include_keywords` /
  `exclude_keywords` on every source, matched case-insensitively against the
  job's title, company, and location.
- **Platform auto-detect** — paste a careers-page URL into the source form
  and CareerSpyder recognizes the ATS platform and pre-fills the type and
  fields; unrecognized platforms can be reported as a GitHub issue in one
  click (see `GITHUB_TOKEN`).
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
  scraped successfully without it, the source was deleted, or its posting
  URL now returns 404/410), and whether it was included in a digest email.
  Jobs can be given a status, flagged as duplicates, and given a manual
  location override.
- **Email digest** — sent only when a run finds at least one new job or at
  least one source failure; a clean run with nothing to report stays
  silent. Each job line shows its status when one is set and its source;
  the email also includes the run's search timestamp and, if
  `PUBLIC_BASE_URL` is configured, a link back to the `/jobs` page.
- **Server-rendered web UI** — dashboard, run history, source management
  (add/edit/delete with a live "test this source" preview before saving),
  and settings — no SPA and no JS build step. Small amounts of inline
  JavaScript handle progressive enhancements (status saves without a page
  reload, dashboard auto-refresh, confirm dialogs).
- **Multi-user, invite-only** — an admin invites users by link; each user
  has their own sources, jobs, run history, and settings. Self-service
  password change and email-based password reset.
- **Settings: Email, Data, and Preferences tabs** — `/settings/email` holds
  the SMTP transport config; `/settings/data` adds a job-cache clear
  (clearing it makes the next run re-report every currently known job as
  new, which can trigger a large digest email) and `settings.json`
  import/export of your sources and preferences (import adds or updates
  sources by id and never deletes existing ones; export downloads the
  current set); `/settings/preferences` holds the Light/Dark/System
  theme choice plus which days to check for jobs, whether a still-listed
  job is resent in every digest or only ever emailed once, one or
  more digest recipient addresses, and whether Not Interested jobs are
  hidden from the jobs map (on by default).
- **PostgreSQL backend with Alembic migrations** — all state (jobs, runs,
  settings, sources, users) lives in a PostgreSQL 17 database on a named
  Docker volume. Schema changes are applied automatically at startup via
  Alembic.

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
                     Dedup Store (PostgreSQL: jobs, runs, settings, sources, users)
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
| Orchestrator | `app/orchestrator.py` | Runs every configured source, applies keyword filters, dedupes across sources within a run, dedupes against PostgreSQL, and records run history. After the scrape it geocodes new locations and runs the URL checker. Serializes concurrent runs with a lock so an overlapping "Run now" and daily cron can't double-report jobs. |
| URL checker | `app/checker.py` | HEADs each active job's URL (8 workers, 60 s overall budget, through the SSRF guard) and marks jobs whose posting returns 404/410 as removed. |
| Geocoding | `app/geocoding/` | Resolves job locations to coordinates for the map and the zip/radius filter. Provider chosen by `GEOCODER_PROVIDER` (default Nominatim). |
| Dedup store | `app/db.py` | PostgreSQL: `jobs` (seen-before keys, status), `runs` (history), `settings` (SMTP host/port/from, recipient list, check days, resend flag, hide-Not-Interested-on-map flag — **not** the password, see [Secrets](#secrets)), `sources` (per-user source list, stored as JSONB), `users` (login credentials, roles), `invite_tokens` (registration links). |
| Digest | `app/digest.py` | Builds an HTML email body from "new jobs this run" (grouped by company, showing each job's status/source when set) and "sources that failed this run," plus the run's search timestamp and an optional "View all jobs" link. Returns `None` (no email sent) when there are no new jobs and no failures. All scraped text is HTML-escaped before landing in the email. |
| Emailer | `app/emailer.py` | Sends the digest via SMTP — STARTTLS, or implicit TLS on port 465 — with certificate verification and a 30 s timeout. |
| Scheduler | `app/scheduler.py` | APScheduler cron job on the `RUN_CRON` schedule in `TZ`, with a one-hour misfire grace window plus a startup check that triggers a catch-up run if today's scheduled run was missed (e.g. the container was down). Skips the scan and email entirely on days not selected in Preferences. Swallows and logs any email-send failure so a bad SMTP config can never crash the process or block future runs. |
| Web UI | `app/web/*.py` + `app/web/templates/*.html` | FastAPI routes + Jinja2 templates for `/`, `/jobs`, `/jobs/map`, `/sources`, `/settings`, `/users`, `/guide`, and the auth pages. Middleware adds security headers, CSRF origin checks, and a host allowlist; login and other sensitive endpoints are rate-limited. |

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
| `DATABASE_URL` | Yes | PostgreSQL DSN, e.g. `postgresql://user:pass@host:5432/careerspyder`. The provided `docker-compose.yml` builds this from `POSTGRES_PASSWORD`. |
| `ADMIN_USERNAME` | Yes (first boot) | Username for the initial admin account. Ignored once an admin exists in the database. |
| `ADMIN_PASSWORD` | Yes (first boot) | Password for the initial admin account (plain text; hashed with bcrypt before storage). Ignored once an admin exists. Alternatively, set `ADMIN_PASSWORD_HASH` with a pre-hashed bcrypt string. |
| `ADMIN_EMAIL` | No | Email address for the initial admin account (defaults to `{ADMIN_USERNAME}@localhost` if unset). |
| `SECRET_KEY` | Yes | A long random string used to sign session cookies. Generate with e.g. `python -c "import secrets; print(secrets.token_hex(32))"`. Changing this value invalidates all active sessions. **Required:** the app refuses to start if it is unset, a published placeholder, or shorter than 32 characters. |
| `SMTP_PASSWORD` | Yes, to send email | The SMTP account password. **Container env var only** — never written to disk, never shown or editable in the UI. See [Secrets](#secrets). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `EMAIL_FROM`, `EMAIL_TO` | No | First-boot defaults only. They seed the `settings` table the very first time the database is empty; after that, `/settings` is the source of truth and these env vars are ignored. |
| `RUN_CRON` | No (default `0 7 * * *`) | Cron expression (5 fields: `min hour dom month dow`) controlling when the daily scrape runs. `0 7 * * *` means 07:00 every day in `TZ`. See [crontab.guru](https://crontab.guru) for reference. |
| `TZ` | No (default `UTC`) | Timezone the scheduler and `RUN_CRON` are interpreted in. |
| `PUBLIC_BASE_URL` | Yes, for password-reset emails | The site's canonical public URL (e.g. `https://jobs.example.com`). Password-reset links are built from it — without it, account-recovery emails are not sent. Also used for invite links and the digest's "View all jobs" link. If it starts with `https://`, the session cookie is marked `Secure`, so sign in through that URL rather than plain `http://host:port`. |
| `ALLOWED_HOSTS` | No | Comma-separated hostnames the app will serve (e.g. `jobs.example.com,localhost`). Requests with a non-matching `Host` header get a 400. Include `localhost` so Docker's internal healthcheck keeps working. When unset, all hosts are accepted. |
| `CHROMIUM_SANDBOX` | No | Set to `1` to enable Chromium's OS-level sandbox inside the container. Requires unprivileged user namespaces on the host (see [SECURITY.md](SECURITY.md)). Leave unset (the default) when unsure. |
| `GA_MEASUREMENT_ID` | No | A GA4 Measurement ID (format `G-XXXXXXXXXX`) to enable Google Analytics page-view tracking. Without it, no `gtag.js` script is loaded and the CSP stays locked down to just this site. |
| `CARTO_API_KEY` | No | A CARTO basemaps API key, appended to `/jobs/map` tile requests as `?key=`. When unset, the map uses CARTO's free public basemaps endpoint. |
| `GEOCODER_PROVIDER` | No (default `nominatim`) | Which geocoding provider resolves job locations for the map and radius filter. |
| `TRUSTED_PROXIES` | No | Comma-separated IPs of reverse proxies whose `X-Forwarded-For` / `X-Real-IP` headers the rate limiter should trust (e.g. `172.18.0.1`). When unset, the direct peer IP is always used — correct when nothing sits in front of the app, but behind a proxy every client then shares one rate-limit bucket. |
| `GITHUB_TOKEN` | No | A fine-grained PAT with `issues: write` on this repo. When set, the source form's "Report as unsupported" button files a GitHub issue directly; otherwise it opens a pre-filled new-issue page. |

`docker-compose.yml` and `docker-compose.prod.yml` only pass through the
variables they list under `environment:` — add any optional variable above
that you set in `.env` (e.g. `CARTO_API_KEY`, `TRUSTED_PROXIES`) to your
compose file's `environment:` block too, or the container won't see it.

### Sources

Sources are managed through the `/sources` UI and stored per-user in the
PostgreSQL database. Each source has a generated `id` (used by the UI for
edit/delete links), a `type` that determines which adapter handles it and
which other fields are required, and two optional keyword filters.

Field reference:

| Type | Required fields | Notes |
|---|---|---|
| `greenhouse`, `lever` | `board_token` | The token in the ATS's board URL, e.g. `boards.greenhouse.io/<board_token>`. |
| `generic_html` | `url`, `selectors.job_card`, `selectors.title`, `selectors.link` | `selectors.location` is optional. Set `render_js: true` if the page needs JavaScript to populate listings (uses headless Chromium instead of a plain HTTP GET). |
| `linkedin`, `indeed` | `url` | Point at a job search results URL. Always uses headless Chromium — see the caveat below. |
| `infor` | `url` | For employers on Infor's Global HR / CandidateSelfService platform. `url` is the full listing page URL. `max_pages` (default 3) bounds how many pages of results are crawled per run — the board is sorted newest-first by default, so this captures the newest postings without a slow full-catalog crawl. All pages are read from a single headless-browser session (the board is loaded once, then paged in place), and the initial load is retried once if the board is slow to render. There is no per-job link on this platform (confirmed via direct investigation): the digest links to the listing page itself, not the individual posting. |
| `healthcaresource` | `site_id` | For employers on the HealthcareSource/symplr talent platform (e.g. `pm.healthcaresource.com/CS/<site_id>`). Calls a directly-callable JSON API — no browser needed. Unlike `infor`, this platform has real per-job URLs and fetches every posting in one call (no pagination limit needed). |
| `talentbrew` | `base_url` | For employers on Radancy's TalentBrew career-site platform (e.g. `jobs.nm.org`). `base_url` is just the site's origin. Calls the platform's own internal AJAX results endpoint with an explicit Title-A-Z sort — the default "Relevancy" sort was found to paginate unreliably (heavily overlapping pages), so this adapter deliberately avoids it. Paginates automatically up to the platform's own reported total page count, capped by `max_pages` (default 60) as a safety backstop. A live smoke test found a small (~0.5%) rate of duplicate job keys even with the deterministic sort, likely from ties in title text at page boundaries on a constantly-changing live board — harmless, since the orchestrator already dedupes by key before persisting. |
| `workday` | `career_site_url` | For employers on Workday's recruiting platform — one of the largest ATS platforms, and this adapter works identically for any Workday tenant, not just the one it was built against. `career_site_url` is the full career site URL (e.g. `https://<tenant>.wd1.myworkdayjobs.com/<site>`); the API URL and job-detail links (`<career_site_url>/job/...`) are both derived from it. No auth, no browser needed. Two verified API quirks are handled internally: the reported result total is only trustworthy on the first page (later pages report 0 regardless), and requesting a page past the real end silently wraps back to page 1 instead of returning empty — the adapter freezes the total from page 1 and never crosses that computed boundary. |
| `phenompeople` | `career_site_url` | For employers on Phenom People's "CareerConnect" career-site platform (e.g. `jobs.ascension.org`). Calls the platform's own internal, unauthenticated JSON search endpoint (`POST {career_site_url}/widgets`) — no cookies, CSRF token, or tenant ID needed; verified directly to work with a cookie-free request. A single call with a generously large page size returns every matching job at once, same tradeoff as `healthcaresource`. The optional `state` field maps to the platform's own "State" facet (e.g. `"Illinois"`) — worth setting explicitly, since the site's *unfiltered* search results are personalized to the requester's own IP-geolocated location rather than being a stable nationwide list. Job-detail URLs are built as `{career_site_url}/us/en/job/{job_id}` — verified the platform ignores any title-slug suffix entirely, so none is generated. |
| `findly` | `org_id`, `career_site_url` | For employers on the Findly/Radancy career-site platform (e.g. Advocate Health at `careers.aah.org`, WordPress sites running the "CWS" plugin). Calls the platform's shared, cross-tenant, unauthenticated JSON API (`jobsapi-internal.m-cloud.io/api/job`) — no cookies or site-specific auth needed, just the numeric `org_id` tenant identifier (found in the target site's `cws_opts` JS object). Paginates in fixed pages of 500 (the platform's own cap — larger `Limit` values silently return zero results) up to `max_pages` (default 20), always with an explicit `open_date`/descending sort — a live smoke test found the API's *default* ordering is unstable across pages (210 duplicate job keys, ~8%, without an explicit sort; zero with one). Each record already carries an absolute, resolvable job-detail `url`, so no slug reconstruction is needed. `career_site_url` is captured for documentation only; the adapter doesn't read it. |

`include_keywords` / `exclude_keywords` are optional on every type and
default to no additional filtering beyond what the source itself returns.
`board_token`, `url`, and the required `selectors` fields must be
non-empty — the web form rejects blanks (including whitespace-only
values) before saving.

### Secrets

The SMTP **password** stays a container env var (`SMTP_PASSWORD`) only —
never written to the database, never shown or editable in the UI. Every
other setting (host, port, from/to addresses) is editable at runtime
through `/settings`, persisted in the database, and survives restarts and
redeploys.

## Web UI

Every save, update, or delete action across these pages shows a brief
toast confirmation in the top-right corner. Dates are stored as UTC but
displayed in your browser's local timezone.

| Page | Purpose |
|---|---|
| `/` (Dashboard) | Stat cards (total jobs, new this week, sources, runs), a **Run now** button (always triggers an immediate scrape, regardless of configured check days; rate-limited), plus a paginated, auto-refreshing, sortable table of past runs — start/finish time, new job count, "N / M sources failed" with links to the failed sources — filterable by whether a run had failed sources. |
| `/jobs` | Every job CareerSpyder has ever found — company, search name, linked title (opens in a new tab), location, dates found/removed, age, emailed status, status (Applied/Ignored/Accepted/Rejected/Not Interested, with a per-job change history), and a summary where available. Sortable by company, title, date found, or age; filterable by free-text search (title + company), company, source, location, state, zip/radius (geocoded haversine), listing status (active/removed), emailed, job status, and duplicates. Changing a job's status saves in place without a page reload. **Defaults to Active jobs only** (select "All" in the **Listing status** filter to see removed jobs too). A **Map view** link shows the same filtered jobs as pins on a map. |
| `/jobs/map` | The same filtered jobs as clustered pins (via Leaflet + Leaflet.markercluster) with a per-location job list popup, plus a fixed home-location marker. The initial view fits itself to whatever's plotted. **Defaults to Active jobs only**, same as the table. Shares the same state and zip/radius filter controls as the Jobs table. Jobs marked Not Interested are excluded by default (toggle in `/settings/preferences`); jobs whose location couldn't be resolved are excluded from the map but still filterable/visible in the table under "Other / Unresolved". |
| `/sources` | Sortable (name/type/company) and type-filterable table of configured sources with a last-run health badge (ok/failed/never), Edit/Delete actions (delete asks for confirmation via a themed dialog), and an **Add source** button. |
| `/sources/new`, `/sources/{id}/edit` | A form for one source; the `type` field determines which other fields are shown. Includes a **Test this source** button that runs the adapter once against the in-progress (unsaved) form values and previews the jobs it currently finds — useful for validating `generic_html` selectors before committing. |
| `/login`, `/logout` | Login form (username + password). Authenticated sessions are signed cookies; logging out invalidates the session. Unauthenticated access to any protected route redirects here. |
| `/users` | Admin-only. Lists all users and their status; generates invite links (7-day expiry) for new users. Admins can deactivate any account except their own. |
| `/register?token=…` | Invite-only registration. Accepts the token from a `/users` invite link; creates a new account on submission. |
| `/settings/email` | SMTP host/port/from address, plus a rate-limited **Send test email** button. The SMTP password is intentionally not present here (see [Secrets](#secrets)). |
| `/settings/data` | Clear the job dedup cache (the next run will re-report every currently known job as new and may send a large digest email), and export/import a `settings.json` of your sources and preferences (max 1 MB; import adds or updates sources by id without deleting any, and asks for confirmation via a themed dialog first). |
| `/settings/account` | Change your own password (signs out your other sessions). |
| `/settings/preferences` | Light/Dark/System theme choice (client-side, `localStorage` only). Also: which days of the week to check for jobs and send a digest, whether a still-listed job is resent every digest or emailed once ever, one or more recipient addresses (server-stored, validated client- and server-side), and whether Not Interested jobs are hidden from `/jobs/map` (on by default). |

CareerSpyder can also be installed as an app from your browser's
install/Add to Home Screen prompt, for a standalone window and app icon.

## CI & Security

Every pull request runs `ci.yml`'s jobs: `lint` (Ruff), `typecheck` (mypy), `test` (pytest, against a PostgreSQL 17 service, including the Playwright e2e suite), `integration-test` (`pytest -m integration`), `dependency-audit` (pip-audit), and `trivy-fs` (Trivy filesystem/dependency scan). `docker.yml`'s `build-scan-smoketest` job builds the image, lints the Dockerfile (hadolint), runs a Trivy CRITICAL/HIGH container scan, and smoke-tests all public routes. `codeql.yml` runs CodeQL SAST on push/PR and weekly on a schedule. All Trivy and CodeQL findings are uploaded as SARIF to the repository's **Security → Code scanning** dashboard.

`master` is protected by a repository ruleset: merges require `lint`, `typecheck`, `test`, `dependency-audit`, `build-scan-smoketest`, and CodeQL to pass, high-or-higher CodeQL/Trivy alerts block the merge, and force-pushes and branch deletion are rejected.

[Dependabot](https://docs.github.com/en/code-security/dependabot) automatically opens weekly PRs for pip, GitHub Actions, and Docker base-image updates. All Dependabot PRs go through the same CI gates before merging.

## Development

Requirements: Python 3.14 (matches the Docker base image and CI — a
`.python-version` file is included for pyenv users). Python 3.12+ works but
is not tested.

```bash
pip install -e ".[dev]"
pytest
```

The unit and route tests make no live network calls and never launch a
real browser — every adapter's `fetch()` takes injectable `http_get` /
`html_renderer` parameters, and tests pass in fakes/fixtures. Two
deliberate exceptions: `tests/web/e2e/` drives a real Chromium against a
local server (run `playwright install --with-deps chromium` first), and
`tests/integration/` hits live sites but is skipped unless its env vars are
set. Tests need PostgreSQL: `pytest-postgresql` starts a throwaway server
from locally installed PostgreSQL binaries, or point it at an existing one
with `PGTEST_HOST` / `PGTEST_PORT` / `PGTEST_USER` / `PGTEST_PASSWORD`.

Run the app locally without Docker (requires a running PostgreSQL instance):

```bash
export DATABASE_URL=postgresql://careerspyder:dev@localhost:5432/careerspyder
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=changeme
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export PUBLIC_BASE_URL=http://localhost:8080
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

All persistent state lives in PostgreSQL. `docker-compose.yml` bind-mounts
`./data/postgres` for the database files — fine for local dev and CI.
`docker-compose.prod.yml` uses a named Docker volume (`careerspyder_pgdata`)
instead — Docker keys these by name rather than host path, so they survive
pulls and container recreation. Docker creates the volume automatically on
the first `up -d`; no host directory setup is needed. To back up the
database:
```bash
docker exec -t careerspyder-postgres-1 \
  pg_dump -U careerspyder careerspyder > careerspyder.sql
```

Exposed port: `32600` (mapped to the container's internal port 8080).

The server itself runs as a fixed non-root user (uid/gid `1000:1000`), not
root. No manual host setup is required for this: `docker-entrypoint.sh`
runs once as root on every container start, `chown -R`s `/app/config` to
`1000:1000`, then hands off to the app user via `setpriv` to apply any
pending Alembic migrations (`alembic upgrade head`) and start uvicorn. The
database runs in its own `postgres` container.

## Project structure

```
app/
  models.py            Job dataclass
  db.py                PostgreSQL: jobs / runs / settings / sources / users / invite_tokens
  config.py            Source pydantic models (SourceConfig union type)
  filters.py           include/exclude keyword filtering
  textutils.py         HTML-to-plain-text summaries + safe-URL-scheme helper
  adapters/
    greenhouse.py, lever.py, infor.py, healthcaresource.py,
    talentbrew.py, workday.py, phenompeople.py, findly.py   ATS/career-site adapters
    generic_html.py                CSS-selector HTML adapter
    linkedin.py, indeed.py         best-effort Playwright adapters
    browser.py                     shared Playwright render helper
  orchestrator.py      runs all sources, dedupes, records run history
  checker.py           marks jobs removed when their URL returns 404/410
  geocoding/           location -> coordinates (pluggable provider)
  platform_detector.py recognizes an ATS platform from a careers-page URL
  security/            SSRF guard for outbound HTTP and the headless browser
  digest.py            builds the HTML email body
  emailer.py           sends the digest via SMTP
  scheduler.py         APScheduler cron job, catch-up run, run-and-notify wiring
  web/
    main.py            FastAPI app + startup wiring
    auth.py            session middleware, login guard (require_user/require_admin), password hashing
    csrf_protection.py, security_headers.py, ratelimit.py   request hardening
    routes_auth.py     /login, /logout, /register, password reset
    routes_users.py    /users (admin: invite, deactivate)
    routes_*.py        one router per other UI section
    source_form.py     form <-> pydantic model translation
    templating.py      shared Jinja2Templates instance
    templates/*.html   server-rendered pages
alembic/               schema migrations (applied at container start)
tests/                 mirrors app/ layout; adapters/, web/ (+ web/e2e/), security/, integration/
docs/
  USAGE.md             usage guide (also in-app at /guide)
  issue-tiers.md       open GitHub issues ranked by impact and effort
  audits/              dated audit reports
  superpowers/specs/   design specs features were built from
  superpowers/plans/   task-by-task implementation plans
```

## Further reading

- [docs/USAGE.md](docs/USAGE.md) — usage guide with example values for
  every source type; also available in-app at `/guide`.
- [CHANGELOG.md](CHANGELOG.md) — what's shipped so far.
- [ROADMAP.md](ROADMAP.md) — known limitations not yet filed as issues.
- [docs/issue-tiers.md](docs/issue-tiers.md) — open GitHub issues ranked
  by impact and effort.
- [SECURITY.md](SECURITY.md) — security model, vulnerability reporting,
  and accepted residual risks.
- [docs/audits/](docs/audits/) — dated security, accessibility,
  performance, and feature audits; still-open findings are tracked in
  ROADMAP.md or as GitHub issues.
- [AGENTS.md](AGENTS.md) — conventions and commands for AI coding agents
  working in this repo.
- `docs/superpowers/specs/2026-08-09-careerspyder-design.md` — the original
  design spec.
- `docs/superpowers/plans/2026-08-09-careerspyder-v1.md` — the task-by-task
  implementation plan this codebase was built from (includes documented
  deviations discovered during implementation).
