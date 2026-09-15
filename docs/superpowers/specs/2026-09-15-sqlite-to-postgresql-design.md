# SQLite → PostgreSQL Migration Design

**Issue:** #138  
**Date:** 2026-09-15  
**Version bump:** 0.65.1 → 0.66.0  
**Prerequisite for:** #31 (Authentication)

---

## Overview

Replace the SQLite database engine with PostgreSQL 17. The db layer stays raw SQL (no ORM); psycopg3 replaces sqlite3 as the driver; Alembic replaces the hand-rolled inline migration system. The public function signatures in `app/db.py` do not change — every caller passes a connection and gets back the same dicts/objects it always did.

Clean start: no data migration from existing SQLite files.

---

## Architecture & Connection Model

### Before
```
init_db(path: str) -> sqlite3.Connection
# shared across FastAPI threadpool, APScheduler, BackgroundTasks
```

### After
```
init_db(dsn: str) -> psycopg_pool.ConnectionPool
# callers acquire a connection via: with pool.connection() as conn: ...
```

All `db.py` public functions keep their existing signature `(conn, ...)`. Callers that previously passed the shared sqlite3 connection now pass a connection acquired from the pool.

**App startup (`app/web/main.py`):** `app.state.conn` → `app.state.pool`.

**Route handlers** currently do `conn = request.app.state.conn`. They change to:
```python
with request.app.state.pool.connection() as conn:
    result = db.some_function(conn, ...)
```
Every route that references `request.app.state.conn` gets this wrapping treatment. `db.py`'s internal functions are untouched at the call-site level.

### Environment variable
`CAREERSPYDER_DB_PATH` is removed. Replaced by:
```
DATABASE_URL=postgresql://careerspyder:<password>@postgres:5432/careerspyder
```

---

## SQL Dialect Translation

Every SQLite-specific construct has a direct PostgreSQL equivalent:

| SQLite | PostgreSQL |
|--------|------------|
| `?` placeholder | `%s` |
| `INSERT OR IGNORE INTO …` | `INSERT … ON CONFLICT DO NOTHING` |
| `ORDER BY col COLLATE NOCASE` | `ORDER BY LOWER(col)` |
| `LOWER(col) LIKE ?` | `col ILIKE %s` |
| `julianday(COALESCE(removed_at, 'now')) - julianday(first_seen_at)` | `EXTRACT(EPOCH FROM (COALESCE(removed_at::timestamptz, NOW()) - first_seen_at::timestamptz)) / 86400` |
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY` |
| `cur.lastrowid` | `INSERT … RETURNING id` + `cursor.fetchone()[0]` |
| `conn.create_function("haversine_miles", 4, fn)` | `CREATE OR REPLACE FUNCTION haversine_miles(…)` in Alembic |
| `PRAGMA foreign_keys = ON` | Enforced by default in PostgreSQL |
| `PRAGMA journal_mode=WAL` | Not applicable (server-managed) |
| `PRAGMA busy_timeout=5000` | Not applicable |
| `PRAGMA table_info(tbl)` | `information_schema.columns` |
| `PRAGMA foreign_key_list(tbl)` | `information_schema.table_constraints` |
| `sqlite_master` | `information_schema.tables` |
| `INTEGER NOT NULL DEFAULT 0` (booleans) | `BOOLEAN NOT NULL DEFAULT FALSE` |
| `jobs.rowid` tie-break in ORDER BY | `jobs.key` (TEXT primary key) |

### Haversine function
The Python UDF registered via `conn.create_function()` becomes a PostgreSQL SQL function created in the initial Alembic migration:

```sql
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
```

SQL callers (`haversine_miles(geocoded_locations.lat, geocoded_locations.lng, %s, %s)`) are identical.

---

## Schema & Alembic

### Directory structure
```
alembic/
  env.py
  versions/
    0001_initial_schema.py
alembic.ini
```

### Initial migration (`0001_initial_schema.py`)
Creates all 5 tables in PostgreSQL-native types, plus the `haversine_miles` function. Consolidates all the historical `ALTER TABLE ADD COLUMN` increments into a single clean baseline — no legacy to support.

Tables:
- `geocoded_locations` — unchanged columns; `lat REAL` → `lat FLOAT8`, `lng REAL` → `lng FLOAT8`
- `jobs` — `is_duplicate INTEGER NOT NULL DEFAULT 0` → `is_duplicate BOOLEAN NOT NULL DEFAULT FALSE`; `AUTOINCREMENT` removed (no integer PK on jobs; `key TEXT PRIMARY KEY` unchanged)
- `job_status_history` — `id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY`
- `runs` — `id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY`
- `settings` — `id INTEGER PRIMARY KEY CHECK (id = 1)` unchanged; boolean columns use `BOOLEAN`

### Future migrations
Standard Alembic workflow:
```bash
alembic revision --autogenerate -m "add users table"
alembic upgrade head
```

The hand-written `_add_column_if_missing`, `_migrate_jobs_table`, and `_migrate_jobs_location_fk` functions in `db.py` are deleted entirely.

### Startup
`docker-entrypoint.sh` runs `alembic upgrade head` before starting uvicorn. Safe to run on every container start (no-op when already at head).

---

## Docker & Deployment

### `docker-compose.yml` (dev)
Add `postgres:17` service alongside `careerspyder`. CareerSpyder depends on it with `condition: service_healthy`.

```yaml
postgres:
  image: postgres:17
  environment:
    POSTGRES_DB: careerspyder
    POSTGRES_USER: careerspyder
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-dev}
  volumes:
    - ./data/postgres:/var/lib/postgresql/data
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U careerspyder"]
    interval: 5s
    retries: 5

careerspyder:
  depends_on:
    postgres:
      condition: service_healthy
  environment:
    DATABASE_URL: postgresql://careerspyder:${POSTGRES_PASSWORD:-dev}@postgres:5432/careerspyder
    # CAREERSPYDER_DB_PATH removed
```

The `./data` bind mount now holds PostgreSQL data; the SQLite `state.db` file is no longer written.

### `docker-compose.prod.yml`
Same pattern: `postgres:17` with `careerspyder_pgdata` named volume. No default password — `${POSTGRES_PASSWORD}` required.

### `Dockerfile`
No structural changes. `alembic` installs as a runtime dep via `pip install .`. The `CAREERSPYDER_DB_PATH` env var reference and any `/app/data/state.db` path references are removed.

### `.env.example`
Replace `CAREERSPYDER_DB_PATH` with `DATABASE_URL` and add `POSTGRES_PASSWORD`.

---

## Testing Strategy

### Fixture replacement
`conftest.py` `tmp_db_path` fixture → `pg_conn` fixture using `pytest-postgresql`:
- Spawns an isolated temporary PostgreSQL process per test session
- Creates and drops a fresh database per test function
- Runs `alembic upgrade head` against the temp database before handing back the connection
- Works in CI without a running PostgreSQL sidecar (uses `pg_ctl` bundled by the fixture)

### `test_db.py` changes
**Deleted tests** (tested SQLite-specific inline migration logic, not applicable to Alembic):
- `test_init_db_migrates_a_legacy_jobs_table_to_add_the_location_fk`
- `test_init_db_adds_new_columns_to_a_pre_existing_database`
- `test_init_db_adds_new_columns_to_an_existing_jobs_table`
- `test_init_db_adds_location_override_column`
- `test_init_db_enables_wal_mode_and_busy_timeout`

**Updated tests:**
- `test_init_db_creates_geocoded_locations_table_and_enables_fk_pragma` → replace `PRAGMA` assertions with `information_schema.tables` check
- `test_init_db_creates_job_status_history_table` → same
- `test_fk_enforcement_rejects_a_job_location_with_no_geocoded_locations_row` → replace `sqlite3.IntegrityError` with `psycopg.errors.ForeignKeyViolation`
- All `import sqlite3` inside test bodies → `import psycopg`
- All `conn.execute("PRAGMA …")` assertions → removed or replaced

**New negative tests:**
- `test_init_db_raises_on_bad_dsn` — `OperationalError` on invalid connection string
- `test_fk_violation_raises_psycopg_error` — FK enforcement is now `psycopg.errors.ForeignKeyViolation`
- `test_save_jobs_on_conflict_do_nothing_for_duplicate_key` — duplicate key is silently ignored
- `test_start_run_returns_integer_id_via_returning` — confirms `RETURNING id` path

**Positive tests that run unchanged** (all business logic: save/list/filter/reconcile/geocode/status/duplicate/haversine/etc.) — these exercise the `db.py` public API and will pass without modification once the SQL dialect is updated.

### CI (`.github/workflows/`)
Add PostgreSQL service container to the test job:
```yaml
services:
  postgres:
    image: postgres:17
    env:
      POSTGRES_DB: test
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
    options: >-
      --health-cmd pg_isready
      --health-interval 5s
      --health-retries 5
```

---

## Dependencies

### Runtime additions (`pyproject.toml` `[project]` dependencies)
```
psycopg[pool]>=3.2
alembic>=1.16
```

### Dev additions (`[project.optional-dependencies] dev`)
```
pytest-postgresql>=7.0
```

`sqlite3` is stdlib and simply goes unused — no removal needed.

---

## Version & Docs

- **Version:** `0.65.1` → `0.66.0` (minor bump; backward-incompatible infra change)
- **CHANGELOG.md:** New `0.66.0` section: PostgreSQL replaces SQLite, `DATABASE_URL` replaces `CAREERSPYDER_DB_PATH`, Alembic introduced, docker-compose gains postgres service
- **README.md:** Update setup section — PostgreSQL connection string instead of SQLite path; note the postgres container requirement
- **AGENTS.md:** Update DB layer description to psycopg3 + Alembic and new test fixture
- **`.env.example`:** Replace `CAREERSPYDER_DB_PATH` with `DATABASE_URL` and `POSTGRES_PASSWORD`

---

## Out of Scope

- Async database access (save for a later iteration)
- Data migration from existing SQLite databases
- Authentication / user accounts (issue #31 — builds on this)
- ORM introduction (raw SQL retained throughout)
