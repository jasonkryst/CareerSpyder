# CareerSpyder performance audit — 2026-09-04

A full-app performance review of the web request path, database access
layer, scraping/orchestration pipeline, geocoding, static assets, and
scheduler wiring, as of `v0.56.1`.

**Methodology.** This is static code analysis of `app/` — reading the
route handlers, `app/db.py`, `app/orchestrator.py`, `app/checker.py`,
the adapters, the geocoding module, and the scheduler — plus a review of
prior audit/design notes in `docs/` for context on decisions already
made deliberately. **It is not a live load test**; no profiler, query
planner (`EXPLAIN QUERY PLAN`), or wall-clock timing was run against a
running instance.

**Scale context — this drives every severity call below.** CareerSpyder
is a single-operator tool (per `AGENTS.md` / the 2026-08-16 sort/filter
design doc) running against a small SQLite database on a schedule
(typically once a day) plus occasional interactive browsing by one
person. There is no concurrent user load, and job counts are expected to
stay in the hundreds-to-low-thousands range, not millions. Consequently:

- **Critical/High** is reserved for things that can hang the process,
  throw user-visible errors, or corrupt/lose data during *normal
  single-user use* — not things that would only matter at scale.
- **Medium/Low** covers real inefficiencies whose actual cost at this
  scale is small (extra milliseconds, a redundant disk read) but that
  are still worth fixing opportunistically.
- **Informational** covers things that would become real problems if the
  app's scale assumptions ever changed (many users, huge job counts),
  but are non-issues today. Several such items (no `CREATE INDEX`, no
  server-side index tuning) were already explicitly deferred as
  premature optimization in `docs/superpowers/specs/2026-08-16-table-sorting-filters-design.md:301` and are not re-litigated here as new findings.

## Summary

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 2 |
| Medium | 4 |
| Low | 4 |
| Informational | 3 |

The scraping/adapter layer is in good shape: every `requests`-based
adapter sets an explicit `timeout=15`, Playwright navigations set an
explicit `timeout=30000`, and a prior review (commit `638fbfb`) already
moved the one truly risky blocking call (`/sources/test-preview`'s
adapter invocation) onto `run_in_threadpool` and added a run-serializing
lock in `app/orchestrator.py`. The real gaps are concentrated in SQLite
connection configuration (no WAL, no busy timeout, on a connection that
*is* genuinely shared across threads) and one un-throttled, un-cached
geocoding call sitting directly in an `async def` route handler.

---

## High

### H1. No `WAL` mode / no `busy_timeout` on a connection that is genuinely shared across threads — risk of user-visible "database is locked" errors during normal use

`app/db.py:146-158` (`init_db`), `app/web/main.py:26,36` (single
connection stored on `app.state.conn` for the process lifetime),
`app/scheduler.py:76-81` (APScheduler's `BackgroundScheduler` runs
`run_and_notify` on its own worker thread, against the same `conn`),
`app/web/routes_dashboard.py:56-60` (`/check-urls`'s background task
also writes via the same `conn`, on a threadpool thread, with **no**
`orchestrator._run_lock`).

`init_db` opens exactly one `sqlite3.connect(path, check_same_thread=False)`
and never sets `PRAGMA journal_mode=WAL` or `PRAGMA busy_timeout`. SQLite's
default rollback-journal mode takes an exclusive lock on the whole
database file for the duration of a write, and with the default
`busy_timeout` of `0`, a second thread that touches the file while that
lock is held gets an immediate `sqlite3.OperationalError: database is
locked` instead of waiting.

This connection is used concurrently from at least four execution
contexts in normal single-user use: (1) the FastAPI threadpool serving
synchronous routes like `/jobs`, (2) `async def` routes in
`routes_jobs.py` (status/remove/duplicate/location-override) executing
directly on the event loop thread, (3) `BackgroundTasks`-driven work
(`run_now`, `check_urls`) on threadpool worker threads, and (4)
APScheduler's dedicated background thread running the daily
`run_and_notify` job. `orchestrator.run_once` takes a `threading.Lock`
(`app/orchestrator.py:20,33`) to keep two *scrape* runs from overlapping,
but that lock is **not** held by `/check-urls`'s `_run_url_check`
(`app/web/routes_dashboard.py:51-53`), nor by any of the interactive
job-mutation routes. So the realistic failure mode isn't exotic: click
"Check URLs" (or mark a job's status) while the nightly scheduled run
happens to be mid-write, and that second write can throw immediately
instead of just waiting the extra tens of milliseconds SQLite would
normally need to finish the first one. Because `_run_url_check` runs as
a fire-and-forget background task, that failure is silent — the `runs`
row it started is left with no `finished_at`, and nothing surfaces it to
the user.

*Fix:* in `init_db`, right after `conn.execute("PRAGMA foreign_keys = ON")`,
add `conn.execute("PRAGMA journal_mode=WAL")` and
`conn.execute("PRAGMA busy_timeout=5000")` (or similar). WAL mode lets
readers and a single writer proceed concurrently instead of exclusive-
locking the whole file, and `busy_timeout` makes SQLite retry for a few
seconds instead of failing instantly on the rare cases where two writers
still collide. Also worth having `_run_url_check` acquire
`orchestrator._run_lock` so it can't interleave with a scrape run at all.

### H2. Un-cached, un-rate-limited Nominatim geocode call executed synchronously inside an `async def` route — blocks the whole event loop for up to the request's timeout

`app/web/routes_jobs.py:229-263` (`update_location_override`), calling
`app/geocoding/nominatim.py:16-54` (`NominatimGeocoder.geocode`, a
`requests.get` with `timeout=10`).

`update_location_override` is declared `async def`, so — unlike the
*synchronous* `def jobs(...)` and `def jobs_map_data(...)` handlers,
which FastAPI automatically off-loads to a worker thread — it runs
directly on the single asyncio event loop thread. Inside it, line 248
calls `geocoder.geocode(location)`, a plain synchronous `requests.get`
against `nominatim.openstreetmap.org` with a 10-second timeout and no
`run_in_threadpool` wrapper. For up to 10 seconds (longer if DNS
resolution is slow, since `timeout=10` only bounds the connect+read
phase loosely), **no other request of any kind** — including static
assets, the dashboard, or the scheduler's own use of the shared
connection from another thread waiting on it — can be serviced, because
the one event loop thread is parked in a blocking network call. This is
exactly the class of bug a prior review already fixed once, for
`/sources/test-preview` (commit `638fbfb`, now using
`run_in_threadpool`) — this call site was missed.

This call also bypasses the rate-limiting/caching discipline the rest of
the geocoding path observes (see Geocoding section below): it calls the
API directly on every request with no `min_interval_seconds` throttle
and no check of whether `location` already has a cached row in
`geocoded_locations`.

*Fix:* wrap the call in `await run_in_threadpool(geocoder.geocode, location)`
(mirroring `routes_sources.py:123`), and check `geocoded_locations` for
an existing `resolved`/`manual` row matching the input before hitting
Nominatim.

---

## Medium

### M1. Zip-code radius search geocodes on every request, with no cache — repeated Nominatim calls for the same zip

`app/web/routes_jobs.py:51-61` (`jobs`), `:132-140` (`jobs_map_data`).

Both routes call `geocoder.geocode(zip_code)` fresh on every request
that includes a `zip` query param — every pagination click, sort click,
or filter change while a zip/radius filter is active re-geocodes the
same zip code. Unlike job-location geocoding (`app/geocoding/service.py`,
which persists results in `geocoded_locations` and only geocodes rows
still `pending`), there is no cache keyed on zip code anywhere. At
single-user scale this mostly costs the user a bit of latency per click
(an outbound HTTP round trip on every navigation), but it also runs
against Nominatim's usage policy expectation that results be cached
rather than re-fetched, and — because these are synchronous `def`
routes — it's at least off the event loop, so no correctness risk, just
avoidable latency and API load.

*Fix:* cache zip→coordinates lookups (e.g., reuse `geocoded_locations`
keyed by the zip string, or a small in-process TTL cache) instead of
calling Nominatim on every request.

### M2. Sequential, one-at-a-time HTTP `HEAD` checks in `checker.check_job_urls`, no concurrency, no overall time budget

`app/checker.py:13-41`.

Every active job's URL is checked with a blocking `requests.head(...,
timeout=10)` in a plain Python `for` loop, one at a time. Each call can
take up to 10 seconds before timing out and moving on. This function
runs both as the last step of every scrape run (`app/orchestrator.py:66-70`,
under `_run_lock`) and standalone via the `/check-urls` button
(`app/web/routes_dashboard.py:56-60`). At a "small job list" scale this
is a few seconds to at most a couple of minutes if several URLs happen
to be unreachable and each burns its full 10s timeout — tolerable for a
once-daily background job, but it does hold `_run_lock` for that whole
duration, delaying a concurrently-triggered "Run now" until it finishes.

*Fix:* if job counts grow, parallelize with a small thread pool
(`concurrent.futures.ThreadPoolExecutor`, 5-10 workers) to bound total
wall-clock time to roughly `max(per-request time)` instead of `sum`. Not
urgent at current scale.

### M3. Playwright launches a brand-new Chromium process per source, sequentially, with no reuse within a run

`app/adapters/browser.py:4-19` (`render_html`), `app/adapters/infor.py:56-79`
(`default_frame_fetcher`), used by `generic_html` (when `render_js`),
`indeed`, `linkedin`, and `infor` adapters; invoked sequentially per
source in `app/orchestrator.py:40-50`.

Each Playwright-backed source fetch does a full `sync_playwright()` →
`chromium.launch()` → ... → `browser.close()` cycle, and `orchestrator.run_once`
iterates sources one at a time with no concurrency at all (not even
for the cheap `requests`-based adapters). For a handful of sources this
adds a fixed ~1-2s browser-startup tax per Playwright source on top of
page-load time, and the whole run's wall-clock time is the sum of every
source's fetch time rather than the max. For a nightly scheduled batch
job this is a non-issue; it only becomes user-visible latency when
someone clicks "Run now" and watches the dashboard.

*Fix (only worth it if the source count or Playwright-source count
grows meaningfully):* share a single `Browser` instance across
Playwright-backed sources within one run (open/close a `Page` per
source instead of a whole `Browser`), and/or fetch independent sources
concurrently (e.g. `concurrent.futures.ThreadPoolExecutor`, since these
adapters are all synchronous). Not urgent today.

### M4. Filter dropdown data (`source_names`, `locations`, `states`) and `sources.json` are re-read/re-queried on every page view instead of cached

`app/web/routes_jobs.py:85-87` (`db.list_job_source_names`,
`db.list_job_locations`, `db.list_job_states`, three `SELECT DISTINCT`
scans on every `/jobs` request), `:75` (`_secondary_source_ids` →
`app/config.py:117-122` `load_sources`, a full disk read + JSON parse +
Pydantic validation of `sources.json` on every `/jobs` request), and
similarly `app/web/routes_sources.py:30` (`load_sources` on every
`/sources` request).

None of this data changes more than a few times a day (new sources are
added rarely; new job locations/companies appear once per scrape run).
Re-deriving it on every request is wasted work, though at this scale
each piece is cheap (a small file parse, a `SELECT DISTINCT` over a
small table) — this is inefficiency, not a bottleneck.

*Fix:* cache `load_sources()`'s result keyed on the file's mtime (invalidate
on write), and/or cache the three `list_job_*` lookups for a short TTL
or invalidate them when a scrape run finishes. Low priority given the
current cost is sub-millisecond per call.

---

## Low

### L1. Static assets served with no explicit `Cache-Control`/`max-age`

`app/web/main.py:48-52` (`StaticFiles` mount), `app/web/security_headers.py`
(no cache-control header added). Starlette's `StaticFiles` sends
`Last-Modified`/`ETag` and supports conditional `304` responses, but
without an explicit `Cache-Control: max-age=...`, browsers revalidate
(a full round trip, just a cheap `304`) on every navigation rather than
serving straight from cache. Total static payload is small (`leaflet.js`
at 148KB is the largest file, third-party and already used as-is; all
first-party JS/CSS files are a few KB each), so the actual bytes-on-the-
wire cost is negligible — this is a small number of avoidable round
trips per page load, not a bandwidth problem.

*Fix:* add a `Cache-Control: public, max-age=86400` (or longer, with a
cache-busting query string / filename hash on deploy) for the `/static`
mount.

### L2. Minor blocking SQLite calls inside `async def` route handlers

`app/web/routes_jobs.py:165-226` (`update_job_status`, `remove_job`,
`update_job_duplicate` — each an `async def` calling a synchronous
`db.*` function directly). Same event-loop-blocking mechanism as H2, but
each of these is a single indexed-by-primary-key `UPDATE`/`SELECT`
against a small SQLite table — sub-millisecond in practice. Listed
separately from H2 because the *impact* is negligible at this data
scale (unlike H2's multi-second network call); the *pattern* (blocking
call in `async def`) is the same and worth cleaning up for consistency
if these handlers are touched anyway.

*Fix:* not urgent; if convenience allows, wrap in `run_in_threadpool` or
convert the handlers to plain `def` (FastAPI already threadpools those).

### L3. `update_location_override` doesn't check the geocode cache before calling Nominatim

`app/web/routes_jobs.py:247-249`. Related to H2/M1: even setting aside
the event-loop-blocking issue, this call never checks whether
`geocoded_locations` already has a `resolved`/`manual` row for the
entered location string before hitting the network. For a manual,
occasional, single-user action this is a minor inefficiency (one extra
HTTP round trip), not a real cost.

### L4. `check_job_urls` re-checks every active job's URL on every run rather than staggering/skipping recently-checked ones

`app/checker.py:13-20`. Every scrape run re-`HEAD`s *every* currently-
active job's URL (`WHERE removed_at IS NULL`), with no "last checked"
timestamp to skip URLs checked within, say, the last day. At small job
counts this is cheap network traffic, but it's the same set of requests
repeated daily forever with no decay.

*Fix:* not worth doing at current scale; would matter more if the
active job count grows into the thousands.

---

## Informational

### I1. No explicit indexes on filter/sort columns

`app/db.py:8-65` (`SCHEMA`) has no `CREATE INDEX` statements; `_JOB_SORT_COLUMNS`
(`app/db.py:328-333`) and `_job_filters_sql` (`app/db.py:336-379`) filter
and sort on `company`, `source_name`, `removed_at`, `status`,
`is_duplicate`, and join against `geocoded_locations`, all via full
table scans. This was already considered and explicitly deferred as
premature optimization in
`docs/superpowers/specs/2026-08-16-table-sorting-filters-design.md:301`
("dataset sizes here are small ... adding indexes now would be
premature optimization"). Re-flagging only as a marker for *if* job
counts ever grow past a few thousand rows: at that point, indexes on
`jobs(removed_at)`, `jobs(source_name)`, `jobs(is_duplicate)`, and
`geocoded_locations(region)` would be the first candidates.

### I2. Single shared `sqlite3.Connection` for the whole process lifetime

`app/web/main.py:26,36`. This is the *appropriate* pattern for SQLite at
this scale (opening a fresh connection per request would be pure
overhead for a local file-backed database with one real user) and is
not itself a finding — it's called out here only because it's the
reason H1 matters: a single long-lived connection shared across threads
makes WAL mode and `busy_timeout` load-bearing in a way they wouldn't be
if each request opened/closed its own connection.

### I3. Sequential adapter fetching has no per-run overall deadline

`app/orchestrator.py:40-50`. Every adapter has its own per-request
timeout (`timeout=15` for `requests`-based adapters, `timeout=30000` for
Playwright navigations), so no single source can hang the process
indefinitely — but there's no aggregate cap on total run time across all
configured sources. Today, with a handful of sources, worst-case run
time is bounded and acceptable for a nightly job. If the number of
configured sources grows substantially, worst-case run time grows
linearly with no ceiling; worth an overall watchdog/deadline at that
point, not now.
