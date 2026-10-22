# AGENTS.md

Instructions for AI coding agents working in this repository. See
[README.md](README.md) for user-facing docs, [ROADMAP.md](ROADMAP.md) for
known gaps, [docs/issue-tiers.md](docs/issue-tiers.md) for the ranked list
of open GitHub issues, and [CHANGELOG.md](CHANGELOG.md) for what's shipped.

## What this is

CareerSpyder: a single-process FastAPI + APScheduler app that scrapes
configured job sources on a schedule, dedupes against PostgreSQL 17, emails
a digest of new postings, and serves a server-rendered web UI for managing
sources and settings. Invite-only multi-user: every user has their own
sources, jobs, runs, and settings. Python 3.14 (Docker image and CI;
`requires-python` is `>=3.12`), schema managed by Alembic, no frontend
build step.

Two documents in `docs/superpowers/` are the authoritative origin of this
codebase and should be read before making non-trivial changes:

- `docs/superpowers/specs/2026-08-09-careerspyder-design.md` — the design
  spec (architecture, component responsibilities, error-handling rules).
- `docs/superpowers/plans/2026-08-09-careerspyder-v1.md` — the task-by-task
  implementation plan, including documented deviations discovered during
  implementation (e.g. Dockerfile `COPY` ordering, HTML-escaping the
  digest, form-field validation). Deviations are noted inline right after
  the plan step they diverge from — read those notes, they explain *why*
  the code doesn't match the plan's literal snippet in a few spots.

## Commands

```bash
pip install -e ".[dev]"      # install package + dev deps (pytest, httpx)
pytest                        # run the full suite (e2e tests launch Chromium; see below)
pytest tests/test_db.py -v    # run one file
pytest --cov=app --cov-report=term-missing   # with coverage (CI runs this)
pytest -m integration -v      # live-site tests; skipped unless their env vars are set
ruff check app tests          # includes flake8-bandit ("S") security rules
mypy                          # type check (CI's `typecheck` job)
pip-audit                     # dependency CVE scan (CI's `dependency-audit` job)
alembic revision -m "..."     # new migration in alembic/versions/ (applied at container start)
uvicorn app.web.main:app --reload --port 8080   # run the app locally
# Local dev requires a running PostgreSQL instance and DATABASE_URL set in .env
# On Windows: install libpq (via PostgreSQL installer) for psycopg3 to connect
# Tests use pytest-postgresql: it starts a throwaway server from local
# PostgreSQL binaries, or set PGTEST_HOST/PGTEST_PORT/PGTEST_USER/
# PGTEST_PASSWORD to use an existing server (CI uses a postgres:17 service)

docker build -t careerspyder:latest .
docker compose up -d          # requires .env with POSTGRES_PASSWORD + SMTP_PASSWORD
docker compose logs -f
docker compose down
```

`playwright install --with-deps chromium` is needed locally only if you're
exercising `linkedin`, `indeed`, or a `generic_html` source with
`render_js: true` outside Docker (the image installs it at build time).

## Non-negotiable constraints

These come from the design spec's Global Constraints and are enforced by
existing tests — don't casually relax them:

- **`SMTP_PASSWORD` is a container env var only.** Never write it to
  the database, never add it to any pydantic settings model, never render it in
  a template. Every other SMTP/email setting lives in the `settings`
  table and is editable via `/settings`.
- **Tests must not make live network calls or launch a real browser.**
  Every adapter's `fetch()` signature is `fetch(source, **injectable_io)`
  — tests always pass fake `http_get`/`html_renderer` callables. If you
  add a new adapter or change an existing one, keep this shape. The only
  exceptions are `tests/web/e2e/` (real Chromium against a local server,
  see below) and `tests/integration/` (`@pytest.mark.integration`, live
  sites, auto-skipped unless their env vars are set).
- **The digest email is sent only if a run has ≥1 new job or ≥1 failed
  source.** A clean run (nothing new, nothing failed) must stay silent by
  default — `app/digest.py::build_digest` returns `None` in that case, and
  `app/scheduler.py::run_and_notify` short-circuits on `None`. The one
  exception is the opt-in `send_weekly_checkin` preference (off by
  default): when a user has turned it on, `build_digest`'s `force_checkin`
  returns a minimal "all clear" digest instead of `None`, but only on the
  weekly check-in day (Sunday, per `app/scheduler.py::_run_user`) — every
  other day, and every user who hasn't opted in, stays silent exactly as
  before.
- **Sources live in the per-user `sources` table** (config stored as
  JSONB), read fresh on every run and every `/sources` request — no
  restart needed after an edit. All reads/writes go through `app/db.py`
  (`list_sources`, `add_source`, `update_source`, `delete_source`,
  `import_sources`). `/settings/data`'s import
  (`app/web/routes_settings.py::import_settings`) validates the whole
  upload against `app/config.py::SourcesFile` *before* calling
  `db.import_sources`, so an invalid file can't partially apply; the
  import upserts by source id and gives a fresh id to any id owned by
  another user. The `sources.json` file helpers still in `app/config.py`
  (`load_sources`/`save_sources`/...) predate the PostgreSQL migration and
  aren't used by the running app — don't build new features on them.
- **Every query is scoped by `user_id`.** Jobs, sources, runs, and
  settings belong to one user; every `app/db.py` function that touches
  them takes `user_id` and filters on it (admins get read-only cross-user
  views of jobs only). `tests/test_tenant_isolation_db.py` enforces this —
  add a case there for any new per-user query.
- **User-supplied URLs go through the SSRF guard.** Any outbound request
  to a URL that came from a user (source URLs, previews, the URL checker)
  must use `app/security/ssrf_guard.py` — `safe_get`/`safe_post`/
  `safe_head`, or `install_ssrf_guard(page)` for Playwright — never a bare
  `requests.get(url)`. See SECURITY.md's "SSRF guard" section.
- **One source failing must never abort the others.** The per-source
  `try/except` in `app/orchestrator.py::run_once` (including the
  `ADAPTERS[source.type]` lookup itself) is what guarantees this — keep
  anything that can raise for one source inside that block.
- **Scraped/user-supplied text must be safe in HTML.** Job titles,
  company names, and source names can come from a scraped page or a form
  field and end up in a Jinja2 template or the digest email body. Jinja2's
  autoescape handles templates; `app/digest.py` does its own escaping
  (titles/companies/locations/source names, plus neutralizing non-`http(s)`
  URL schemes) since the digest is built as a raw HTML string, not
  rendered through Jinja2. Any new place that assembles HTML by hand needs
  the same treatment.
- **Every response carries baseline security headers.** `app/web/main.py`
  registers `SecurityHeadersMiddleware` (`app/web/security_headers.py`)
  app-wide — don't add a second `FastAPI()`/router path that bypasses it.
  Its CSP allows inline scripts/styles (the app has genuine inline
  `<script>` blocks and no nonce plumbing) — that's a known, accepted
  trade-off, not an oversight; don't silently tighten it without checking
  `base.html`/`source_form.html` still work. The e2e `page` fixture
  (`tests/web/e2e/conftest.py`) passes `bypass_csp=True` because
  Playwright's own `wait_for_function`/`expect` helpers use `eval()`
  internally — that's test-tooling only, not a CSP relaxation for users.
- **The Dockerfile's image-level user is root; the server process isn't.**
  `docker-entrypoint.sh` needs to run as root on every container start (to
  `chown` `/app/config` regardless of host ownership), then drops to uid
  1000 via `setpriv` to run `alembic upgrade head` and exec uvicorn — so
  there's deliberately no `USER` instruction in the Dockerfile. (The
  database itself is a separate `postgres` container with its own data
  volume.) `docker exec`/`docker compose exec` therefore still default
  to root; that's expected and doesn't mean the app is running as root —
  check the real process with `docker compose top`, as `docker.yml` does.

## Code conventions

- **Adapter pattern.** Every source type gets one module in
  `app/adapters/` exporting `fetch(source, **injectable_io) -> list[Job]`.
  Register it in `app/adapters/__init__.py`'s `ADAPTERS` dict, keyed by the
  `type` string used in `app/config.py`. Adding a new source type means:
  a new `SourceConfig` variant in `config.py`, a new adapter module, a
  registry entry, and a `tests/adapters/test_<type>.py` with fixture-based
  (not live) tests.
- **Config models are pydantic, discriminated by `type`.** `SourceConfig`
  in `app/config.py` is a `Union` of source models tagged by a
  `Literal["type"]` field — see `app/adapters/__init__.py`'s `ADAPTERS`
  dict for the current, authoritative list. Required-but-scrapeable-blank fields
  (`board_token`, `url`, CSS selectors) use `Field(min_length=1)` —
  browsers submit hidden fields from other source types too, so
  server-side validation is the only real guard; don't rely on the form
  JS alone.
- **Form ↔ model translation lives in `app/web/source_form.py`.**
  `source_from_form` builds and validates a `SourceConfig` from raw form
  data (raising `pydantic.ValidationError` on bad input, which the route
  catches and turns into a 400 + re-rendered form via `echo_source`).
  `echo_source` builds an unvalidated `SimpleNamespace` mirror of the
  submitted values purely so the template can redisplay what the user
  typed after a validation error — it is not a source of truth for
  anything.
- **Missing ids → `HTTPException(404)`.** `app/db.py`'s
  `update_source`/`delete_source` raise `KeyError` on a miss (including a
  source owned by another user) and routes catch it; `db.get_source`
  returns `None` instead, and routes check for it. Follow one of these
  patterns for any new lookup-by-id route.
- **Templates**: one shared `Jinja2Templates` instance in
  `app/web/templating.py`, built from `Path(__file__).parent /
  "templates"` — absolute, not CWD-relative. Import that instance; don't
  instantiate a new `Jinja2Templates(...)` per route file. If you add a
  template, remember `pyproject.toml`'s
  `[tool.setuptools.package-data]` entry (`app.web` → `templates/*.html`)
  needs to keep covering it for the file to ship in an installed package.
- **Blocking work off the event loop.** Route handlers that call an
  adapter (which does a synchronous `requests.get` or launches Playwright)
  must not be `async def` doing that work inline — either make the
  handler a plain `def` (FastAPI runs those in a threadpool
  automatically) or explicitly `await
  run_in_threadpool(...)`. See `/sources/test-preview` in
  `app/web/routes_sources.py` for the pattern.
- **Shared mutable state needs a lock.** The database connection pool is
  used from request threads, `BackgroundTasks` threads, and the
  APScheduler worker thread concurrently.
  `app/orchestrator.py::_run_lock` serializes the read-new/write-new
  sequence for runs (and the URL checker, which runs under it) — if you
  add another cross-thread read-then-write sequence, it needs the same
  treatment. In-memory state such as `app/web/ratelimit.py`'s buckets is
  per-process, which is fine only because this is a single-process app.
- **Schema changes are Alembic migrations.** Add a revision under
  `alembic/versions/`; the container applies it on start
  (`docker-entrypoint.sh`). `tests/test_migrations.py` covers upgrade
  paths.

## Testing approach

The plan this codebase was built from used TDD throughout: a failing test
first, then the implementation, then a passing run, per task. Follow the
same shape for new work — write the test against the fixture/fake before
writing the code that makes it pass. Existing tests are organized to
mirror `app/`:

```
tests/
  test_db.py, test_config.py, test_filters.py, ...   # one per app/*.py module
  adapters/test_<type>.py                              # one per adapter
  web/test_<page>.py                                    # one per route group, using FastAPI's TestClient
  web/e2e/test_<feature>.py                             # real Playwright browser against a live uvicorn server
  security/test_<guard>.py                              # SSRF / browser-guard tests (no live network)
  integration/test_<type>_live.py                       # @pytest.mark.integration, live sites, opt-in via env vars
```

`tests/web/e2e/` is the one deliberate exception to "no real browser" above:
it drives an actual Chromium instance (via `tests/web/e2e/conftest.py`'s
`live_server`/`browser`/`page` fixtures) against a real running instance of
the app, for behavior that can only be observed client-side (JS-driven
polling, keyboard nav, theme persistence). Everything outside that
directory still must not touch the network or a real browser.

Run `pytest -q`, `ruff check app tests`, and `mypy` before committing —
they're required checks on `master`. The non-e2e suite stays fast; the full
suite including `web/e2e/` takes noticeably longer because it launches
real Chromium instances.

## Git workflow

This repo uses the Superpowers `subagent-driven-development` and
`finishing-a-development-branch` skills for larger changes: an isolated
worktree/branch per unit of work, fresh implementer subagents per task,
task-level review, and a final whole-branch review before merging. If
you're an agent picking up follow-on work from the roadmap, that workflow
is a reasonable default. `master` is protected by a ruleset (required CI +
CodeQL checks, no force-push), so all changes land via PR. Bump
`pyproject.toml`'s `version` and add a CHANGELOG entry for release-worthy
changes — the Docker image is tagged from that version.
