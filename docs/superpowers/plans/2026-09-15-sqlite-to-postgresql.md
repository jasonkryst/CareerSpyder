# SQLite → PostgreSQL Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SQLite with PostgreSQL 17 using psycopg3 + Alembic, with full test coverage, CI integration, and updated Docker/docs.

**Architecture:** All `app/db.py` public function signatures stay the same (`conn` as first arg). `init_db` returns a `ConnectionPool` instead of a `Connection`; callers acquire connections from the pool. Alembic replaces the hand-rolled inline migration system.

**Tech Stack:** PostgreSQL 17, psycopg3 (`psycopg[pool]>=3.2`), Alembic 1.16+, pytest-postgresql 7+

**Spec:** `docs/superpowers/specs/2026-09-15-sqlite-to-postgresql-design.md`

## Global Constraints

- PostgreSQL version: 17 (image `postgres:17`)
- psycopg version: `>=3.2` (psycopg3, package name `psycopg`)
- Alembic version: `>=1.16`
- pytest-postgresql version: `>=7.0`
- Python version: 3.12+ (already set in pyproject.toml)
- Clean start: no data migration from SQLite; fresh PostgreSQL database
- All `db.py` public function signatures unchanged — `(conn, ...)` pattern preserved
- `DATABASE_URL` env var replaces `CAREERSPYDER_DB_PATH` (format: `postgresql://user:pass@host:5432/db`)
- Version bump: `0.65.1` → `0.66.0`
- No ORM; raw SQL throughout
- `ruff` S608 suppression on `app/db.py` stays (dynamic SQL uses allow-listed identifiers only)

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `pyproject.toml` | Modify | Add psycopg, alembic, pytest-postgresql; bump version |
| `alembic.ini` | Create | Alembic config (reads DATABASE_URL from env) |
| `alembic/env.py` | Create | Alembic env that connects via postgresql+psycopg |
| `alembic/versions/0001_initial_schema.py` | Create | Full schema + haversine function |
| `app/db.py` | Rewrite | sqlite3 → psycopg3; full dialect translation |
| `app/orchestrator.py` | Modify | `sqlite3.Connection` → `psycopg.Connection` type annotation |
| `app/checker.py` | Modify | `sqlite3.Connection` → `psycopg.Connection` type annotation |
| `app/geocoding/service.py` | Modify | `sqlite3.Connection` → `psycopg.Connection` type annotation |
| `app/scheduler.py` | Modify | `conn` → `pool`; acquire connection inside `run_and_notify` |
| `app/web/main.py` | Modify | `DATABASE_URL` env var; `app.state.pool` instead of `app.state.conn` |
| `app/web/routes_dashboard.py` | Modify | Acquire conn from pool per request; pass pool to background tasks |
| `app/web/routes_jobs.py` | Modify | Acquire conn from pool per request |
| `app/web/routes_settings.py` | Modify | Acquire conn from pool per request |
| `tests/conftest.py` | Rewrite | `tmp_db_path` → `pg_conn` (psycopg3 connection to migrated test DB) |
| `tests/web/conftest.py` | Modify | `CAREERSPYDER_DB_PATH` → `DATABASE_URL` in `client` fixture |
| `tests/test_db.py` | Modify | Remove SQLite migration tests; update assertions; add negative tests |
| `tests/test_orchestrator.py` | Modify | `tmp_db_path` → `pg_conn`; remove `db.init_db` calls |
| `tests/test_scheduler.py` | Modify | `tmp_db_path` → `pg_conn`; remove `db.init_db` calls |
| `tests/test_geocoding.py` | Modify | `tmp_db_path` → `pg_conn`; remove `db.init_db` calls |
| `tests/test_checker.py` | Modify | `tmp_db_path` → `pg_conn`; remove `db.init_db` calls |
| `.github/workflows/ci.yml` | Modify | Add PostgreSQL 17 service to `test` job |
| `docker-compose.yml` | Modify | Add `postgres:17` service; `DATABASE_URL` env var |
| `docker-compose.prod.yml` | Modify | Same; `careerspyder_pgdata` named volume |
| `docker-entrypoint.sh` | Modify | Add `alembic upgrade head` before uvicorn |
| `.env.example` | Modify | Replace `CAREERSPYDER_DB_PATH` with `DATABASE_URL` + `POSTGRES_PASSWORD` |
| `CHANGELOG.md` | Modify | Add 0.66.0 entry |
| `README.md` | Modify | Update setup instructions |
| `AGENTS.md` | Modify | Update DB layer description |

---

### Task 1: Dependencies & Version Bump

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `psycopg`, `psycopg_pool`, `alembic`, `pytest_postgresql` available to import in subsequent tasks

- [ ] **Step 1: Edit `pyproject.toml`**

  Under `[project]` `dependencies`, add after `pydantic`:
  ```toml
  "psycopg[pool]>=3.2",
  "alembic>=1.16",
  ```

  Under `[project.optional-dependencies]` `dev`, add:
  ```toml
  "pytest-postgresql>=7.0",
  ```

  Change version line:
  ```toml
  version = "0.66.0"
  ```

- [ ] **Step 2: Install deps to verify no conflicts**

  ```bash
  pip install -e ".[dev]"
  ```
  Expected: installs psycopg, psycopg-pool, alembic, pytest-postgresql with no errors.

- [ ] **Step 3: Commit**

  ```bash
  git add pyproject.toml
  git commit -m "chore: bump to 0.66.0; add psycopg, alembic, pytest-postgresql deps"
  ```

---

### Task 2: Alembic Scaffolding

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/.gitkeep`

**Interfaces:**
- Produces: `alembic upgrade head` command that reads `DATABASE_URL` from environment

- [ ] **Step 1: Create `alembic.ini`**

  ```ini
  [alembic]
  script_location = alembic
  # URL is set dynamically in env.py from DATABASE_URL environment variable
  sqlalchemy.url =

  [loggers]
  keys = root,sqlalchemy,alembic

  [handlers]
  keys = console

  [formatters]
  keys = generic

  [logger_root]
  level = WARN
  handlers = console
  qualname =

  [logger_sqlalchemy]
  level = WARN
  handlers =
  qualname = sqlalchemy.engine

  [logger_alembic]
  level = INFO
  handlers =
  qualname = alembic

  [handler_console]
  class = StreamHandler
  args = (sys.stderr,)
  level = NOTSET
  formatter = generic

  [formatter_generic]
  format = %(levelname)-5.5s [%(name)s] %(message)s
  datefmt = %H:%M:%S
  ```

- [ ] **Step 2: Create `alembic/env.py`**

  ```python
  import os
  from logging.config import fileConfig

  from alembic import context
  from sqlalchemy import create_engine, pool

  config = context.config
  if config.config_file_name is not None:
      fileConfig(config.config_file_name)

  target_metadata = None


  def _get_url() -> str:
      url = os.environ["DATABASE_URL"]
      # SQLAlchemy requires the psycopg3 dialect prefix
      return url.replace("postgresql://", "postgresql+psycopg://", 1)


  def run_migrations_online() -> None:
      engine = create_engine(_get_url(), poolclass=pool.NullPool)
      with engine.connect() as connection:
          context.configure(connection=connection, target_metadata=target_metadata)
          with context.begin_transaction():
              context.run_migrations()


  def run_migrations_offline() -> None:
      context.configure(url=_get_url(), target_metadata=target_metadata, literal_binds=True)
      with context.begin_transaction():
          context.run_migrations()


  if context.is_offline_mode():
      run_migrations_offline()
  else:
      run_migrations_online()
  ```

- [ ] **Step 3: Create `alembic/versions/` directory marker**

  ```bash
  mkdir -p alembic/versions
  touch alembic/versions/.gitkeep
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add alembic.ini alembic/
  git commit -m "feat: add Alembic scaffolding (alembic.ini + env.py)"
  ```

---

### Task 3: Initial Schema Migration

**Files:**
- Create: `alembic/versions/0001_initial_schema.py`

**Interfaces:**
- Produces: running `alembic upgrade head` creates all 5 tables and the `haversine_miles` function in PostgreSQL

- [ ] **Step 1: Create `alembic/versions/0001_initial_schema.py`**

  ```python
  """initial schema

  Revision ID: 0001
  Revises:
  Create Date: 2026-09-15
  """
  from alembic import op

  revision = "0001"
  down_revision = None
  branch_labels = None
  depends_on = None

  _HAVERSINE = """
  CREATE OR REPLACE FUNCTION haversine_miles(
      lat1 float8, lon1 float8, lat2 float8, lon2 float8
  ) RETURNS float8 LANGUAGE sql IMMUTABLE AS $$
      SELECT CASE
          WHEN lat1 IS NULL OR lon1 IS NULL OR lat2 IS NULL OR lon2 IS NULL THEN NULL
          ELSE 3958.8 * 2 * ATAN2(
              SQRT(
                  SIN(RADIANS((lat2 - lat1) / 2))^2 +
                  COS(RADIANS(lat1)) * COS(RADIANS(lat2)) *
                  SIN(RADIANS((lon2 - lon1) / 2))^2
              ),
              SQRT(1 - (
                  SIN(RADIANS((lat2 - lat1) / 2))^2 +
                  COS(RADIANS(lat1)) * COS(RADIANS(lat2)) *
                  SIN(RADIANS((lon2 - lon1) / 2))^2
              ))
          )
      END
  $$;
  """


  def upgrade() -> None:
      op.execute(_HAVERSINE)

      op.execute("""
          CREATE TABLE geocoded_locations (
              location TEXT PRIMARY KEY,
              display_name TEXT,
              city TEXT,
              region TEXT,
              country TEXT,
              lat FLOAT8,
              lng FLOAT8,
              status TEXT NOT NULL,
              provider TEXT,
              resolved_at TEXT
          )
      """)

      op.execute("""
          CREATE TABLE jobs (
              key TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              company TEXT,
              location TEXT REFERENCES geocoded_locations(location),
              location_override TEXT,
              url TEXT NOT NULL,
              posted_date TEXT,
              source_name TEXT NOT NULL,
              source_id TEXT,
              summary TEXT,
              first_seen_run_id BIGINT,
              first_seen_at TEXT NOT NULL,
              removed_at TEXT,
              emailed_at TEXT,
              status TEXT,
              is_duplicate BOOLEAN NOT NULL DEFAULT FALSE,
              duplicate_of TEXT
          )
      """)

      op.execute("""
          CREATE TABLE job_status_history (
              id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
              job_key TEXT NOT NULL,
              status TEXT,
              changed_at TEXT NOT NULL
          )
      """)

      op.execute("""
          CREATE TABLE runs (
              id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              new_job_count BIGINT NOT NULL DEFAULT 0,
              failed_sources TEXT NOT NULL DEFAULT '[]',
              kind TEXT NOT NULL DEFAULT 'scrape'
          )
      """)

      op.execute("""
          CREATE TABLE settings (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              smtp_host TEXT,
              smtp_port INTEGER,
              smtp_user TEXT,
              email_from TEXT,
              email_to TEXT,
              email_days TEXT NOT NULL DEFAULT 'mon,tue,wed,thu,fri,sat,sun',
              resend_jobs BOOLEAN NOT NULL DEFAULT FALSE,
              hide_not_interested_on_map BOOLEAN NOT NULL DEFAULT TRUE,
              digest_max_per_company INTEGER NOT NULL DEFAULT 0,
              digest_exclude_statuses TEXT NOT NULL DEFAULT ''
          )
      """)


  def downgrade() -> None:
      op.execute("DROP TABLE IF EXISTS settings")
      op.execute("DROP TABLE IF EXISTS runs")
      op.execute("DROP TABLE IF EXISTS job_status_history")
      op.execute("DROP TABLE IF EXISTS jobs")
      op.execute("DROP TABLE IF EXISTS geocoded_locations")
      op.execute("DROP FUNCTION IF EXISTS haversine_miles(float8, float8, float8, float8)")
  ```

- [ ] **Step 2: Start a local PostgreSQL 17 instance and verify the migration applies**

  ```bash
  docker run --rm -d --name pg-test \
    -e POSTGRES_DB=careerspyder -e POSTGRES_USER=careerspyder -e POSTGRES_PASSWORD=dev \
    -p 5432:5432 postgres:17
  ```

  Wait ~5 seconds for it to start, then:

  ```bash
  DATABASE_URL=postgresql://careerspyder:dev@localhost:5432/careerspyder alembic upgrade head
  ```

  Expected: `Running upgrade  -> 0001, initial schema`

- [ ] **Step 3: Verify downgrade works**

  ```bash
  DATABASE_URL=postgresql://careerspyder:dev@localhost:5432/careerspyder alembic downgrade base
  ```

  Expected: no error; all tables dropped.

- [ ] **Step 4: Apply the migration again (clean state for subsequent tasks)**

  ```bash
  DATABASE_URL=postgresql://careerspyder:dev@localhost:5432/careerspyder alembic upgrade head
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add alembic/versions/0001_initial_schema.py alembic/versions/.gitkeep
  git commit -m "feat: add initial PostgreSQL schema migration (#138)"
  ```

---

### Task 4: Rewrite `app/db.py`

**Files:**
- Rewrite: `app/db.py`

**Interfaces:**
- Consumes: `psycopg.Connection` (from `psycopg_pool.ConnectionPool.connection()`)
- Produces:
  - `init_db(dsn: str) -> ConnectionPool`
  - All existing public functions unchanged in signature, now typed `psycopg.Connection`
  - `_haversine_miles` removed (lives in PostgreSQL now)

`★ Insight ─────────────────────────────────────`
psycopg3's `conn.execute()` returns a cursor just like sqlite3 — the call-site changes are minimal. The three most non-obvious changes: (1) `RETURNING id` replaces `lastrowid`, (2) `ILIKE` is more idiomatic than `LOWER() LIKE` in PostgreSQL, (3) `julianday()` has no direct equivalent — PostgreSQL uses interval arithmetic on typed timestamps.
`─────────────────────────────────────────────────`

- [ ] **Step 1: Replace imports and remove inline-migration code**

  Delete the entire top of the file down through `_migrate_jobs_location_fk`. The new top of `db.py`:

  ```python
  import json
  from datetime import UTC, datetime

  import psycopg
  from psycopg_pool import ConnectionPool

  from app.models import FailedSource, Job


  def _now() -> str:
      return datetime.now(UTC).isoformat()


  def init_db(dsn: str) -> ConnectionPool:
      return ConnectionPool(dsn, min_size=1, max_size=10, open=True)
  ```

  Everything from `SCHEMA = """` down to `def init_db(path: str)` (inclusive of `init_db` body) is deleted.

- [ ] **Step 2: Replace `sqlite3.Connection` type annotations everywhere in the file**

  Global replace: `sqlite3.Connection` → `psycopg.Connection`

- [ ] **Step 3: Translate `get_new_jobs` and `save_jobs`**

  `get_new_jobs`: replace `"?" * len(jobs)` with `"%s" * len(jobs)`:
  ```python
  placeholders = ",".join(["%s"] * len(jobs))
  rows = conn.execute(f"SELECT key FROM jobs WHERE key IN ({placeholders})", keys).fetchall()
  ```

  `save_jobs`: replace `INSERT OR IGNORE` with `ON CONFLICT DO NOTHING` and `?` with `%s`:
  ```python
  conn.executemany(
      "INSERT INTO geocoded_locations (location, status) VALUES (%s, 'pending') ON CONFLICT DO NOTHING",
      [(loc,) for loc in locations],
  )
  conn.executemany(
      "INSERT INTO jobs "
      "(key, title, company, location, url, posted_date, source_name, source_id, summary, "
      "first_seen_run_id, first_seen_at) "
      "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
      [
          (j.key, j.title, j.company, j.location, j.url, j.posted_date, j.source_name,
           j.source_id, j.summary, run_id, now)
          for j in jobs
      ],
  )
  ```

- [ ] **Step 4: Translate `start_run` — use `RETURNING id`**

  ```python
  def start_run(conn: psycopg.Connection, kind: str = "scrape") -> int:
      cur = conn.execute(
          "INSERT INTO runs (started_at, kind) VALUES (%s, %s) RETURNING id",
          (_now(), kind),
      )
      row = cur.fetchone()
      if row is None:
          raise RuntimeError("INSERT INTO runs did not produce an id")
      conn.commit()
      return row[0]
  ```

- [ ] **Step 5: Translate `finish_run`**

  ```python
  conn.execute(
      "UPDATE runs SET finished_at = %s, new_job_count = %s, failed_sources = %s WHERE id = %s",
      (_now(), new_job_count, serialized, run_id),
  )
  ```

- [ ] **Step 6: Translate `list_runs` and `count_runs`**

  In `_run_filters_sql`: no SQL changes (no placeholders here).

  In `list_runs`:
  ```python
  # Change LIMIT ? OFFSET ? → LIMIT %s OFFSET %s
  query = (
      "SELECT id, started_at, finished_at, new_job_count, failed_sources, kind FROM runs "
      f"{where_sql} ORDER BY {order_column} {order_dir}, id {order_dir} LIMIT %s OFFSET %s"
  )
  rows = conn.execute(query, [*params, limit, offset]).fetchall()
  ```

  In `count_runs`: `conn.execute(f"SELECT COUNT(*) FROM runs {where_sql}", params)` — no placeholder changes needed here (params list from `_run_filters_sql` is empty for all current branches).

- [ ] **Step 7: Translate `get_settings`, `save_settings`, `save_preferences`, `seed_settings_if_empty`**

  `get_settings`: no placeholder changes (no params). Remove `bool()` wrappers since psycopg3 returns Python `bool` directly from BOOLEAN columns:
  ```python
  return {
      ...
      "resend_jobs": row[6],           # was bool(row[6])
      "hide_not_interested_on_map": row[7],  # was bool(row[7])
      ...
  }
  ```

  `save_settings`:
  ```python
  conn.execute(
      "INSERT INTO settings (id, smtp_host, smtp_port, smtp_user, email_from) "
      "VALUES (1, %s, %s, %s, %s) "
      "ON CONFLICT(id) DO UPDATE SET "
      "smtp_host=excluded.smtp_host, smtp_port=excluded.smtp_port, "
      "smtp_user=excluded.smtp_user, email_from=excluded.email_from",
      (smtp_host, smtp_port, smtp_user, email_from),
  )
  ```

  `save_preferences`: replace `?` with `%s`; remove `int()` wrappers (pass Python bools directly):
  ```python
  conn.execute(
      "INSERT INTO settings "
      "(id, email_days, resend_jobs, email_to, hide_not_interested_on_map, "
      "digest_max_per_company, digest_exclude_statuses) "
      "VALUES (1, %s, %s, %s, %s, %s, %s) "
      "ON CONFLICT(id) DO UPDATE SET "
      "email_days=excluded.email_days, resend_jobs=excluded.resend_jobs, "
      "email_to=excluded.email_to, "
      "hide_not_interested_on_map=excluded.hide_not_interested_on_map, "
      "digest_max_per_company=excluded.digest_max_per_company, "
      "digest_exclude_statuses=excluded.digest_exclude_statuses",
      (email_days, resend_jobs, email_to, hide_not_interested_on_map,
       digest_max_per_company, digest_exclude_statuses),
  )
  ```

  `seed_settings_if_empty`:
  ```python
  conn.execute(
      "INSERT INTO settings (id, smtp_host, smtp_port, smtp_user, email_from, email_to) "
      "VALUES (1, %s, %s, %s, %s, %s)",
      (smtp_host, smtp_port, smtp_user, email_from, email_to),
  )
  ```

- [ ] **Step 8: Translate `_JOB_SORT_COLUMNS`**

  ```python
  _JOB_SORT_COLUMNS = {
      "company": "LOWER(jobs.company)",
      "title": "LOWER(jobs.title)",
      "first_seen_at": "jobs.first_seen_at",
      "age_days": (
          "(EXTRACT(EPOCH FROM ("
          "COALESCE(jobs.removed_at::timestamptz, NOW()) - jobs.first_seen_at::timestamptz"
          ")) / 86400)"
      ),
  }
  ```

- [ ] **Step 9: Translate `_job_filters_sql`**

  Replace `LOWER(jobs.company) LIKE ?` with `jobs.company ILIKE %s` (no manual `.lower()` needed):
  ```python
  if company:
      clauses.append("jobs.company ILIKE %s")
      params.append(f"%{company}%")
  ```

  Replace all `?` with `%s` in every `clauses.append(...)` call:
  - `"jobs.source_name IN ({ph})"` — `ph = ",".join(["%s"] * len(source_name))`
  - `"(jobs.status IS NULL OR jobs.status IN ({ph}))"` — same pattern
  - `"jobs.status IN ({ph})"` — same pattern
  - `"geocoded_locations.display_name = %s"`
  - `"geocoded_locations.region IN ({ph})"` — same pattern
  - `"haversine_miles(geocoded_locations.lat, geocoded_locations.lng, %s, %s) <= %s"`

- [ ] **Step 10: Translate `list_jobs`**

  Replace `jobs.rowid` with `jobs.key` in ORDER BY tie-break:
  ```python
  query = (
      "... "
      f"{where_sql} ORDER BY {order_column} {order_dir}, jobs.key {order_dir} LIMIT %s OFFSET %s"
  )
  rows = conn.execute(query, [*params, limit, offset]).fetchall()
  ```

- [ ] **Step 11: Translate `count_jobs`, `list_job_source_names`, `list_job_locations`, `list_job_states`**

  `count_jobs`: no placeholder changes needed (params from `_job_filters_sql` already updated).

  `list_job_source_names`: remove `COLLATE NOCASE`:
  ```python
  rows = conn.execute(
      "SELECT DISTINCT source_name FROM jobs ORDER BY LOWER(source_name)"
  ).fetchall()
  ```

  `list_job_locations`:
  ```python
  rows = conn.execute(
      "SELECT DISTINCT display_name FROM geocoded_locations "
      "WHERE status = 'resolved' AND display_name IS NOT NULL "
      "ORDER BY LOWER(display_name)"
  ).fetchall()
  ```

  `list_job_states`:
  ```python
  rows = conn.execute(
      "SELECT DISTINCT region FROM geocoded_locations "
      "WHERE status IN ('resolved', 'manual') AND region IS NOT NULL "
      "ORDER BY LOWER(region)"
  ).fetchall()
  ```

- [ ] **Step 12: Translate `mark_emailed`, `get_unemailed_jobs`, `reconcile_jobs`, `mark_job_removed`, `set_job_status`, `get_job_status_history`**

  For each function, replace `?` with `%s` and `",".join("?" * len(x))` with `",".join(["%s"] * len(x))`.

  Key change in `reconcile_jobs`:
  ```python
  conn.execute(
      f"UPDATE jobs SET removed_at = %s WHERE key IN ({placeholders})",
      [now, *remove_keys],
  )
  conn.execute(
      f"UPDATE jobs SET removed_at = NULL, emailed_at = NULL WHERE key IN ({placeholders})",
      reactivate_keys,
  )
  ```

  `set_job_status`:
  ```python
  cur = conn.execute("UPDATE jobs SET status = %s WHERE key = %s", (status, key))
  if cur.rowcount == 0:
      raise KeyError(key)
  conn.execute(
      "INSERT INTO job_status_history (job_key, status, changed_at) VALUES (%s, %s, %s)",
      (key, status, now),
  )
  ```

- [ ] **Step 13: Translate `get_geocoded_location`, `set_location_override`, `clear_location_override`**

  `get_geocoded_location`:
  ```python
  row = conn.execute(
      "SELECT display_name, city, region, country, lat, lng, provider FROM geocoded_locations "
      "WHERE location = %s AND status IN ('resolved', 'manual')",
      (location,),
  ).fetchone()
  ```

  `set_location_override`: replace `?` with `%s` throughout; the `ON CONFLICT(location) DO UPDATE SET` syntax is identical in PostgreSQL.

  `clear_location_override`:
  ```python
  cur = conn.execute("UPDATE jobs SET location_override = NULL WHERE key = %s", (key,))
  ```

- [ ] **Step 14: Translate `get_job_statuses`, `get_emailed_keys`, `set_job_duplicate`, `clear_job_duplicate`**

  `get_job_statuses` and `get_emailed_keys`: `"?" * len(keys)` → `["%s"] * len(keys)`.

  `set_job_duplicate`:
  ```python
  cur = conn.execute(
      "UPDATE jobs SET is_duplicate = TRUE, duplicate_of = %s WHERE key = %s",
      (duplicate_of, key),
  )
  ```

  `clear_job_duplicate`:
  ```python
  cur = conn.execute(
      "UPDATE jobs SET is_duplicate = FALSE, duplicate_of = NULL WHERE key = %s",
      (key,),
  )
  ```

- [ ] **Step 15: Verify no remaining `sqlite3` or `?` references in `app/db.py`**

  ```bash
  grep -n "sqlite3\|\b?\b" app/db.py
  ```

  Expected: zero matches.

- [ ] **Step 16: Commit**

  ```bash
  git add app/db.py
  git commit -m "feat: rewrite db.py for PostgreSQL — psycopg3, Alembic, no inline migrations (#138)"
  ```

---

### Task 5: Update Type Annotations in Non-DB Modules

**Files:**
- Modify: `app/orchestrator.py`
- Modify: `app/checker.py`
- Modify: `app/geocoding/service.py`

**Interfaces:**
- Consumes: `psycopg.Connection` (from Task 4)
- Produces: all three modules type-annotated with `psycopg.Connection`

- [ ] **Step 1: Update `app/orchestrator.py`**

  Replace:
  ```python
  import sqlite3
  ```
  With:
  ```python
  import psycopg
  ```

  Replace `sqlite3.Connection` with `psycopg.Connection` in the function signature:
  ```python
  def run_once(conn: psycopg.Connection, sources: list[SourceConfig], ...) -> RunSummary:
  ```

- [ ] **Step 2: Update `app/checker.py`**

  Same replacement: `import sqlite3` → `import psycopg`; `sqlite3.Connection` → `psycopg.Connection`.

- [ ] **Step 3: Update `app/geocoding/service.py`**

  Same replacement.

- [ ] **Step 4: Run mypy to check type correctness**

  ```bash
  mypy app
  ```

  Expected: no errors related to `psycopg.Connection`.

- [ ] **Step 5: Commit**

  ```bash
  git add app/orchestrator.py app/checker.py app/geocoding/service.py
  git commit -m "refactor: update sqlite3.Connection → psycopg.Connection type annotations (#138)"
  ```

---

### Task 6: Update `app/scheduler.py` — Pool Pattern

**Files:**
- Modify: `app/scheduler.py`

**Interfaces:**
- Consumes: `ConnectionPool` from `psycopg_pool`
- Produces:
  - `run_and_notify(pool: ConnectionPool, sources_path: str, tz: str, force: bool) -> None`
  - `create_scheduler(pool: ConnectionPool, sources_path: str, run_cron: str, tz: str) -> BackgroundScheduler`

- [ ] **Step 1: Add pool import and update `run_and_notify`**

  Add at top of file:
  ```python
  from psycopg_pool import ConnectionPool
  ```

  Change `run_and_notify` signature and body to acquire a connection from the pool:
  ```python
  def run_and_notify(pool: ConnectionPool, sources_path: str, tz: str = "UTC", force: bool = False) -> None:
      with pool.connection() as conn:
          settings = db.get_settings(conn)
          # ... rest of the function body unchanged, using conn ...
  ```

  (The body uses `conn` in many places — wrap the whole body in `with pool.connection() as conn:` at one level of indentation.)

- [ ] **Step 2: Update `create_scheduler`**

  ```python
  def create_scheduler(pool: ConnectionPool, sources_path: str, run_cron: str, tz: str) -> BackgroundScheduler:
      ...
      sched.add_job(run_and_notify, trigger, args=[pool, sources_path, tz], id="daily_run")
      return sched
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add app/scheduler.py
  git commit -m "refactor: scheduler uses ConnectionPool, acquires conn per run (#138)"
  ```

---

### Task 7: Update App Startup & Route Files

**Files:**
- Modify: `app/web/main.py`
- Modify: `app/web/routes_dashboard.py`
- Modify: `app/web/routes_jobs.py`
- Modify: `app/web/routes_settings.py`

**Interfaces:**
- Consumes: `init_db(dsn: str) -> ConnectionPool` (Task 4); `run_and_notify(pool, ...)` (Task 6)
- Produces: `app.state.pool` on all routes; `CAREERSPYDER_DB_PATH` removed

- [ ] **Step 1: Update `app/web/main.py`**

  Change env var and lifespan:
  ```python
  from psycopg_pool import ConnectionPool

  @asynccontextmanager
  async def lifespan(app: FastAPI):
      dsn = os.environ.get("DATABASE_URL", "postgresql://careerspyder:dev@localhost:5432/careerspyder")
      sources_path = os.environ.get("CAREERSPYDER_SOURCES_PATH", "/app/config/sources.json")
      run_cron = os.environ.get("RUN_CRON", "0 7 * * *")
      tz = os.environ.get("TZ", "UTC")

      pool: ConnectionPool = db.init_db(dsn)

      with pool.connection() as conn:
          db.seed_settings_if_empty(
              conn,
              os.environ.get("SMTP_HOST", ""),
              int(os.environ.get("SMTP_PORT", "587")),
              os.environ.get("SMTP_USER", ""),
              os.environ.get("EMAIL_FROM", ""),
              os.environ.get("EMAIL_TO", ""),
          )

      app.state.pool = pool
      app.state.sources_path = sources_path
      app.state.scheduler = create_scheduler(pool, sources_path, run_cron, tz)

      yield

      app.state.scheduler.shutdown()
      pool.close()
  ```

  Remove the old `conn = db.init_db(db_path)` line and `app.state.conn = conn` and `conn.close()`.

- [ ] **Step 2: Update `app/web/routes_dashboard.py`**

  Every `request.app.state.conn` becomes `request.app.state.pool`. Acquire a connection inside each route handler. For handlers that call a background task, pass the pool:

  ```python
  # Route that lists runs (read-only):
  with request.app.state.pool.connection() as conn:
      total = db.count_runs(conn, failures=failures_filter)
      rows = db.list_runs(conn, limit=PAGE_SIZE, offset=pagination.offset, ...)

  # "Trigger run" route:
  background_tasks.add_task(
      run_and_notify, request.app.state.pool, request.app.state.sources_path, force=True,
  )

  # "Check URLs" route:
  with request.app.state.pool.connection() as conn:
      run_id = db.start_run(conn, kind="url_check")
  background_tasks.add_task(_run_url_check, request.app.state.pool, run_id)
  ```

  Update `_run_url_check` signature:
  ```python
  def _run_url_check(pool: ConnectionPool, run_id: int) -> None:
      with _run_lock:
          with pool.connection() as conn:
              removed = checker.check_job_urls(conn)
              db.finish_run(conn, run_id, removed, [])
  ```

  Add import at top: `from psycopg_pool import ConnectionPool`

- [ ] **Step 3: Update `app/web/routes_jobs.py`**

  Every `conn = request.app.state.conn` becomes:
  ```python
  with request.app.state.pool.connection() as conn:
      # ... db calls ...
  ```

  Wrap each route handler's db calls in this context manager.

- [ ] **Step 4: Update `app/web/routes_settings.py`**

  Same pattern as routes_jobs.py — wrap each handler's db calls with pool acquisition.

- [ ] **Step 5: Verify no remaining `app.state.conn` references**

  ```bash
  grep -rn "app\.state\.conn\|state\.conn" app/
  ```

  Expected: zero matches.

- [ ] **Step 6: Commit**

  ```bash
  git add app/web/main.py app/web/routes_dashboard.py app/web/routes_jobs.py app/web/routes_settings.py
  git commit -m "refactor: web layer uses pool.connection() per request (#138)"
  ```

---

### Task 8: Update Test Fixtures

**Files:**
- Rewrite: `tests/conftest.py`
- Modify: `tests/web/conftest.py`

**Interfaces:**
- Produces:
  - `pg_conn` fixture: `psycopg.Connection` to a fresh, migrated test database
  - `pg_dsn` fixture: DSN string for the same database (used by web `client` fixture)
  - Updated `client` fixture: uses `DATABASE_URL` env var

- [ ] **Step 1: Rewrite `tests/conftest.py`**

  ```python
  import pytest
  import psycopg
  from pytest_postgresql import factories

  from alembic.config import Config
  from alembic import command

  # Session-scoped PostgreSQL process (shared across all tests in a session)
  postgresql_proc = factories.postgresql_proc(port=None)


  @pytest.fixture(scope="function")
  def pg_dsn(postgresql_proc, tmp_path):
      """Creates a fresh database for this test, applies Alembic migrations, yields DSN."""
      dbname = f"cs_test_{tmp_path.name}"[:63]
      host, port, user = postgresql_proc.host, postgresql_proc.port, postgresql_proc.user

      admin = psycopg.connect(
          f"host={host} port={port} user={user} dbname=postgres", autocommit=True
      )
      admin.execute(f"CREATE DATABASE {dbname}")
      admin.close()

      dsn = f"postgresql://{user}@{host}:{port}/{dbname}"

      cfg = Config("alembic.ini")
      cfg.set_main_option(
          "sqlalchemy.url", dsn.replace("postgresql://", "postgresql+psycopg://", 1)
      )
      command.upgrade(cfg, "head")

      yield dsn

      admin = psycopg.connect(
          f"host={host} port={port} user={user} dbname=postgres", autocommit=True
      )
      admin.execute(f"DROP DATABASE {dbname}")
      admin.close()


  @pytest.fixture
  def pg_conn(pg_dsn):
      """psycopg3 connection to a fresh, migrated test database."""
      conn = psycopg.connect(pg_dsn)
      yield conn
      conn.close()
  ```

- [ ] **Step 2: Update `tests/web/conftest.py`**

  Change the `client` fixture to use `pg_dsn` and `DATABASE_URL`:

  ```python
  @pytest.fixture
  def client(pg_dsn, monkeypatch):
      monkeypatch.setenv("DATABASE_URL", pg_dsn)
      sources_path = ...  # keep tmp_path logic for sources.json
      monkeypatch.setenv("CAREERSPYDER_SOURCES_PATH", str(sources_path))
      monkeypatch.setenv("RUN_CRON", "0 8 * * *")
      monkeypatch.setenv("TZ", "UTC")
      monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
      monkeypatch.setenv("SMTP_PORT", "587")
      monkeypatch.setenv("SMTP_USER", "user")
      monkeypatch.setenv("EMAIL_FROM", "from@x.test")
      monkeypatch.setenv("EMAIL_TO", "to@x.test")
      monkeypatch.setenv("SMTP_PASSWORD", "secret")

      from app.web.main import app
      with TestClient(app) as test_client:
          yield test_client
  ```

  The `client` fixture needs `pg_dsn` which needs `postgresql_proc` which needs `tmp_path`. The `tmp_path` needed for `sources.json` is a problem — `pg_dsn` uses `tmp_path` for the DB name. Use a different approach: use `tmp_path` only for sources.json and let `pg_dsn` generate its own DB name from a UUID:

  Revise `pg_dsn` to use `uuid4()` for the dbname instead of `tmp_path.name`:
  ```python
  import uuid

  @pytest.fixture(scope="function")
  def pg_dsn(postgresql_proc):
      dbname = f"cs_test_{uuid.uuid4().hex[:12]}"
      ...
  ```

  And revise `client` to take its own `tmp_path`:
  ```python
  @pytest.fixture
  def client(pg_dsn, tmp_path, monkeypatch):
      monkeypatch.setenv("DATABASE_URL", pg_dsn)
      sources_path = tmp_path / "sources.json"
      sources_path.write_text(json.dumps({"sources": []}))
      monkeypatch.setenv("CAREERSPYDER_SOURCES_PATH", str(sources_path))
      ...
  ```

- [ ] **Step 3: Run one test to verify fixtures work**

  ```bash
  pytest tests/test_db.py::test_new_job_then_seen_on_second_run -v
  ```

  Expected: this test will either PASS (if db.py is updated) or FAIL with a meaningful error (not a fixture setup error).

- [ ] **Step 4: Commit**

  ```bash
  git add tests/conftest.py tests/web/conftest.py
  git commit -m "test: replace tmp_db_path with pg_conn fixture (pytest-postgresql) (#138)"
  ```

---

### Task 9: Update `tests/test_db.py`

**Files:**
- Modify: `tests/test_db.py`

**Interfaces:**
- Consumes: `pg_conn` fixture (psycopg.Connection, schema already applied)

- [ ] **Step 1: Global fixture rename**

  Replace every `tmp_db_path` with `pg_conn` (function signature and any `db.init_db(tmp_db_path)` calls).
  Delete every line `conn = db.init_db(tmp_db_path)` — `pg_conn` IS the connection.
  Rename `tmp_db_path` parameter in test function signatures to `pg_conn`.

- [ ] **Step 2: Delete SQLite-specific migration tests**

  Delete these tests entirely (they test inline migration logic that no longer exists):
  - `test_init_db_migrates_a_legacy_jobs_table_to_add_the_location_fk`
  - `test_init_db_adds_new_columns_to_a_pre_existing_database`
  - `test_init_db_adds_new_columns_to_an_existing_jobs_table`
  - `test_init_db_adds_location_override_column`
  - `test_init_db_enables_wal_mode_and_busy_timeout`

- [ ] **Step 3: Update `test_init_db_creates_geocoded_locations_table_and_enables_fk_pragma`**

  Replace PRAGMA assertions with `information_schema`:
  ```python
  def test_schema_has_geocoded_locations_table_and_jobs_fk(pg_conn):
      # Verify table exists
      row = pg_conn.execute(
          "SELECT table_name FROM information_schema.tables "
          "WHERE table_schema = 'public' AND table_name = 'geocoded_locations'"
      ).fetchone()
      assert row is not None

      # Verify FK from jobs.location → geocoded_locations.location
      row = pg_conn.execute(
          "SELECT COUNT(*) FROM information_schema.referential_constraints rc "
          "JOIN information_schema.key_column_usage kcu "
          "ON rc.constraint_name = kcu.constraint_name "
          "WHERE kcu.table_name = 'jobs' AND kcu.column_name = 'location'"
      ).fetchone()
      assert row[0] >= 1
  ```

- [ ] **Step 4: Update FK enforcement test**

  Replace `sqlite3.IntegrityError` with `psycopg.errors.ForeignKeyViolation`:
  ```python
  def test_fk_enforcement_rejects_a_job_location_with_no_geocoded_locations_row(pg_conn):
      import psycopg.errors

      with pytest.raises(psycopg.errors.ForeignKeyViolation):
          pg_conn.execute(
              "INSERT INTO jobs (key, title, url, source_name, first_seen_at, location) "
              "VALUES ('k1', 'Engineer', 'https://x.test/1', 'Acme Board', "
              "'2026-01-01T00:00:00+00:00', 'Nowhere, XX')"
          )
  ```

- [ ] **Step 5: Update `test_init_db_creates_job_status_history_table`**

  ```python
  def test_schema_has_job_status_history_table(pg_conn):
      row = pg_conn.execute(
          "SELECT table_name FROM information_schema.tables "
          "WHERE table_schema = 'public' AND table_name = 'job_status_history'"
      ).fetchone()
      assert row is not None
  ```

- [ ] **Step 6: Add new negative tests**

  ```python
  def test_save_jobs_duplicate_key_is_silently_ignored(pg_conn):
      run_id = db.start_run(pg_conn)
      job = make_job(key="k1")
      db.save_jobs(pg_conn, [job], run_id)

      db.save_jobs(pg_conn, [job], run_id)  # must not raise

      assert db.count_jobs(pg_conn) == 1


  def test_start_run_returns_integer_id(pg_conn):
      run_id = db.start_run(pg_conn)

      assert isinstance(run_id, int)
      assert run_id >= 1


  def test_fk_violation_raises_psycopg_error(pg_conn):
      import psycopg.errors

      with pytest.raises(psycopg.errors.ForeignKeyViolation):
          pg_conn.execute(
              "INSERT INTO jobs (key, title, url, source_name, first_seen_at, location) "
              "VALUES ('k1', 'Engineer', 'https://x.test/1', 'Board', "
              "'2026-01-01T00:00:00+00:00', 'no-such-location')"
          )
  ```

- [ ] **Step 7: Remove any remaining `import sqlite3` inside test bodies and replace with `import psycopg`**

  Lines like:
  ```python
  import sqlite3
  legacy_conn = sqlite3.connect(tmp_db_path)
  ```
  These are in the deleted migration tests — verify they're all gone.

- [ ] **Step 8: Run the full `test_db.py` suite**

  ```bash
  pytest tests/test_db.py -v
  ```

  Expected: all remaining tests PASS.

- [ ] **Step 9: Commit**

  ```bash
  git add tests/test_db.py
  git commit -m "test: migrate test_db.py to PostgreSQL — remove SQLite-specific tests, add negatives (#138)"
  ```

---

### Task 10: Update Remaining Test Files

**Files:**
- Modify: `tests/test_orchestrator.py`
- Modify: `tests/test_scheduler.py`
- Modify: `tests/test_geocoding.py`
- Modify: `tests/test_checker.py`

**Interfaces:**
- Consumes: `pg_conn` fixture

For each of these files the change is the same mechanical pattern:
1. Replace `tmp_db_path` with `pg_conn` in test function parameter lists
2. Delete `conn = db.init_db(tmp_db_path)` line at the top of each test body
3. The variable name `conn` stays — it was assigned from `db.init_db(...)`, now it's the `pg_conn` parameter renamed to `conn` in the function body OR just use `pg_conn` as the name

- [ ] **Step 1: Update `tests/test_orchestrator.py`**

  Pattern for each test:
  ```python
  # Before:
  def test_run_once_...(tmp_db_path):
      conn = db.init_db(tmp_db_path)
      ...

  # After:
  def test_run_once_...(pg_conn):
      conn = pg_conn
      ...
  ```

  Or more concisely, rename the parameter directly:
  ```python
  def test_run_once_...(pg_conn):
      # use pg_conn directly as conn
  ```
  And replace `conn` with `pg_conn` throughout the test body, OR keep `conn = pg_conn` as the first line.

- [ ] **Step 2: Update `tests/test_scheduler.py`**

  Same pattern. Note: `run_and_notify` now takes a pool, not a conn. Tests that call `run_and_notify(conn, ...)` must change to pass a pool. Create a tiny pool from the test DSN:

  ```python
  def test_run_and_notify_sends_email_when_digest_present(pg_dsn, tmp_path, monkeypatch):
      from psycopg_pool import ConnectionPool
      pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
      # ... setup using: with pool.connection() as conn: db.save_jobs(conn, ...) ...
      run_and_notify(pool, str(sources_path), "UTC")
      pool.close()
  ```

  Tests that set up db state via `db.*` calls need to acquire a connection from the pool:
  ```python
  with pool.connection() as conn:
      db.seed_settings_if_empty(conn, "smtp.test", 587, "u", "f@t.com", "t@t.com")
      db.save_jobs(conn, jobs, db.start_run(conn))
  ```

- [ ] **Step 3: Update `tests/test_geocoding.py`**

  Same `tmp_db_path` → `pg_conn` rename, delete `conn = db.init_db(tmp_db_path)`.

- [ ] **Step 4: Update `tests/test_checker.py`**

  Same rename pattern.

- [ ] **Step 5: Run all unit tests**

  ```bash
  pytest tests/ -v --ignore=tests/integration --ignore=tests/web
  ```

  Expected: all tests PASS.

- [ ] **Step 6: Run web tests**

  ```bash
  pytest tests/web/ -v
  ```

  Expected: all tests PASS.

- [ ] **Step 7: Run full suite**

  ```bash
  pytest -q --cov=app --cov-report=term-missing
  ```

  Expected: full suite passes; coverage comparable to pre-migration.

- [ ] **Step 8: Commit**

  ```bash
  git add tests/test_orchestrator.py tests/test_scheduler.py tests/test_geocoding.py tests/test_checker.py
  git commit -m "test: migrate orchestrator/scheduler/geocoding/checker tests to PostgreSQL (#138)"
  ```

---

### Task 11: CI Update

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `test` job in CI has a PostgreSQL 17 service container; `DATABASE_URL` env var set for that job

- [ ] **Step 1: Add PostgreSQL service and env var to the `test` job**

  In `ci.yml`, find the `test:` job and add a `services:` block and `env:` block:

  ```yaml
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:17
        env:
          POSTGRES_DB: careerspyder_test
          POSTGRES_USER: careerspyder
          POSTGRES_PASSWORD: test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 5s
          --health-timeout 3s
          --health-retries 5
    env:
      DATABASE_URL: postgresql://careerspyder:test@localhost:5432/careerspyder_test
    steps:
      - uses: actions/checkout@...
      ...
      - run: pytest -q --cov=app --cov-report=term-missing
  ```

  Note: `pytest-postgresql` spawns its own PostgreSQL process, so the service container is not strictly required for unit tests. However, having a running PostgreSQL available is good practice and allows integration-style tests to use it. Alternatively, if `pytest-postgresql` handles its own server, the `services:` block can be omitted — verify by running CI and checking if `postgresql_proc` fixture works without a pre-existing server. If it does, the service block is optional but harmless.

- [ ] **Step 2: Commit**

  ```bash
  git add .github/workflows/ci.yml
  git commit -m "ci: add PostgreSQL 17 service to test job (#138)"
  ```

---

### Task 12: Docker & Deployment

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose.prod.yml`
- Modify: `docker-entrypoint.sh`
- Modify: `.env.example`

**Interfaces:**
- Produces: a running `docker-compose up` starts PostgreSQL 17 + CareerSpyder, applies migrations, serves the app

- [ ] **Step 1: Update `docker-compose.yml`**

  Replace the current single-service file with:

  ```yaml
  services:
    postgres:
      image: postgres:17
      restart: unless-stopped
      environment:
        POSTGRES_DB: careerspyder
        POSTGRES_USER: careerspyder
        POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-dev}
      volumes:
        - ./data/postgres:/var/lib/postgresql/data
      healthcheck:
        test: ["CMD-SHELL", "pg_isready -U careerspyder"]
        interval: 5s
        timeout: 3s
        retries: 5

    careerspyder:
      build: .
      image: careerspyder:latest
      restart: unless-stopped
      depends_on:
        postgres:
          condition: service_healthy
      ports:
        - "32600:8080"
      environment:
        DATABASE_URL: postgresql://careerspyder:${POSTGRES_PASSWORD:-dev}@postgres:5432/careerspyder
        SMTP_PASSWORD: ${SMTP_PASSWORD}
        SMTP_HOST: ${SMTP_HOST:-}
        SMTP_PORT: ${SMTP_PORT:-587}
        SMTP_USER: ${SMTP_USER:-}
        EMAIL_FROM: ${EMAIL_FROM:-}
        EMAIL_TO: ${EMAIL_TO:-}
        RUN_CRON: ${RUN_CRON:-0 7 * * *}
        TZ: ${TZ:-UTC}
        PUBLIC_BASE_URL: ${PUBLIC_BASE_URL:-}
        GA_MEASUREMENT_ID: ${GA_MEASUREMENT_ID:-}
        CAREERSPYDER_SOURCES_PATH: /app/config/sources.json
      volumes:
        - ./config:/app/config
  ```

  Remove `CAREERSPYDER_DB_PATH` and the `./data:/app/data` volume from `careerspyder` (data now lives in the postgres container).

- [ ] **Step 2: Update `docker-compose.prod.yml`**

  ```yaml
  services:
    postgres:
      image: postgres:17
      restart: unless-stopped
      environment:
        POSTGRES_DB: careerspyder
        POSTGRES_USER: careerspyder
        POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      volumes:
        - careerspyder_pgdata:/var/lib/postgresql/data
      healthcheck:
        test: ["CMD-SHELL", "pg_isready -U careerspyder"]
        interval: 5s
        timeout: 3s
        retries: 5

    careerspyder:
      image: jasonkryst/careerspyder:latest
      restart: unless-stopped
      depends_on:
        postgres:
          condition: service_healthy
      ports:
        - "32600:8080"
      environment:
        DATABASE_URL: postgresql://careerspyder:${POSTGRES_PASSWORD}@postgres:5432/careerspyder
        SMTP_PASSWORD: ${SMTP_PASSWORD}
        SMTP_HOST: ${SMTP_HOST:-}
        SMTP_PORT: ${SMTP_PORT:-587}
        SMTP_USER: ${SMTP_USER:-}
        EMAIL_FROM: ${EMAIL_FROM:-}
        EMAIL_TO: ${EMAIL_TO:-}
        RUN_CRON: ${RUN_CRON:-0 7 * * *}
        TZ: ${TZ:-UTC}
        PUBLIC_BASE_URL: ${PUBLIC_BASE_URL:-}
        GA_MEASUREMENT_ID: ${GA_MEASUREMENT_ID:-}
        CAREERSPYDER_SOURCES_PATH: /app/config/sources.json
      volumes:
        - careerspyder_config:/app/config

  volumes:
    careerspyder_pgdata:
    careerspyder_config:
  ```

- [ ] **Step 3: Update `docker-entrypoint.sh`**

  Read the current file, then add `alembic upgrade head` before the `exec` line:

  ```bash
  # Run database migrations before starting the server
  alembic upgrade head
  ```

  Place this after the `chown`/`setpriv` setup and before the final `exec` of uvicorn.

- [ ] **Step 4: Update `.env.example`**

  Replace `CAREERSPYDER_DB_PATH=...` with:
  ```
  DATABASE_URL=postgresql://careerspyder:yourpassword@localhost:5432/careerspyder
  POSTGRES_PASSWORD=yourpassword
  ```

- [ ] **Step 5: Verify docker-compose up works locally**

  ```bash
  docker compose up --build
  ```

  Expected: postgres starts first, passes healthcheck, careerspyder starts, alembic runs, uvicorn serves on port 32600.

- [ ] **Step 6: Commit**

  ```bash
  git add docker-compose.yml docker-compose.prod.yml docker-entrypoint.sh .env.example
  git commit -m "feat: add PostgreSQL 17 service to Docker Compose; alembic upgrade in entrypoint (#138)"
  ```

---

### Task 13: Documentation

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Add `CHANGELOG.md` entry**

  Add at the top of the changelog (after the header), before the current `0.65.1` entry:

  ```markdown
  ## [0.66.0] - 2026-09-15

  ### Breaking Changes
  - **PostgreSQL replaces SQLite.** The app now requires a PostgreSQL 17 database.
  - `CAREERSPYDER_DB_PATH` environment variable removed. Use `DATABASE_URL` instead (e.g. `postgresql://user:pass@host:5432/careerspyder`).
  - Docker Compose now includes a `postgres` service; `./data/state.db` is no longer written.

  ### Added
  - Alembic migration system (`alembic upgrade head` runs automatically at container startup).
  - `POSTGRES_PASSWORD` env var for Docker deployments.

  ### Internal
  - `psycopg` (psycopg3) replaces `sqlite3` as the database driver.
  - Connection pool (`psycopg_pool.ConnectionPool`) replaces single shared connection.
  - Tests use `pytest-postgresql` for isolated PostgreSQL databases per test.
  ```

- [ ] **Step 2: Update `README.md` setup section**

  Find the "Getting Started" or "Configuration" section that mentions `CAREERSPYDER_DB_PATH` and the SQLite file. Replace with:

  ```markdown
  **Database:** CareerSpyder uses PostgreSQL 17. The Docker Compose setup starts a `postgres`
  container automatically. Set `POSTGRES_PASSWORD` in your `.env` file.

  To connect to an external database, set `DATABASE_URL`:
  ```
  DATABASE_URL=postgresql://user:password@host:5432/careerspyder
  ```
  ```

  Remove any mention of `CAREERSPYDER_DB_PATH` or `state.db`.

- [ ] **Step 3: Update `AGENTS.md` DB layer description**

  Find the section describing the database layer and update it to reflect psycopg3 + Alembic:

  > **Database:** `app/db.py` — raw SQL via psycopg3 (`psycopg`). All public functions take a `psycopg.Connection` as their first argument. `init_db(dsn)` returns a `ConnectionPool`; callers acquire connections with `with pool.connection() as conn:`. Schema is managed by Alembic; migrations live in `alembic/versions/`. Tests use `pytest-postgresql` — the `pg_conn` fixture in `tests/conftest.py` provides a fresh psycopg3 connection per test with the schema already applied.

- [ ] **Step 4: Commit**

  ```bash
  git add CHANGELOG.md README.md AGENTS.md
  git commit -m "docs: update CHANGELOG, README, AGENTS for PostgreSQL migration (#138)"
  ```

---

## Self-Review

**Spec coverage check:**

| Spec Section | Covered by Task |
|---|---|
| Architecture & Connection Model | Tasks 4, 6, 7 |
| SQL Dialect Translation (all 14 items) | Task 4 (steps 2–14) |
| Haversine function → PostgreSQL | Task 3, Task 4 step 1 |
| Alembic setup | Tasks 2, 3 |
| `DATABASE_URL` replaces `CAREERSPYDER_DB_PATH` | Tasks 7, 12, 13 |
| Docker — postgres:17 service | Task 12 |
| docker-entrypoint.sh — alembic upgrade head | Task 12 |
| Test fixture — pytest-postgresql | Task 8 |
| test_db.py — delete SQLite migration tests | Task 9 |
| test_db.py — update FK test | Task 9 |
| test_db.py — new negative tests | Task 9 |
| Other test files (orchestrator, scheduler, etc.) | Task 10 |
| CI — PostgreSQL service | Task 11 |
| Version 0.66.0 | Task 1 |
| CHANGELOG, README, AGENTS | Task 13 |

**No TBDs found.** All steps contain actual code or exact commands.

**Type consistency:** `psycopg.Connection` used in Tasks 4, 5, 6, 7, 8, 9, 10. `ConnectionPool` (from `psycopg_pool`) used in Tasks 4 (`init_db` return type), 6, 7, 10. These are consistent throughout.
