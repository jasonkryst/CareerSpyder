# CareerSpyder testing audit — 2026-09-04

## Scope and methodology

An audit of testing practices and coverage for CareerSpyder `v0.56.1`
(FastAPI + Jinja2 + SQLite job-scraping app). Scope: the full `tests/`
tree (`tests/*.py`, `tests/adapters/`, `tests/web/`, `tests/web/e2e/`)
against the full `app/` source tree (`app/adapters/` — 10 site adapters
plus the shared `browser.py` Playwright helper — `app/web/`,
`app/geocoding/`, and the root modules `db.py`, `orchestrator.py`,
`checker.py`, `digest.py`, `emailer.py`, `scheduler.py`, `filters.py`,
`config.py`, `textutils.py`, `models.py`).

Methodology:

1. Ran the full suite twice: `python -m pytest -q` and
   `python -m pytest --cov=app --cov-report=term-missing -q` (both
   dependencies — `pytest-cov`, `httpx` — were already installed; no
   install step was needed). Both runs executed on Windows against
   Python 3.14.6.
2. Read a representative sample of test files end-to-end across both
   `tests/adapters/` and `tests/web/` (including `tests/web/e2e/`), and
   the corresponding source files, to judge test *quality* — edge
   cases, assertion strength, mocking depth, and whether integration
   paths are genuinely exercised.
3. Read `orchestrator.py`, `scheduler.py`, `digest.py`, `emailer.py`,
   `checker.py`, and all 630 lines of `db.py` against their tests to
   find untested branches in core run/notify/query logic.
4. Read every adapter in `app/adapters/` against its test file (or lack
   thereof) to check whether fixtures reflect real-world HTML/JSON.
5. Read `.github/workflows/ci.yml` (plus `docker.yml`, `codeql.yml` for
   context) for gaps in what's required to merge.
6. Scanned fixtures/conftests for wall-clock reliance, shared state,
   hardcoded paths, and missing teardown.

This is a read-only audit — no source or test files were modified, and
no failures were fixed.

---

## Run results

**`python -m pytest -q`**: **755 passed, 0 failed, 0 skipped**, one
deprecation warning (starlette/httpx), total runtime **5:01**.

**`python -m pytest --cov=app --cov-report=term-missing -q`**: same
755 passed / 0 failed, runtime 5:01, plus **182 warnings** — all but
one are `ResourceWarning: unclosed database in <sqlite3.Connection ...>`
firing during garbage collection at essentially random points across
`test_scheduler.py`, `test_dashboard.py`, and several `tests/web/e2e/`
files (see Finding M1). No flaky tests were observed in two full runs.

**Overall coverage: 96%** (1523 statements, 58 missed).

### Lowest-covered modules

| File | Stmts | Miss | Cover | Missing lines |
|---|---:|---:|---:|---|
| `app/adapters/browser.py` | 12 | 10 | **17%** | 5-19 (the entire `render_html` body) |
| `app/adapters/infor.py` | 65 | 26 | **60%** | 16, 47-53, 57-78 |
| `app/adapters/indeed.py` | 19 | 1 | 95% | 18 |
| `app/adapters/linkedin.py` | 18 | 1 | 94% | 16 |
| `app/adapters/talentbrew.py` | 38 | 1 | 97% | 51 |
| `app/config.py` | 110 | 3 | 97% | 108, 113-114 |
| `app/textutils.py` | 25 | 2 | 92% | 33-34 |
| `app/orchestrator.py` | 52 | 3 | 94% | 68-70 |
| `app/web/routes_dashboard.py` | 34 | 2 | 94% | 52-53 |
| `app/web/routes_jobs.py` | 160 | 4 | 98% | 55-56, 136-137 |
| `app/web/routes_sources.py` | 78 | 2 | 97% | 94-95 |
| `app/web/routes_settings.py` | 116 | 1 | 99% | 129 |
| `app/db.py` | 271 | 2 | 99% | 77, 204 |

Every other module (34 of 47 files) is at **100%**. The aggregate 96%
figure is misleadingly reassuring: it is pulled up by dozens of
100%-covered small files while `browser.py` (the code every JS-rendered
adapter depends on) and half of `infor.py` are effectively unexercised.

---

## Findings

### Critical

None. No path was found where core scrape → save → notify logic can
silently corrupt data or send nothing without any test noticing;
`orchestrator.run_once`, `scheduler.run_and_notify`, and `db.py`'s
write paths are thoroughly covered (see High/Medium below for the gaps
that remain).

### High

**H1 — `app/adapters/browser.py` (`render_html`, lines 5-19) has 0
real coverage; it's the shared fetch primitive for 3 of 10 adapters.**
`render_html` is the Playwright wrapper that `indeed.py`, `linkedin.py`,
and `infor.py`'s `default_frame_fetcher` all build on (`infor.py`
inlines its own copy rather than reusing it — see L1). Coverage shows
17%, i.e. only the `import` line executes; the UA-spoofing logic (the
`HeadlessChrome` → `Chrome` string replace on line 12, added
specifically to work around a real anti-bot block per the inline
comment) and the `page.goto(..., wait_until="networkidle", timeout=30000)`
call are never exercised, mocked, or unit-tested in isolation. Every
adapter that uses it (`test_indeed.py`, `test_linkedin.py`) injects a
fake `html_renderer` and never calls the real `render_html`, so a
regression in the UA-spoofing workaround — the exact kind of fix this
function exists for — would ship with 755/755 green.
Recommendation: add `tests/adapters/test_browser.py` that either (a)
mocks `sync_playwright` to assert the UA-replace logic and page.goto
args are wired correctly (fast, no real browser), or (b) — since the
CI `test` job already runs `playwright install --with-deps chromium`
— add one real-browser smoke test that calls `render_html` against a
local static file/`data:` URL and asserts the returned HTML round-trips.
Either closes the gap; (a) is cheap and should be the minimum bar.

**H2 — `app/adapters/infor.py` pagination/polling logic (lines 47-78)
is untested; only the pure HTML-parsing half (`_parse_page`) is
covered.** `tests/adapters/test_infor.py` is good where it goes (see
also Informational note) but every test passes a `frame_fetcher` that
bypasses `default_frame_fetcher` entirely, so `_wait_for_new_first_title`
(the polling loop that decides whether a "next page" click actually
advanced) and the click/disabled-button pagination logic in
`default_frame_fetcher` (lines 56-78) have zero coverage. This is the
most fragile part of the whole adapter set — a `time.sleep(0.5)` poll
loop with a 15s deadline (line 46-53) driving real UI clicks against a
third-party site's pagination widget — and a change to the selector
(`.inforCardstackHeading`, `button.nextPage`) or the disabled-check
logic could silently break multi-page scraping for Infor sources with
no test catching it.
Recommendation: extract `_wait_for_new_first_title`'s polling
predicate into a pure function (e.g. `_title_changed(current, previous)`)
that can be unit-tested without a real `frame` object, and add a test
using a fake `frame`-like object (Mock with `.locator()` returning
canned `.count()`/`.text_content()`/`.is_disabled()` values) to exercise
`default_frame_fetcher`'s branch logic (stops on disabled button, stops
on zero cards, loops through `page_number - 1` clicks) without Playwright.

### Medium

**M1 — Tests leak `sqlite3.Connection` objects; 182 `ResourceWarning`s
fire nondeterministically during the coverage run.** `db.init_db()`
(`app/db.py:146`) opens a connection that is never closed by
production code (the app process just exits) or by most tests —
`tests/conftest.py`'s `tmp_db_path` fixture hands back a path, not a
connection, and no fixture anywhere calls `conn.close()`. Under
`--cov`, GC pressure from coverage's own instrumentation makes these
warnings surface attributed to essentially random *other* tests
(`test_run_and_notify_marks_resent_jobs_emailed_when_resend_enabled`,
`test_dashboard_table_is_grid_at_desktop_width`, etc.) — a classic
symptom of unmanaged resources: the warning's stack trace is noise, not
signal, which makes a real future leak (e.g. a connection pool
exhaustion bug) much harder to spot in CI output. It's also a a smell
in the app itself: nothing in `app/web/main.py`'s lifecycle appears to
close `request.app.state.conn` on shutdown either.
Recommendation: change `tmp_db_path`/callers to a fixture that yields
an open connection and closes it in teardown (`yield conn; conn.close()`),
audit `app/web/main.py`'s app lifespan for a matching `conn.close()` on
shutdown, and consider `-W error::ResourceWarning` scoped to `tests/`
in CI to make this a hard failure instead of scrollback noise.

**M2 — `orchestrator.py`'s URL-check failure path (lines 68-70) is
untested, unlike its sibling geocoding failure path.** `run_once`
wraps both `geocode_pending` and `checker.check_job_urls` in
`try/except Exception: logger.exception(...)` so one failing step
can't abort a run. `test_orchestrator.py` has
`test_run_once_does_not_abort_when_the_geocoding_step_raises` for the
first, but no equivalent test monkeypatches `checker.check_job_urls`
(or `orchestrator.checker`) to raise — the asymmetry means a future
refactor of the checker step (e.g. swapping the try/except for
something that re-raises, or dropping the `url_removed_count = 0`
fallback) would not be caught by the suite.
Recommendation: add
`test_run_once_does_not_abort_when_the_url_check_step_raises`,
mirroring the existing geocoding test — monkeypatch
`orchestrator.checker.check_job_urls` to raise and assert `run_once`
still returns a `RunSummary` with `url_removed_count == 0` and the run
row's `finished_at` set.

**M3 — `_run_url_check` (`app/web/routes_dashboard.py:51-53`), the
glue between the `/check-urls` endpoint and `checker.check_job_urls` +
`db.finish_run`, is monkeypatched out in both tests that touch it.**
`tests/web/test_dashboard.py::test_check_urls_post_creates_in_progress_run_row`
and `::test_check_urls_post_redirects` both do
`monkeypatch.setattr("app.web.routes_dashboard._run_url_check", lambda *a: None)`
before posting — so the actual body (call the real checker, then
`db.finish_run` with its result) is never run in the context of a real
request. `checker.check_job_urls` itself is well-unit-tested in
isolation (`tests/test_checker.py`), but the *wiring* — that
`background_tasks.add_task` is given the right `conn`/`run_id`, and
that a genuinely-raised exception inside the real (non-monkeypatched)
`_run_url_check` doesn't leave the run row stuck at `finished_at IS
NULL` forever — has no coverage.
Recommendation: add one test that does *not* monkeypatch
`_run_url_check`, instead patches `checker.check_job_urls` (or the
`http_head` it delegates to) to a fast fake, and asserts the run row
ends up finished with the right `new_job_count` after the background
task runs (FastAPI's `TestClient` runs `BackgroundTasks` synchronously
on response completion, so this doesn't need real threading).

**M4 — `app/web/routes_jobs.py:55-56` silently swallows *any*
exception from `geocoder.geocode(zip_code)` and treats it identically
to "zip not found."** The zip-radius filter does
`try: result = geocoder.geocode(zip_code) except Exception: result = None`
then sets `zip_error = True`, which the UI presumably renders as "we
couldn't find that zip." A real network/DNS failure against Nominatim
would show the user the same message as a typo'd zip code, and nothing
is logged (contrast with `orchestrator.py`'s `logger.exception` on its
similarly-broad catches). No test exercises this branch at all — the
existing zip-filter tests in `tests/web/test_jobs.py` presumably only
cover the geocoder-returns-`None`-or-a-result cases, not
geocoder-raises.
Recommendation: add a test that makes the injected/patched geocoder
raise (e.g. `requests.exceptions.ConnectionError`) when filtering by
zip, and assert the response still renders (doesn't 500) — while
separately adding a `logger.warning`/`logger.exception` call in the
`except` block so a real outage is distinguishable from a bad zip in
the logs.

**M5 — No coverage threshold is enforced anywhere.** `ci.yml`'s `test`
job runs `pytest -q --cov=app --cov-report=term-missing` with no
`--cov-fail-under`, and `pyproject.toml` has no `[tool.coverage.report]
fail_under` either. A PR that drops coverage on a touched file (e.g.
someone adding a new branch to `db.py` without a test) merges cleanly
as long as `755 passed` shows green — the coverage number is printed
but not gated. Given how close to 100% most files already sit, even a
low bar (e.g. 90%) would catch regressions early.
Recommendation: add `--cov-fail-under=90` (or similar, tuned below the
current healthy 96% floor with headroom) to the `test` job in
`ci.yml`, or the equivalent in `[tool.coverage.report]`.

### Low

**L1 — `app/adapters/infor.py` and `app/adapters/browser.py` each
implement their own Playwright browser-launch boilerplate
(`sync_playwright() as p: browser = p.chromium.launch(); try: ...
finally: browser.close()`) instead of infor.py reusing
`render_html`/a shared helper.** Not a test bug per se, but it doubles
the untested surface identified in H1/H2 — a fix to one (e.g. the UA
spoofing workaround) won't propagate to the other, and neither is
under test. Recommendation: after adding coverage per H1/H2, consider
extracting a shared "launch chromium, spoof UA, always close" helper
that both adapters call, so there is only one untested-vs-tested
surface to maintain.

**L2 — `app/textutils.py:33-34` (`safe_url_scheme`'s `except
ValueError` branch) is untested.** `urlparse` on a sufficiently
malformed string (e.g. an invalid IPv6-bracket host) raises
`ValueError`, which the function catches and neutralizes to `"#"` —
directly relevant to XSS defense in `digest.py`'s `_safe_href` and
wherever job/failed-source URLs are rendered. `tests/test_textutils.py`
tests `javascript:`/`data:`-style scheme neutralization but not a
string that makes `urlparse` itself raise.
Recommendation: add
`test_safe_url_scheme_neutralizes_a_url_that_makes_urlparse_raise`
using a known `urlparse`-crashing input (e.g.
`"http://[::1"` — unbalanced IPv6 bracket) and assert it returns `"#"`.

**L3 — `app/config.py:108,113-114` (`get_source_url`'s `talentbrew`
case and the `case _: return None` fallback) are untested.**
`get_source_url` is exercised for `greenhouse`/`lever` (via
`test_orchestrator.py`'s failed-source-URL tests) and indirectly for
several types via `test_digest.py`, but not for `talentbrew` nor for
an unrecognized `source.type` reaching the wildcard. The wildcard case
is defensive (Pydantic's discriminated union should make it
unreachable in practice), but the `talentbrew` branch is real,
reachable code with no direct test.
Recommendation: add `test_talentbrew_returns_base_url` alongside the
existing per-type tests in `test_digest.py`'s
`get_source_url`-adjacent section (or wherever the greenhouse/lever
ones live).

**L4 — Malformed-card branches in `indeed.py:18` and `linkedin.py:16`
(`continue` when a card is missing its title/link element) are
untested**, unlike the equivalent branch in `infor.py`
(`test_card_missing_posted_and_location_still_yields_a_job_with_none_fields`,
though that test covers a *different* missing-field case, not a
missing-title skip) and `talentbrew.py`/`generic_html.py` which do
test their analogous skip branches. Minor, but it's the one
un-exercised line in two otherwise 100%-adjacent files.
Recommendation: add a "card with no title/link element yields zero
jobs" case to `test_indeed.py` and `test_linkedin.py`, matching the
pattern already used elsewhere in the adapter suite.

**L5 — `app/db.py:77` (the re-raise branch in
`_add_column_if_missing` for a non-"duplicate column name"
`OperationalError`) and `app/db.py:204` (`start_run`'s defensive
`if cur.lastrowid is None: raise RuntimeError(...)`) are untested.**
Both are narrow defensive branches unlikely to trigger in SQLite in
practice; low priority, but they're the only two uncovered lines in an
otherwise fully-covered 630-line file, and `db.py` is the module this
codebase can least afford a silent regression in.
Recommendation: low priority — skip, or cover with a direct-call test
(mock `conn.execute` to raise a differently-worded `OperationalError`,
and to return a cursor with `lastrowid=None`) only if a coverage gate
(M5) forces the last few percent.

### Informational

**I1 — Adapter tests are a strong pattern: dependency injection over
mocking.** Every adapter's `fetch()` accepts an injectable seam
(`http_get=requests.get`, `html_renderer=render_html`,
`frame_fetcher=default_frame_fetcher`, `http_post=...`), and tests pass
fake implementations returning realistic HTML/JSON fixtures (e.g.
`tests/adapters/test_infor.py`'s multi-page `PAGE_1_HTML`/`PAGE_2_HTML`
constants, `tests/adapters/test_workday.py`'s `FakeResponse` wrapping a
real Workday JSON shape). This is materially better than mocking
`requests`/`BeautifulSoup` internals — it exercises the real parsing
logic end-to-end and would catch a real selector/JSON-shape regression.
The gap is narrowly in the *renderer* layer itself (H1/H2), not the
parsing logic that consumes its output.

**I2 — `tests/web/e2e/` are genuine integration tests, not
browser-flavored unit tests.** `tests/web/e2e/conftest.py`'s
`live_server` fixture boots a real `uvicorn.Server` in a background
thread against a real temp SQLite file and real `sources.json`, and
`browser`/`page` fixtures drive it with real Playwright/Chromium
(`bypass_csp=True` is used deliberately — and explained in a comment —
only so Playwright's own internal `eval()`-based helpers survive the
app's real CSP headers, not to weaken what's under test). This is the
right shape for e2e coverage; it exercises the real HTTP stack,
routing, templates, and security headers together.

**I3 — `digest.py` has thorough XSS/escaping test coverage.**
`test_digest.py` explicitly tests `javascript:`-URL neutralization for
both job URLs and failed-source URLs, HTML-escaping of scraped
title/company/location fields, and failed-source name escaping when
rendered as a link — a genuinely security-conscious test file, not
just happy-path.

**I4 — `scheduler.py`/`orchestrator.py` tests mix full-mock and
real-object styles deliberately, and it works well.**
`test_scheduler.py` has both fully-mocked unit tests (patching
`orchestrator.run_once`, `digest.build_digest`, `emailer.send_email`
individually) *and* a few real-orchestrator-plus-real-digest
"end-to-end" tests (`test_run_and_notify_end_to_end_sends_real_digest_for_a_new_job`)
that only fake the actual network boundary (adapter fetch, SMTP send).
This layered approach catches both wiring bugs (via the mocked tests)
and integration bugs between real `digest`/`orchestrator` objects (via
the end-to-end ones) — worth keeping as the house style for new
scheduler-adjacent tests.

**I5 — Suite runtime (5:01 for 755 tests) is dominated by real
Playwright browser launches in `tests/web/e2e/`** (11 e2e files, each
paying session-scoped Chromium startup once but per-test `page`
creation) and the several `time.sleep`-based polling loops used
deliberately in adapter fixtures/tests
(`orchestrator.py`'s `_run_lock` concurrency test uses
`time.sleep(0.05)`; `live_server`'s readiness poll uses
`time.sleep(0.1)` up to 5s). This isn't a correctness problem — no
flakiness was observed across two full runs — but it's slow enough
(relative to 755 tests) that CI turnaround/local iteration speed may
be worth revisiting later, e.g. by scoping e2e's `browser` fixture
more aggressively or running `tests/web/e2e/` as a separate,
parallelized CI job.

---

## CI wiring notes

`.github/workflows/ci.yml` runs four independent jobs on every PR and
push to `master`: `lint` (`ruff check app tests`), `typecheck`
(`mypy`), `test` (`pytest -q --cov=app --cov-report=term-missing`,
after `playwright install --with-deps chromium` so the e2e suite can
run), and `dependency-audit` (`pip-audit`). `docker.yml` separately
lints the Dockerfile, builds/scans/smoke-tests the image, and
`codeql.yml` covers static analysis; a Trivy filesystem scan also runs
in `ci.yml` uploading SARIF to GitHub Security. All jobs pin actions to
full commit SHAs (good supply-chain hygiene) and run on a single OS
(`ubuntu-latest`) / single Python version (`3.12`) — reasonable given
this is an internal deployment target rather than a published library,
so no version matrix gap to flag. The one concrete gap is **M5
above: no coverage threshold is enforced**, so `test` can go green
with a coverage regression as long as the (currently 0) failing-test
count stays at 0. Whether branch protection actually requires all four
jobs to pass before merge could not be verified from the repository
contents alone (that's a GitHub branch-protection-rule setting, not a
workflow file) — worth confirming separately if not already known.
