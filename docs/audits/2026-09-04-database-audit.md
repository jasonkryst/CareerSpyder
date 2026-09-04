# CareerSpyder database audit — 2026-09-04

A focused audit of the data layer: raw SQLite via `app/db.py`, as used by
the FastAPI web app (`app/web/main.py`), the scrape orchestrator
(`app/orchestrator.py`), the scheduler (`app/scheduler.py`), the URL
checker (`app/checker.py`), and the geocoding service
(`app/geocoding/service.py`). Source configuration (`config/sources.json`,
`app/config.py`) lives outside the database entirely and is out of scope
except where it interacts with job rows (source deletion/reconciliation).

Scope, as of `v0.56.1`: `app/db.py` (630 lines, read in full), plus
`app/config.py`, `app/models.py`, `app/checker.py`,
`app/geocoding/service.py`, `app/orchestrator.py`, `app/scheduler.py`,
`app/web/main.py`, the job-key generation in every `app/adapters/*.py`
file, `pyproject.toml`'s ruff S608 exception, `CHANGELOG.md`, `README.md`,
`docker-compose.yml`, and `docker-compose.prod.yml`.

Methodology: static code review only, following every write/read path
against the `jobs`, `geocoded_locations`, `job_status_history`, `runs`,
and `settings` tables — schema definition, every `CREATE`/`ALTER`
statement, every query builder (`_JOB_SORT_COLUMNS`, `_RUN_SORT_COLUMNS`,
`_job_filters_sql`, `_run_filters_sql`), connection lifecycle, and
transaction boundaries. No live database was queried and no code was
executed or modified — this is a read-only audit, and no source files
were changed to produce it.

Severity labels follow the requested rubric: **Critical/High** = risk of
data loss or corruption; **Medium/Low** = correctness or scalability
gaps that don't lose data; **Informational** = design notes and
confirmed-safe patterns worth recording.

---

## Current schema (as it actually ends up, post-migration)

The `SCHEMA` constant (`app/db.py:8-65`) only defines each table's
*original* shape; `jobs` and `settings` have since grown columns via
`ALTER TABLE` calls run unconditionally on every `init_db()` (see
Migrations below). What follows is the effective, fully-migrated shape.

**`jobs`** — one row per deduplicated job posting, keyed by an
adapter-generated string (see Finding M1).
| column | type | notes |
|---|---|---|
| `key` | TEXT PK | dedup key, format `"<source-type>:<id-or-url-or-content>"` |
| `title`, `url`, `source_name` | TEXT NOT NULL | |
| `company`, `location`, `location_override`, `posted_date`, `source_id`, `summary`, `status` | TEXT | nullable |
| `first_seen_run_id` | INTEGER | soft reference to `runs.id`, **no FK** |
| `first_seen_at` | TEXT NOT NULL | ISO timestamp |
| `removed_at`, `emailed_at` | TEXT | nullable timestamps; `removed_at` is the soft-delete marker |
| `is_duplicate` | INTEGER NOT NULL DEFAULT 0 | boolean flag |
| `duplicate_of` | TEXT | free-text note, **not a FK to `jobs.key`** |
| FK | `location` → `geocoded_locations(location)` | added by a one-time rebuild migration (`app/db.py:111-131`) |

**`geocoded_locations`** — one row per distinct raw location string seen
across all jobs (`location TEXT PRIMARY KEY`), plus resolved
display name/city/region/country/lat/lng/status/provider/resolved_at.
Never has rows deleted (see Finding L2/M4).

**`job_status_history`** — append-only audit log of `set_job_status()`
calls: `id` PK, `job_key` (no FK, no index), `status`, `changed_at`.

**`runs`** — one row per orchestrator run (scheduled or manual):
`id` PK, `started_at`, `finished_at`, `new_job_count`, `failed_sources`
(JSON-serialized text blob), `kind`.

**`settings`** — single-row table enforced via `CHECK (id = 1)`
(`app/db.py:58`), holding SMTP config and a handful of UI preferences
(`email_days`, `resend_jobs`, `hide_not_interested_on_map`), all
`upsert`ed via `ON CONFLICT(id) DO UPDATE`. No `user_id` anywhere in the
schema — consistent with the documented single-operator trust model.

---

## Summary

| # | Finding | Severity |
|---|---|---|
| C1 | No `CREATE INDEX` anywhere in the schema | Medium |
| C2 | No WAL mode, no explicit `busy_timeout`; single shared connection across scheduler thread and web threads | Medium |
| C3 | Multi-statement scrape-run writes are not one atomic transaction | Medium |
| C4 | `job_status_history` has no FK to `jobs`; `clear_jobs()` orphans it | Medium |
| C5 | `geocoded_locations` rows are never deleted; unbounded growth, no reference cleanup | Low |
| C6 | No retention/cleanup policy for `jobs`, `runs`, or `job_status_history` | Low |
| C7 | `indeed` adapter keys jobs on a URL that still carries tracking query params | Low |
| C8 | `generic_html`/`infor` adapters dedup on content (title+location text), not a stable ID | Informational |
| C9 | Ad-hoc, three-places-at-once migration mechanism with no version table | Medium |
| C10 | `duplicate_of` and `first_seen_run_id` are unenforced soft references | Informational |
| C11 | Query-safety (S608) claim in `pyproject.toml` verified accurate | Informational |
| C12 | Backup story is documented but manual/uncoordinated with app state | Low |

No Critical or High findings — nothing found here causes silent data
loss or corruption in the paths reviewed. The two Medium-severity
concurrency/index findings (C1-C3) are the ones most likely to surface
as real incidents (`database is locked`, slow pages) if the job table or
concurrent usage grows past today's single-operator scale.

---

## Findings

### Medium

**M1 (C1). No indexes exist anywhere in the schema — every filtered/sorted query is a full table scan.**
`app/db.py:8-65` (schema), `app/db.py:328-501` (`_JOB_SORT_COLUMNS`,
`_job_filters_sql`, `list_jobs`, `count_jobs`, `list_mappable_jobs`).

There is not a single `CREATE INDEX` statement in `db.py`. The only
indexes that exist are the implicit ones SQLite creates for `PRIMARY KEY`
columns (`jobs.key`, `geocoded_locations.location`, `runs.id`,
`job_status_history.id`, `settings.id`). Every other column used in a
`WHERE` or `ORDER BY` is unindexed:

- `jobs.source_name` (equality filter, `db.py:348`) and
  `jobs.status` (equality filter, `db.py:361`)
- `jobs.removed_at` / `jobs.emailed_at` (`IS [NOT] NULL` filters, `db.py:351-357`)
- `jobs.is_duplicate` (equality filter, always applied by default — `db.py:368-371`)
- `jobs.first_seen_at`, the **default sort column** for `/jobs`
  (`_JOB_SORT_COLUMNS["first_seen_at"]`, `db.py:331`, used whenever no
  `sort` query param is supplied, `db.py:391`)
- `geocoded_locations.display_name` and `.region` (equality filters,
  `db.py:366,373`)
- `job_status_history.job_key` (lookup key for `get_job_status_history`,
  `db.py:618-630`, run once per rendered job row with detail expanded)

With every `/jobs`, `/jobs/map`, and dashboard page load doing
`LEFT JOIN geocoded_locations` plus a filtered, sorted, paginated scan of
`jobs` (`list_jobs`/`count_jobs`, `db.py:382-443`), this is fine at
today's presumably-small row counts but degrades linearly (scan + sort)
as `jobs` grows — and nothing in the codebase caps that growth (see M6).

Fix: add indexes for the actual query patterns, e.g.:
```sql
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen_at ON jobs(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_jobs_source_name ON jobs(source_name);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_removed_at ON jobs(removed_at);
CREATE INDEX IF NOT EXISTS idx_jobs_is_duplicate ON jobs(is_duplicate);
CREATE INDEX IF NOT EXISTS idx_geocoded_locations_region ON geocoded_locations(region);
CREATE INDEX IF NOT EXISTS idx_job_status_history_job_key ON job_status_history(job_key);
```
A composite `(is_duplicate, first_seen_at)` index would directly serve
the most common `/jobs` default query (duplicates excluded, sorted by
`first_seen_at DESC`).

**M2 (C2). No WAL mode, no explicit `busy_timeout`; a single connection is shared between the background scheduler thread and every web request thread.**
`app/db.py:146-158` (`init_db`), `app/web/main.py:26,36` (one `conn`
stored on `app.state` for the process lifetime), `app/scheduler.py:81`
(`BackgroundScheduler` invokes `run_and_notify(conn, ...)` — the same
connection object — from its own thread).

`init_db()` calls `sqlite3.connect(path, check_same_thread=False)` with
no `PRAGMA journal_mode=WAL` and no explicit `timeout=`/`PRAGMA
busy_timeout`. SQLite's default rollback-journal mode means a writer
holds an exclusive lock on the whole file for the duration of its
transaction, blocking all readers (and vice versa); WAL mode would let
readers proceed concurrently with a writer. `sqlite3.connect()`'s
undocumented-but-real default `timeout=5.0` does set an implicit
5-second busy handler, so short lock contention self-resolves today —
but that's incidental (no PRAGMA sets it explicitly, so a future refactor
that passes `timeout=0` or changes the connect call would silently
reintroduce hard `database is locked` failures with no test coverage to
catch it).

A scrape run (`orchestrator.run_once`, `app/orchestrator.py:32-76`) does
6+ separate write transactions against this shared connection
(`start_run`, `save_jobs`, `reconcile_jobs`, one `commit()` per row
inside `geocode_pending`'s loop, `check_job_urls`, `finish_run`) while a
person could simultaneously be loading `/jobs` on the same connection
from a FastAPI worker thread. `CHANGELOG.md:581-583` records that a
run-vs-run race (two concurrent scrapes) was previously a real,
shipped-and-fixed bug (`_run_lock` in `app/orchestrator.py:20`) — but that
lock only serializes orchestrator runs against each other, not against
concurrent web reads.

Fix: explicitly enable WAL and set a generous busy timeout in
`init_db()`:
```python
conn.execute("PRAGMA journal_mode = WAL")
conn.execute("PRAGMA busy_timeout = 10000")
```
WAL in particular removes the reader-vs-writer blocking that's the
actual risk here, rather than relying on an implicit retry window.

**M3 (C3). A scrape run's writes are five-plus independent auto-committed transactions, not one atomic unit.**
`app/orchestrator.py:32-76` calls, in order: `db.start_run` (commits),
`db.save_jobs` (commits), `db.reconcile_jobs` (commits),
`geocode_pending` (commits once per geocoded row, `app/geocoding/service.py:16-43`),
`checker.check_job_urls` (commits), `db.finish_run` (commits).

If the process is killed (OOM, container restart, `docker stop`) between
any two of these, the database is left in a partially-updated but
internally-consistent-looking state: e.g. new jobs saved and
`reconcile_jobs` already marked disappeared jobs as removed, but
`finish_run` never ran — that run row stays `finished_at IS NULL`
forever, and `new_job_count` is never recorded, which would misrender
run history and (depending on how `run_and_notify` in
`app/scheduler.py:27-70` is re-entered) could cause the digest email
step to be silently skipped on next start for that run. This isn't
corruption, but it isn't atomic either, despite being conceptually one
"run."

Fix: wrap the run's writes in a single explicit transaction
(`conn.execute("BEGIN")` / commit at the very end, rollback on
exception), or at minimum accept the current per-step commits but make
`finish_run` idempotent-recoverable (e.g. a startup sweep that closes out
any `runs` row with `finished_at IS NULL`).

**M4 (C4). `job_status_history` has no foreign key to `jobs`, and `clear_jobs()` silently orphans it.**
`app/db.py:41-46` (`job_status_history` schema — `job_key TEXT NOT NULL`,
no `FOREIGN KEY` clause, unlike `jobs.location`'s FK to
`geocoded_locations`), `app/db.py:195-197` (`clear_jobs` — `DELETE FROM
jobs` only), reachable from the UI via
`app/web/routes_settings.py:113` (`CHANGELOG.md:509` documents this as
the "reset dedup table" feature).

Clearing jobs (an intentional, user-facing reset action) leaves every
`job_status_history` row for those jobs behind with no way to reach them
again through the app (no query in `db.py` reads `job_status_history`
except by a specific set of `keys` the caller already has,
`get_job_status_history`, `db.py:618-630`). If a job with the same
computed `key` reappears in a later run (very possible — keys are
content/ID-based, not row-id based, see M5/C8), `get_job_status_history`
will resurrect its pre-reset status history and attach it to what the
UI presents as a "new" job. That's a correctness surprise, not data
loss, but it's undocumented behavior stemming from the missing FK/CASCADE.

Fix: either add `FOREIGN KEY (job_key) REFERENCES jobs(key) ON DELETE
CASCADE` (requires the same table-rebuild treatment as `_migrate_jobs_location_fk`
did for `jobs.location`, since SQLite can't `ALTER TABLE ADD
CONSTRAINT`), or have `clear_jobs()` explicitly
`DELETE FROM job_status_history` in the same transaction.

**M5 (C9). The `jobs` table's true shape is defined in three separate places that must be kept in sync by hand, with no schema-version table.**
`app/db.py:22-39` (`SCHEMA`'s original `CREATE TABLE jobs`, missing
`source_id`, `summary`, `removed_at`, `emailed_at`, `status`,
`location_override`, `is_duplicate`, `duplicate_of`), `app/db.py:80-97`
(`_NEW_JOB_COLUMNS` dict + `_migrate_jobs_table`, which `ALTER TABLE
ADD COLUMN`s those in on every single `init_db()` call, guarded only by
catching `sqlite3.OperationalError: duplicate column name`),
`app/db.py:100-131` (`_JOBS_REBUILD_COLUMNS` — a *fourth*, independent
full restatement of the same columns, used only by the one-time
`_migrate_jobs_location_fk` table-rebuild).

There is no `schema_version`/`PRAGMA user_version` check anywhere —
migrations are entirely inferred at every startup by probing
`PRAGMA table_info(jobs)` (`db.py:93`) and `PRAGMA foreign_key_list(jobs)`
(`db.py:112`) and doing whatever's missing. This works today because
every past schema change happened to be additive (new nullable columns)
or was a single one-off rebuild that's already shipped and already run
against any real database — but it means the next schema change (a
`NOT NULL` column with no default, a column rename, a type change, a new
FK) has no established pattern to follow safely, and a future
contributor adding a column to `_NEW_JOB_COLUMNS` without also updating
`_JOBS_REBUILD_COLUMNS` would silently drop that column for any database
old enough to still need the FK-rebuild migration (pre-dates the FK
addition) — `_migrate_jobs_location_fk` returns early once the FK exists
(`db.py:113-114`), so this is a narrowing but non-zero window (any
instance never having gone through that one-time migration).

Fix: introduce `PRAGMA user_version` (or a `schema_migrations` table) and
an explicit, ordered list of migration functions gated on the recorded
version, replacing the `PRAGMA table_info` probing. At minimum, collapse
the three column lists into one source of truth generated from
`_NEW_JOB_COLUMNS` plus the base schema, rather than a hand-maintained
duplicate tuple.

---

### Low

**L1 (C5). `geocoded_locations` rows are never deleted, and nothing prunes rows no `jobs` row still points at.**
`app/db.py:9-20` (schema), no `DELETE FROM geocoded_locations` exists
anywhere in `db.py`. Every distinct raw location string ever seen is kept
forever, even after every job that used it is removed or the `jobs` table
is cleared entirely (`clear_jobs`, `db.py:195-197`, which never touches
`geocoded_locations`). Harmless for correctness (it's a lookup/cache
table with a small natural cardinality — distinct city/region strings),
but it's one more table with no lifecycle story, and it means
`clear_jobs()` doesn't actually reset geocoding state or spend from
scratch even though a user invoking that reset button would reasonably
expect a clean slate.

Fix: low priority given its small expected size, but if `clear_jobs()` is
meant to be a real reset, also clear (or leave, documented as
intentional) `geocoded_locations`.

**L2 (C6). No retention/cleanup policy for `jobs`, `runs`, or `job_status_history` — all three grow forever.**
Confirmed by exhaustive search: no `retention`, `cleanup`, `vacuum`,
`purge`, or age-based `DELETE` anywhere in `app/`. `jobs` rows are only
ever soft-deleted (`removed_at` set, never actually removed —
`mark_job_removed`, `db.py:540-545`; `reconcile_jobs`, `db.py:513-537`),
`runs` accumulates one row per scheduled/manual run indefinitely, and
`job_status_history` accumulates one row per status change indefinitely.
For a daily-cron scraper running for months/years across many sources,
this is unbounded, monotonic growth with no cap — compounding the
missing-index findings above (M1) since scans get slower as these tables
grow, and inflating `data/state.db`'s on-disk size (relevant given it's a
single bind-mounted file per the compose volumes, `docker-compose.yml:19`,
`docker-compose.prod.yml:16`).

Fix: given this is a single-operator personal tool, an explicit,
documented decision either way is enough — e.g. "removed jobs older than
N days are purged" as an optional maintenance task, or an explicit README
note that growth is intentionally unbounded and operators should monitor
`data/state.db` size themselves. Today there's no policy and no
visibility into current DB size in the app.

**L3 (C7). The `indeed` adapter's dedup key includes URL query-string params that may not be stable, unlike every other adapter.**
`app/adapters/indeed.py:21,23` — `href = urljoin(source.url,
str(link_el.get("href", "")))` then `key=f"indeed:{href}"`, with no
stripping of the query string. Compare `app/adapters/linkedin.py:19,21`,
which explicitly does `href = str(link_el.get("href", "")).split("?")[0]`
before using it as the key, precisely to avoid this problem. If Indeed's
search-result markup includes any per-render tracking/session query
parameters on job links (common for job aggregators), the same physical
posting would dedup-key differently across runs, producing repeated
"new job" rows (and repeated digest emails) for postings that never
actually changed — a real job-dedup soundness gap, not a hypothetical
one, given the sibling adapter for the same category of site
(`linkedin.py`) was written defensively against exactly this.

Fix: apply the same `.split("?")[0]` (or a proper query-stripping
`urlparse`/`urlunparse`) treatment in `indeed.py` before building the key
and storing `url`.

**L4 (C12). Backup is documented but is a manual, uncoordinated file copy — no story for a copy taken mid-write.**
`README.md:313-326` documents `docker run ... cp /data/state.db /backup/`
as the backup method, and volumes are correctly bind-mounted/named so the
data does persist across redeploys (`docker-compose.yml:18-19`,
`docker-compose.prod.yml:15-17`, `careerspyder_data` volume). This is
fine as a cold-backup story (container stopped, or between runs), but
nothing in the docs warns that copying `state.db` while the app is
running and mid-write (e.g. during a scheduled scrape, or if SQLite is
ever switched to WAL per M2, mid-checkpoint) can produce a torn/
inconsistent copy — SQLite's own recommended safe-copy method is the
`.backup` command / `sqlite3_backup_api`, or `VACUUM INTO`, not a raw
file copy of a live database.

Fix: note in `README.md` that backups should be taken while the
container is stopped, or switch the documented backup command to
`sqlite3 state.db ".backup /backup/state.db"` (safe for a live DB in any
journal mode).

---

### Informational

**I1 (C8). `generic_html` and `infor` adapters dedup on scraped content, not a stable identifier — an inherent, unavoidable limitation of those source types.**
`app/adapters/generic_html.py:30` (`key=f"html:{source.company}:{title}:{href}"`)
and `app/adapters/infor.py:34`
(`key=f"infor:{source.company}:{title}:{location}"`) build keys from
scraped text rather than a job-board-native ID, because these adapter
types (generic HTML scraping, Infor career sites) don't expose one. This
means any upstream re-wording of a job title or location text will
produce a "new" job row rather than being recognized as the same
posting continuing to exist. This isn't a bug so much as a structural
limit of scraping sites with no stable per-posting ID — noted here
because it's the weakest link in an otherwise sound dedup design (every
other adapter — `greenhouse`, `lever`, `workday`, `talentbrew`,
`phenompeople`, `findly`, `healthcaresource` — keys on the source
system's own stable ID, per `app/adapters/*.py` — see the grep list
below). No fix is obvious short of not supporting these source types;
worth being aware of when investigating "why did this job get
re-reported."

**I2 (C10). `duplicate_of` and `first_seen_run_id` are intentional soft references, not enforced FKs — consistent with the rest of the schema's style, just worth naming.**
`app/db.py:33` (`first_seen_run_id INTEGER` — no FK to `runs(id)`) and
`app/db.py:88`/`app/db.py:106` (`duplicate_of TEXT` — no FK to
`jobs(key)`, and not validated as an existing key by
`set_job_duplicate`, `app/db.py:600-606`, which accepts any string). Both
are populated only by trusted, internal code paths (never raw user
input reaching the column, satisfying the S608 exception's premise —
see I3), so there's no injection risk; the gap is purely referential
integrity (a `runs` row or `jobs` row referenced this way could
disappear — though nothing currently deletes `runs` or `jobs` rows
outright — leaving a dangling reference with no `ON DELETE` behavior to
fall back on). Given the FK-rebuild precedent already in this codebase
(`_migrate_jobs_location_fk`), adding these two FKs would be a
straightforward, low-risk follow-up rather than something blocking.

**I3 (C11). The `pyproject.toml` ruff S608 exception for `app/db.py` was verified against the actual code and holds up.**
`pyproject.toml:51-55` claims "every dynamic query here interpolates only
allow-listed column names/ORDER direction ... alongside `?` placeholders
for actual data." Traced every f-string/format-based SQL construction in
`db.py`:
- `_run_filters_sql`/`_job_filters_sql` (`db.py:238-243,336-379`): every
  clause is a fixed string literal; every value goes through `params`
  and a `?` placeholder — confirmed by tracing `sort=` and `direction=`
  as genuinely user-controlled HTTP query params
  (`app/web/routes_jobs.py:40-41`) that only ever reach
  `_JOB_SORT_COLUMNS.get(sort, "jobs.first_seen_at")`
  (`db.py:391`) — an unrecognized `sort` value safely falls back to the
  default column rather than being interpolated, and `direction` is
  reduced to a hardcoded `"ASC"`/`"DESC"` literal (`db.py:392`) before
  use.
- `placeholders = ",".join("?" * len(...))` (`db.py:164,508,528,534,593,621`)
  interpolates only `?` characters, never data.
- `_add_column_if_missing`'s `table` parameter (`db.py:72-77`) is only
  ever called with the hardcoded literals `"settings"` (default) or
  `"runs"` (`db.py:154`) — never a caller-supplied value.
- `_migrate_jobs_table`'s column names come from the `_NEW_JOB_COLUMNS`
  dict's own keys (`db.py:94-96`), not external input.

`app/checker.py:34` has the same `placeholders`-only pattern under an
inline `# noqa: S608` (that file isn't covered by the `db.py`-scoped
ruff ignore) — same conclusion applies. No finding here; recorded
because the task asked for independent verification rather than trusting
the comment, and it checks out.

**I4. Connection lifecycle is a single long-lived connection for the whole process, closed cleanly at shutdown.**
`app/web/main.py:26,43` — `init_db()` is called once in the FastAPI
`lifespan`, stored on `app.state.conn`, and `conn.close()` runs on
shutdown. No connection leaks found: every function in `db.py` reuses
the one passed-in `conn` rather than opening its own, and no code path
opens a connection without a matching close. This is an unusual pattern
for a web app (typically one connection per request) but is a reasonable
and deliberate choice for SQLite specifically — the design tradeoff it
creates is exactly M2/M3 above (single connection = single point of lock
contention across the whole app), not a leak.

---

## What's already solid

- Every data-carrying value in every query goes through a `?`
  placeholder — no string-formatted values reach SQL anywhere in `db.py`
  (I3).
- `PRAGMA foreign_keys = ON` is set (`db.py:149`), and the one FK that
  exists (`jobs.location → geocoded_locations.location`) was retrofitted
  onto existing databases via a correct table-rebuild migration
  (`db.py:111-131`) rather than being skipped.
- The `settings` table's `CHECK (id = 1)` (`db.py:58`) is a clean,
  enforced way to guarantee a true singleton row.
- `ON CONFLICT(id) DO UPDATE` upserts (`save_settings`, `save_preferences`,
  `set_location_override`, `db.py:289-314,569-578`) are race-free
  single-statement patterns, better than a `SELECT`-then-`INSERT`/`UPDATE`
  dance.
- The run-vs-run race that previously caused duplicate digest emails was
  identified and fixed with `_run_lock` (`app/orchestrator.py:20`,
  `CHANGELOG.md:581-583`) — evidence the concurrency model has had real
  scrutiny before, just not extended to run-vs-web-read contention (M2).
- Backup is at least documented (`README.md:313-326`) and the Docker
  volume setup correctly persists `data/state.db` across redeploys.
