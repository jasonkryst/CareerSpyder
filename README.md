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

- **Five source types**, one adapter each:
  - `greenhouse` / `lever` — call the ATS's public JSON board API directly.
    No HTML parsing; stable and low-maintenance.
  - `generic_html` — fetch any careers page via plain HTTP (or a headless
    Chromium render when the page needs JavaScript) and extract listings
    with CSS selectors you define.
  - `linkedin` / `indeed` — best-effort, Playwright-based scraping of public
    job search result pages. Explicitly fragile (blocking, layout changes,
    CAPTCHAs); isolated so their breakage never affects the other sources.
- **Per-source keyword filters** — optional `include_keywords` /
  `exclude_keywords` on every source, matched case-insensitively against the
  job title.
- **Per-source failure isolation** — one source erroring out (site down,
  selector no longer matches, platform blocked the request) never blocks
  the others; failures are logged and surfaced in the run history and in
  the digest email.
- **Dedup that persists** — every job is keyed by the platform's own job ID
  (Greenhouse/Lever) or a stable hash of company + title + link
  (HTML/LinkedIn/Indeed) so a job is only ever reported "new" once, even
  across container restarts.
- **Email digest** — sent only when a run finds at least one new job or at
  least one source failure; a clean run with nothing to report stays
  silent.
- **Server-rendered web UI** — dashboard, run history, source management
  (add/edit/delete with a live "test this source" preview before saving),
  and settings — no SPA, no JS build step, full page reloads.
- **No database migration story to manage** — a single SQLite file holds
  dedup state, run history, and settings; it's a bind-mounted volume so it
  survives redeploys.

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
| Dedup store | `app/db.py` | SQLite: `jobs` (seen-before keys), `runs` (history), `settings` (SMTP host/port/from/to — **not** the password, see [Secrets](#secrets)). |
| Digest | `app/digest.py` | Builds an HTML email body from "new jobs this run" (grouped by company) and "sources that failed this run." Returns `None` (no email sent) when both are empty. All scraped text is HTML-escaped before landing in the email. |
| Emailer | `app/emailer.py` | Sends the digest via SMTP (STARTTLS, 30s timeout). |
| Scheduler | `app/scheduler.py` | APScheduler cron job, once daily at a configurable hour/timezone. Swallows and logs any email-send failure so a bad SMTP config can never crash the process or block future runs. |
| Web UI | `app/web/*.py` + `app/web/templates/*.html` | FastAPI routes + Jinja2 templates for `/`, `/history`, `/sources`, `/settings`. |

## Quick start (Docker)

```bash
git clone <this repo>
cd CareerSpyder
docker build -t careerspyder:latest .
```

Create a `.env` file (not committed — see `.gitignore`) with at least your
SMTP password:

```env
SMTP_PASSWORD=your-smtp-password
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=you@example.com
EMAIL_FROM=you@example.com
EMAIL_TO=you@example.com
RUN_HOUR=8
TZ=America/Chicago
```

Then:

```bash
docker compose up -d
```

Open `http://localhost:8080/`, add a source or two under **Sources**, and
click **Run now** on the dashboard to trigger an immediate scrape. The
scheduler will otherwise run once a day at `RUN_HOUR` in `TZ`.

## Configuration

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `SMTP_PASSWORD` | Yes, to send email | The SMTP account password. **Container env var only** — never written to disk, never shown or editable in the UI. See [Secrets](#secrets). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `EMAIL_FROM`, `EMAIL_TO` | No | First-boot defaults only. They seed the `settings` table the very first time the database is empty; after that, `/settings` is the source of truth and these env vars are ignored. |
| `RUN_HOUR` | No (default `8`) | Hour of day (0–23, in `TZ`) the daily scrape runs. |
| `TZ` | No (default `UTC`) | Timezone the scheduler and `RUN_HOUR` are interpreted in. |
| `CAREERSPYDER_DB_PATH` | No (default `/app/data/state.db`) | SQLite file location. |
| `CAREERSPYDER_SOURCES_PATH` | No (default `/app/config/sources.json`) | Source list location. |

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

| Page | Purpose |
|---|---|
| `/` (Dashboard) | Last run time and new-job count, plus a **Run now** button that triggers a scrape as a background task without blocking the page. |
| `/history` | Table of past runs — start/finish time, new job count, failed source names. |
| `/sources` | Table of configured sources with Edit/Delete actions and an **Add source** button. |
| `/sources/new`, `/sources/{id}/edit` | A form for one source; the `type` field determines which other fields are shown. Includes a **Test this source** button that runs the adapter once against the in-progress (unsaved) form values and previews the jobs it currently finds — useful for validating `generic_html` selectors before committing. |
| `/settings` | SMTP host/port/from/recipient address. The SMTP password is intentionally not present here (see [Secrets](#secrets)). |

There is no authentication in v1 — this is meant for a trusted home/private
network only (see [ROADMAP.md](ROADMAP.md)).

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

Both files use the same two bind-mounted volumes for persistent state:

- `./config` → `/app/config` — `sources.json`.
- `./data` → `/app/data` — `state.db` (dedup store, run history, settings).

Exposed port: `8080`.

## Project structure

```
app/
  models.py          Job dataclass
  db.py               SQLite: jobs / runs / settings
  config.py           sources.json schema + CRUD (pydantic models)
  filters.py           include/exclude keyword filtering
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

- [CHANGELOG.md](CHANGELOG.md) — what's shipped so far.
- [ROADMAP.md](ROADMAP.md) — known limitations and what's planned next.
- [AGENTS.md](AGENTS.md) — conventions and commands for AI coding agents
  working in this repo.
- `docs/superpowers/specs/2026-08-09-careerspyder-design.md` — the original
  design spec.
- `docs/superpowers/plans/2026-08-09-careerspyder-v1.md` — the task-by-task
  implementation plan this codebase was built from (includes documented
  deviations discovered during implementation).
