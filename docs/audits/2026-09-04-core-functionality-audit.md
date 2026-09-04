# CareerSpyder core functionality audit — 2026-09-04

A functional/correctness audit of CareerSpyder's core scraping, dedup,
digest, and web-UI logic — "does the feature actually work correctly and
completely as designed," not security, accessibility, or performance
(those are covered by [docs/audits/2026-08-19-app-audit.md](2026-08-19-app-audit.md)
and its findings tracked in [ROADMAP.md](../../ROADMAP.md)).

## Scope & methodology

Static code review only (read-only; no code was modified). Reviewed
against the documented feature set in `README.md` and `docs/USAGE.md`,
with `ROADMAP.md` and recent `CHANGELOG.md` entries used to separate
already-known/tracked gaps from new findings. Areas covered:

1. `app/orchestrator.py` — run orchestration, partial-failure isolation,
   result aggregation, interaction with dedup.
2. `app/checker.py` + `app/db.py` — dedup key robustness, stale/removed
   job lifecycle.
3. `app/adapters/*.py` (all eleven adapters, plus `browser.py`) — empty
   results, pagination, malformed-input handling, field-extraction
   consistency.
4. `app/digest.py` + `app/emailer.py` + `app/scheduler.py`'s
   `run_and_notify` — digest accuracy, email-failure handling, duplicate/
   missed-email risk on crash.
5. `app/scheduler.py` + the "Run now" / "Check job URLs" web routes —
   schedule firing, manual-run safety, concurrency with the daily cron.
6. `app/web/routes_*.py` + templates — feature completeness vs.
   `docs/USAGE.md`, dead/half-finished routes, TODO/FIXME (none found via
   `grep -rn "TODO\|FIXME\|XXX" app/`).
7. `app/filters.py`, `app/web/query_params.py`, `app/web/pagination.py` —
   job list filter/sort/pagination query building.
8. `app/geocoding/*` — end-to-end wiring for the jobs map and fallback
   behavior when geocoding fails.

**Feature set as documented:** CareerSpyder is a single-process (FastAPI +
in-process APScheduler) app that scrapes eleven source types once daily
(or on-demand via "Run now"), dedupes new postings into SQLite keyed by
platform job ID / URL / a company+title+location composite (depending on
platform), reconciles which previously-seen jobs are still present
per-source ("stale" tracking), separately HEAD-checks job URLs for
404/410 to catch removals between scrapes, and emails an HTML digest of
new postings and/or failed sources. A server-rendered web UI provides a
run-history dashboard, a filterable/sortable/paginated job list with a
Leaflet map view (geocoded via Nominatim), source CRUD with a live test
preview, and settings (Email/Data/Preferences).

## Summary

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 1 |
| Medium | 5 |
| Low | 4 |
| Informational | 3 |

---

## High

### H1. "Check job URLs" runs outside the run-serialization lock and can race a concurrent scrape

`app/orchestrator.py:20,33` (`_run_lock`), `app/web/routes_dashboard.py:51-53,56-60`
(`_run_url_check` / `POST /check-urls`)

`orchestrator.run_once()` wraps its entire body — including its own
internal call to `checker.check_job_urls(conn)` — in `with _run_lock:`,
specifically so that "an overlapping 'Run now' and daily cron can't
double-report jobs" (per the module's own comment and `README.md`'s
architecture table). But the dashboard's separate **Check job URLs**
button (`POST /check-urls`) calls `checker.check_job_urls(conn)`
*directly*, from a `BackgroundTasks` callback, with no lock at all:

```python
def _run_url_check(conn, run_id: int) -> None:
    removed = checker.check_job_urls(conn)
    db.finish_run(conn, run_id, removed, [])
```

If a user clicks **Check job URLs** while a scrape (daily cron or "Run
now") is in progress — or the daily cron fires while a URL check is
still running — both code paths execute `conn.execute(...)` /
`conn.commit()` against the *same* `sqlite3.Connection` object
(`check_same_thread=False`, `app/db.py:147`) from two different
threads with no coordination. `checker.check_job_urls` itself does a
read, then (conditionally) an `UPDATE ... WHERE key IN (...)` +
`commit()`, while a concurrent `run_once()` is doing its own sequence of
inserts/updates/commits (`save_jobs`, `reconcile_jobs`, its own
`check_job_urls` call, `finish_run`). Since Python's `sqlite3.Connection`
methods are not safe to call concurrently from multiple threads on one
connection (only `check_same_thread` is relaxed — the implicit
transaction state is still per-connection, not per-thread), this can
produce `sqlite3.OperationalError` ("cannot start a transaction within a
transaction" / "database is locked"), or, more subtly, one thread's
`commit()` silently committing the other thread's in-flight partial
writes early.

**Repro:** click **Run now**, then within the run's HEAD-checking window
(large source lists make `check_job_urls`'s per-URL 10s-timeout loop take
a while) click **Check job URLs**. Both threads now write through the
shared connection unlocked.

**Fix:** have `_run_url_check` acquire `orchestrator._run_lock` (or a
shared lock exposed from `orchestrator`) before calling
`checker.check_job_urls`, the same way `run_once` already does
internally.

---

## Medium

### M1. A crash between saving new jobs and sending the digest silently and permanently drops that batch from any future email

`app/orchestrator.py:55-56` (`db.get_new_jobs` / `db.save_jobs`),
`app/scheduler.py:26-73` (`run_and_notify`)

`run_once()` commits newly-found jobs to the `jobs` table
(`db.save_jobs`, which calls `conn.commit()`) well before
`run_and_notify` gets around to calling `emailer.send_email`. There is no
separate "pending digest" queue — a job's presence in `run_and_notify`'s
`new_jobs` list for *this* run is derived entirely from
`db.get_new_jobs`'s "not already a known key" check. If the process is
killed (OOM, container restart, `docker compose up -d` redeploy) any
time after `save_jobs` commits but before `send_email` completes and
`db.mark_emailed` runs, those jobs are now permanently "known" in
`jobs`, so the *next* run's `get_new_jobs` will never see them as new
again — they will never appear in a digest, this run or any future one
(with the default `resend_jobs = 0`; see M2's report for how a user could
notice via the `/jobs?emailed=not_sent` filter, but there is no
automatic recovery). The `emailed_at` column exists precisely to make
this observable, but nothing acts on it.

**Repro:** trigger a run that finds ≥1 new job, `kill -9` the process (or
`docker restart`) between the log line for a saved run and the SMTP
send, then let the next scheduled run complete normally with no new
postings on the source. The originally-found job now sits in `/jobs`
with `emailed_at = NULL` forever and was never emailed.

**Fix:** either (a) treat "unemailed known jobs" as first-class digest
input — each run's digest should include `new_jobs` *plus* any
previously-saved jobs with `emailed_at IS NULL` (not just when
`resend_jobs` is on) — or (b) don't commit `save_jobs` until the digest
has been successfully built/queued, using a two-phase "pending"/"sent"
status on the job row instead of only `first_seen`/`emailed_at`.

### M2. Reactivated jobs (removed, then reappear) are never re-surfaced in the digest

`app/db.py:513-537` (`reconcile_jobs`), `app/orchestrator.py:55` (`db.get_new_jobs`)

`reconcile_jobs` correctly clears `removed_at` when a previously-removed
job's key reappears in a source's results (`reactivate_keys`). But
reactivation doesn't touch `first_seen_run_id`/`first_seen_at`, and more
importantly the job's key already exists in `jobs`, so
`db.get_new_jobs` (a pure "key not already known" check) will never
classify it as new again. A posting that closes and later reopens with
the same platform job ID (a very common ATS pattern — Greenhouse/Lever/
Workday all reuse requisition IDs across a close/reopen cycle) silently
reappears as Active in `/jobs` with no digest email and no
`removed_at`→`null` transition visible anywhere except by noticing the
date fields didn't change.

**Repro:** let a Greenhouse job go stale (removed from the board,
`reconcile_jobs` sets `removed_at`), then have it reappear on a later
scrape (reposted with the same `id`). The row un-removes with zero user
notification.

**Fix:** treat a `removed_at`→active transition the same as a brand-new
key for digest purposes (include it in `new_jobs`, and consider
resetting `emailed_at` to `NULL` on reactivation so it's picked up).

### M3. Indeed's dedup key includes the full URL query string; LinkedIn's does not — same-job re-reports likely on Indeed

`app/adapters/indeed.py:21-23` vs. `app/adapters/linkedin.py:19-21`

LinkedIn explicitly strips the query string before keying:
`href = str(link_el.get("href", "")).split("?")[0]` — the adapter
comment context (and general LinkedIn URL structure, which appends
volatile tracking params like `refId`/`trackingId` per page load) makes
clear this was a deliberate stability fix. Indeed's adapter has no such
stripping:

```python
href = urljoin(source.url, str(link_el.get("href", "")))
...
key=f"indeed:{href}",
```

Indeed job-card links are well known to carry `advn`, `vjs`, and similar
per-render tracking parameters that are not guaranteed stable across
scrapes of the same listing. If any such volatile parameter is present,
the same posting gets a new `key` on every run and is reported as "new"
repeatedly rather than being deduped — the opposite of the
already-fixed LinkedIn case sitting right next to it in the same
adapter family.

**Fix:** normalize the Indeed URL the same way (strip query string, or
extract Indeed's stable `jk=<id>` parameter and key on that directly,
which would be more robust than a full-URL key).

### M4. JSON-API adapters abort the entire source on a single malformed record instead of skipping it

`app/adapters/greenhouse.py:14-25`, `lever.py:14-25`,
`healthcaresource.py:23-37`, `talentbrew.py` (`link.get("data-job-id")`
unchecked), `workday.py:20-36`, `phenompeople.py:26-39`,
`findly.py:33-43`

Every JSON/API-backed adapter builds its `Job` list with direct key
access on untrusted response fields (`item["id"]`, `item["title"]`,
`src["title"]`, `posting["title"]`, `record["title"]`, `record["url"]`,
etc.) inside a `for` loop with no per-record `try`/`except`. A single
record in an otherwise-healthy response that's missing an expected field
(a draft/incomplete posting, a platform API change affecting one record
type, a `None` where a string is expected) raises `KeyError`/
`TypeError` for the *whole* adapter call. `orchestrator.run_once`'s
per-source `try/except` does correctly isolate this from other sources
(consistent with the documented "per-source failure isolation"), so it
surfaces as one failed source rather than crashing the run — but it
means the *entire* board's legitimate new postings (there could be
hundreds) are silently discarded for that run whenever one record is
malformed, and this will repeat every run until the bad record rotates
out of the feed, effectively blacking out an entire source.

Contrast with the HTML-based adapters (`generic_html.py:24`,
`infor.py:16,29`, `talentbrew.py:50` `if link is None or heading is
None: continue`), which already defensively skip a card missing expected
elements rather than failing the whole page.

**Fix:** wrap each record's `Job(...)` construction in a
`try/except (KeyError, TypeError)` that logs and `continue`s, mirroring
the HTML adapters' per-item defensiveness, so one bad record costs one
job, not the whole source.

### M5. Geocoding failures are never retried — a transient error permanently drops a job from the map

`app/geocoding/service.py:15-43`, `app/geocoding/nominatim.py:39-40`

`NominatimGeocoder.geocode` catches `requests.RequestException` (covers
timeouts, connection errors, and Nominatim's 429 rate-limit responses via
`raise_for_status()`) and returns `None` — indistinguishable from a
genuine "no such place" result. `geocode_pending` then marks that
location's `geocoded_locations.status = 'failed'` permanently
(`app/geocoding/service.py:30-34`). Only rows with `status = 'pending'`
are ever selected for (re)geocoding (`service.py:16-18`), so a
one-off network blip or a rate-limit response during a busy run
(multiple new locations in one run only get `min_interval_seconds`
spacing, no backoff/retry on 429) permanently excludes that job from
`/jobs/map` with no automatic path back — the only fix is the manual
per-job location-override flow.

**Fix:** distinguish "resolved as not found" from "request failed" in
`GeocodeResult`/return type (e.g. raise on network errors instead of
returning `None`, or a separate status), and only mark `'failed'`
(vs. leaving `'pending'` for a retry on the next run) for the former.

---

## Low

### L1. `reconcile_jobs` only tracks staleness for jobs with a `source_id`; nothing else guards against schema drift

`app/db.py:513-537`

`reconcile_jobs`'s removal query is scoped to
`WHERE removed_at IS NULL AND source_id IS NOT NULL` — by design, since
staleness needs to be attributed to a specific source. All current
adapters set `source_id=source.id` unconditionally, so this isn't
reachable today, but there's no defensive fallback (e.g. via the URL
`checker.py` HEAD-check) called out anywhere as the intended backstop for
a hypothetical `source_id`-less row; worth a one-line comment so a future
adapter change doesn't quietly reintroduce jobs nothing ever marks stale.

### L2. `duplicate_keys` exclusion in the digest path is capped at 10,000 rows

`app/scheduler.py:38-41`

```python
duplicate_keys = {row["key"] for row in db.list_jobs(conn, limit=10_000, duplicates="only")}
```

`db.list_jobs` is a paginated query; passing `limit=10_000` with no
`offset` loop means only the first 10,000 duplicate-flagged jobs are
excluded from the digest. For any installation that accumulates more
than 10,000 manually-marked duplicates over its lifetime (plausible for
a long-running instance with many `generic_html`/secondary sources), the
10,001st+ duplicate-flagged job would start appearing in digests again if
it's ever re-found as "new" or resent. Low likelihood at typical scale,
but the cap is silent (no logging, no pagination) rather than an
intentional/documented limit.

### L3. `/settings/email` raises an unhandled 500 on a missing or non-numeric `smtp_port`

`app/web/routes_settings.py:16-20,56-64`

```python
def _str_field(form: dict, key: str) -> str:
    value = form[key]     # raw KeyError if the field is absent
    ...
db.save_settings(..., int(_str_field(form, "smtp_port")), ...)   # raw ValueError if non-numeric
```

Unlike the source form (which has a *documented, tracked* version of this
same class of bug for `max_pages` — ROADMAP's finding L2), the Email
settings form has no `try`/`except` around either the field-presence
check or the `int()` conversion, so a missing field or a non-numeric
port renders FastAPI's default unhandled-exception page instead of a
validation error banner like the sibling `/settings/preferences` route
already provides for invalid emails.

**Fix:** apply the same pattern used in `save_preferences` — validate
first, re-render the form with an `error` message and 400 status on
failure — to `/settings/email`.

### L4. Talentbrew pagination silently caps at 1 page when the `data-total-pages` marker is absent

`app/adapters/talentbrew.py:41,81-83`

```python
_TOTAL_PAGES_RE = re.compile(r'data-total-pages="(\d+)"')
...
total_pages = int(match.group(1)) if match else 1
```

If the platform ever changes this markup (attribute renamed, moved to a
different element, or simply absent on a particular tenant's page), the
adapter falls back to `total_pages = 1` and stops after page one with no
error/log — a silent under-scrape rather than a visible failure. Given
the adapter's own doc comment already notes TalentBrew's pagination
behavior needed reverse-engineering per-tenant, this fallback deserves at
least a `logger.warning` so a silently truncated board is diagnosable
instead of just quietly returning fewer jobs than exist.

---

## Informational

### I1. Digest subject line omits failures when the run also found new jobs (already tracked)

Already tracked in `ROADMAP.md` under Features. Confirmed still present:
`app/digest.py:32-35` only ever reflects `len(new_jobs)` in the subject
when `new_jobs` is non-empty, even if `failed_sources` is also non-empty
for that run — no new finding, restated here only for completeness of
this audit's digest review.

### I2. SMTP port 465 / implicit TLS unsupported (already tracked)

Already tracked in `ROADMAP.md` under Reliability & operations.
`app/emailer.py:12-14` always does `starttls()`; confirmed no branch
exists for `smtplib.SMTP_SSL`. No new finding.

### I3. `mark_emailed`/`send_email` ordering means a send-succeeds-but-record-fails leaves a misleading log line

`app/scheduler.py:65-73`

```python
try:
    emailer.send_email(...)
    db.mark_emailed(conn, [j.key for j in jobs_to_send])
except Exception:
    logger.exception("Failed to send digest email for run %s", summary.run_id)
```

If `send_email` succeeds but the subsequent `db.mark_emailed` call raises
(e.g. a transient SQLite error), the `except` block logs "Failed to send
digest email" even though the email was actually delivered — misleading
for anyone debugging via logs. Functionally low-impact (per M1's
analysis, `emailed_at` doesn't gate future dedup decisions, so no
duplicate email results — it only affects the `/jobs` "emailed" filter
display), but worth splitting into two `try` blocks with distinct log
messages so the log accurately reflects what happened.

---

## What's solid

Worth noting given the depth of the review: `orchestrator.run_once`'s
per-source `try/except` genuinely does isolate one adapter's exception
from the rest of the run (verified across all eleven adapters — none
have a code path that could escape their own `fetch()` call and reach
the orchestrator's loop undconditionally uncaught, aside from the M4
malformed-record gap which is still contained per-source); the run
lock correctly serializes overlapping scheduled/manual scrapes against
each other (just not against `check-urls`, see H1); `reconcile_jobs`'
core stale-marking logic (jobs no longer found on a *successfully*
re-scraped source, or belonging to a deleted source, get `removed_at`
set) is correct and well-targeted; keyword filtering
(`app/filters.py`) is applied consistently and only to the
new-job/save/digest path, not to the raw staleness-reconciliation path,
which is the right call; pagination bounding in `workday.py` correctly
freezes the total from page 1 per its own documented API quirks; and the
geocoding pipeline's map/table fallback (unresolved locations stay
visible in the table, excluded only from the map) matches the documented
behavior exactly.
