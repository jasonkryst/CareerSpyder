# AGENTS.md

Instructions for AI coding agents working in this repository. See
[README.md](README.md) for user-facing docs, [ROADMAP.md](ROADMAP.md) for
known gaps, and [CHANGELOG.md](CHANGELOG.md) for what's shipped.

## What this is

CareerSpyder: a single-process FastAPI + APScheduler app that scrapes
configured job sources on a schedule, dedupes against SQLite, emails a
digest of new postings, and serves a server-rendered web UI for managing
sources and settings. Python 3.12, no frontend build step.

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
pytest                        # run the full suite (no network, no browser)
pytest tests/test_db.py -v    # run one file
pytest --cov=app --cov-report=term-missing   # with coverage (CI runs this)
ruff check app tests          # includes flake8-bandit ("S") security rules
uvicorn app.web.main:app --reload --port 8080   # run the app locally

docker build -t careerspyder:latest .
docker compose up -d          # requires a .env with at least SMTP_PASSWORD
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
  SQLite, never add it to any pydantic settings model, never render it in
  a template. Every other SMTP/email setting lives in the `settings`
  table and is editable via `/settings`.
- **Tests must not make live network calls or launch a real browser.**
  Every adapter's `fetch()` signature is `fetch(source, **injectable_io)`
  — tests always pass fake `http_get`/`html_renderer` callables. If you
  add a new adapter or change an existing one, keep this shape.
- **The digest email is sent only if a run has ≥1 new job or ≥1 failed
  source.** A clean run (nothing new, nothing failed) must stay silent —
  `app/digest.py::build_digest` returns `None` in that case, and
  `app/scheduler.py::run_and_notify` short-circuits on `None`.
- **`sources.json` is the single source of truth for sources**, re-read on
  every run and every `/sources` request — no rebuild or restart needed
  after an edit. Writes go through `app/config.py::save_sources`, which
  writes atomically (temp file + `os.replace`) — don't reintroduce a
  direct `open(path, "w")`. `/settings/data`'s import feature
  (`app/config.py::import_sources_json`) is the one other write path;
  it validates against the same `SourcesFile` model before calling
  `save_sources`, so an invalid upload can't partially overwrite the file.
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
  `chown` the bind-mounted `./config`/`./data` regardless of host
  ownership), then drops to uid 1000 via `setpriv` before exec'ing
  uvicorn — so there's deliberately no `USER` instruction in the
  Dockerfile. `docker exec`/`docker compose exec` therefore still default
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
- **Routes catch `KeyError` → `HTTPException(404)`** wherever a
  `source_id` might not exist (`app/config.py`'s `get_source`/
  `update_source`/`delete_source` all raise `KeyError` on a miss). Follow
  this pattern for any new lookup-by-id route.
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
- **Shared mutable state needs a lock.** The SQLite connection and
  `sources.json` are both touched from request threads, `BackgroundTasks`
  threads, and the APScheduler worker thread concurrently.
  `app/orchestrator.py::_run_lock` serializes the read-new/write-new
  sequence for runs — if you add another cross-thread read-then-write
  sequence, it needs the same treatment (see ROADMAP.md's
  `sources.json` write-locking gap for a known example that hasn't been
  addressed yet).

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
```

`tests/web/e2e/` is the one deliberate exception to "no real browser" above:
it drives an actual Chromium instance (via `tests/web/e2e/conftest.py`'s
`live_server`/`browser`/`page` fixtures) against a real running instance of
the app, for behavior that can only be observed client-side (JS-driven
polling, keyboard nav, theme persistence). Everything outside that
directory still must not touch the network or a real browser.

Run `pytest -q` before committing. The non-e2e suite stays fast (a couple
seconds); the full suite including `web/e2e/` takes roughly a minute
because it launches real Chromium instances.

## Git workflow

This repo uses the Superpowers `subagent-driven-development` and
`finishing-a-development-branch` skills for larger changes: an isolated
worktree/branch per unit of work, fresh implementer subagents per task,
task-level review, and a final whole-branch review before merging. If
you're an agent picking up follow-on work from the roadmap, that workflow
is a reasonable default rather than committing directly to `master`.
