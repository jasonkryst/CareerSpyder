# Security Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every High and Medium finding (and the actionable Lows) from the 2026-09-27 security audit.

**Architecture:** Four independently shippable phases, one branch + PR each:
**Phase 1 — tenant isolation** (jobs become owned by `(user_id, key)`; every job
read/write, the scrape pipeline, run-now and import are scoped to the owner),
**Phase 2 — auth & sessions** (fail-closed config, reset links never built from
the request, revocable sessions, non-blocking auth handlers),
**Phase 3 — outbound requests** (SSRF guard pins validated IPs, browser guard
walks redirect chains itself, URL checker goes through the guard, SMTP verifies
TLS), **Phase 4 — hardening & docs**. Phases are ordered by risk; each leaves
`master` releasable.

**Tech Stack:** Python 3.14, FastAPI/Starlette, psycopg 3 + Alembic (Postgres 17), Playwright (Chromium), `requests`/urllib3 2.x, bcrypt 5.x, pytest.

**Spec:** [`docs/audits/2026-09-27-security-audit.md`](../../audits/2026-09-27-security-audit.md) — finding IDs (H1…L8) below refer to it.

## Global Constraints

- `SMTP_PASSWORD` is a container env var only — never persisted, never in a pydantic model, never rendered.
- No live network calls and no real browser in tests, **except** under `tests/web/e2e/`.
- Adapters keep the `fetch(source, **injectable_io) -> list[Job]` shape.
- Digest email is sent only if a run has ≥1 new job or ≥1 failed source; `build_digest` returns `None` otherwise.
- One source failing must never abort the others (per-source `try/except` in `orchestrator.run_once`).
- Scraped/user text must stay escaped in HTML; `app/digest.py` escapes by hand.
- `SecurityHeadersMiddleware` stays on every response; don't tighten the CSP's `'unsafe-inline'` here.
- Routes turn `KeyError` from a lookup-by-id into `HTTPException(404)`.
- Blocking work (bcrypt, SMTP, adapters) never runs inline on the event loop inside `async def`.
- DB helper convention: `user_id` is the **second positional parameter** (`get_source(conn, user_id, source_id)`), matching existing helpers.
- `ruff check app tests` (includes flake8-bandit `S`) and `mypy` must pass; run `pytest -q` before every commit.
- Tests need Postgres. Locally: `PGTEST_HOST=localhost PGTEST_PORT=15432 PGTEST_USER=cs PGTEST_PASSWORD=testpass pytest -q` (the `cs-test-pg` container).
- Each phase = its own branch off `master`, bumps `pyproject.toml` version, adds a `CHANGELOG.md` entry, opens a PR, and **stops for the user to review and merge**.

| Phase | Branch | Version |
|---|---|---|
| 1 | `fix/security-tenant-isolation` | 1.5.0 |
| 2 | `fix/security-auth-hardening` | 1.6.0 |
| 3 | `fix/security-outbound-requests` | 1.7.0 |
| 4 | `chore/security-hardening-docs` | 1.7.1 |

## Review Focus

1. **Upgrading a live database** whose `jobs` rows have `user_id IS NULL` (single-user install that never seeded an admin before 0003) — expected: rows are assigned to the first admin, not dropped or crashing the migration. *(Task 1, `test_migration_0003_assigns_ownerless_jobs_to_the_first_admin`)*
2. **Sessions issued before Phase 2 deploys** (cookie has `user_id` but no `pw_fp`) — expected: a clean redirect to `/login`, never a 500. *(Task 6, `test_legacy_session_without_fingerprint_is_logged_out`)*
3. **Two users tracking the same board** (identical job keys), viewed together by the admin — expected: two rows, each with its *own* status history, and no action controls on the row the admin doesn't own. *(Task 2, `test_admin_view_keeps_each_owners_history_separate`)*
4. **Legitimate same-site redirects in browser adapters** (http→https, `/careers`→`/careers/`) — expected: the page still renders with the final response. *(Task 11, `test_allowed_redirect_chain_is_followed_and_fulfilled` + e2e test)*
5. **SMTP relay with a self-signed certificate** (common in home labs) — expected: the digest send fails with a logged `certificate verify failed`, the run itself completes and is recorded. *(Task 12, `test_run_completes_when_smtp_certificate_is_rejected`)*

---

# Phase 1 — Tenant isolation (H1, H2, H3, M3, M4, L2)

Branch: `git switch -c fix/security-tenant-isolation origin/master`

### Task 1: Jobs are owned by `(user_id, key)` — schema, DB helpers, all callers

Fixes H1, H2 (core), H3.

**Files:**
- Create: `alembic/versions/0003_tenant_scoped_jobs.py`
- Modify: `app/db.py` (`get_new_jobs`, `save_jobs`, `refresh_job_urls`, `clear_jobs`, `reconcile_jobs`, `mark_job_removed`, `set_job_status`, `set_location_override`, `clear_location_override`, `get_job_statuses`, `get_emailed_keys`, `set_job_duplicate`, `clear_job_duplicate`, `mark_emailed`, `get_job_status_history`, `list_jobs`)
- Modify: `app/checker.py`, `app/orchestrator.py`, `app/scheduler.py`, `app/web/routes_jobs.py`, `app/web/routes_settings.py:162-172`
- Modify: `tests/conftest.py` (add `owner_id_for`), every test calling the changed helpers (codemod, Step 5)
- Test: `tests/test_tenant_isolation_db.py` (new), `tests/web/test_tenant_isolation.py` (new), `tests/test_migrations.py` (new)

**Interfaces:**
- Produces (all later tasks rely on these exact signatures):
  - `db.get_new_jobs(conn, user_id: str, jobs: list[Job]) -> list[Job]`
  - `db.save_jobs(conn, jobs: list[Job], run_id: int, *, user_id: str) -> None`
  - `db.refresh_job_urls(conn, user_id: str, jobs: list[Job]) -> int`
  - `db.clear_jobs(conn, user_id: str) -> None`
  - `db.reconcile_jobs(conn, user_id: str, configured_source_ids: set[str], succeeded_source_ids: set[str], found_jobs: list[Job]) -> None`
  - `db.mark_job_removed(conn, user_id: str, key: str) -> None` (raises `KeyError`)
  - `db.set_job_status(conn, user_id: str, key: str, status: str | None) -> None` (raises `KeyError`)
  - `db.set_location_override(conn, user_id: str, key: str, location: str, display_name, city, region, country, lat, lng, provider) -> None` (raises `KeyError`)
  - `db.clear_location_override(conn, user_id: str, key: str) -> None` (raises `KeyError`)
  - `db.set_job_duplicate(conn, user_id: str, key: str, duplicate_of: str | None = None) -> None`, `db.clear_job_duplicate(conn, user_id: str, key: str) -> None` (raise `KeyError`)
  - `db.get_job_statuses(conn, user_id: str, keys: list[str]) -> dict[str, str | None]`
  - `db.get_emailed_keys(conn, user_id: str, keys: list[str]) -> set[str]`
  - `db.mark_emailed(conn, user_id: str, keys: list[str]) -> None`
  - `db.get_job_status_history(conn, owned_keys: list[tuple[str, str]]) -> dict[tuple[str, str], list[dict]]` — pairs are `(user_id, key)`
  - `db.list_jobs(...)` rows gain `"user_id": str`
  - `orchestrator.run_once(conn, sources, geocoder=None, *, user_id: str) -> RunSummary`
  - `scheduler._record_empty_run(conn, user_id: str | None = None) -> None`
  - `checker.check_job_urls(conn, http_head=..., user_id=None, ...)` — updates by `(user_id, key)`
  - `tests.conftest.owner_id_for(conn) -> str`

- [ ] **Step 1: Write the failing DB-level isolation tests**

Create `tests/test_tenant_isolation_db.py`:

```python
import pytest

from app import db, orchestrator
from app.models import Job

KEY = "greenhouse:1"


def _job(key: str = KEY, source_id: str = "src") -> Job:
    return Job(key=key, title="Engineer", url=f"https://boards.example/{key}",
               source_name="Acme", source_id=source_id)


@pytest.fixture
def two_users(pg_conn):
    alice = db.create_user(pg_conn, "alice", "alice@test.local", "x")
    bob = db.create_user(pg_conn, "bob", "bob@test.local", "x")
    return alice["id"], bob["id"]


def _save(conn, user_id: str, job: Job | None = None) -> None:
    db.save_jobs(conn, [job or _job()], db.start_run(conn, user_id=user_id), user_id=user_id)


def test_same_job_key_is_saved_once_per_user(pg_conn, two_users):
    alice, bob = two_users
    _save(pg_conn, alice)
    assert db.get_new_jobs(pg_conn, bob, [_job()]) == [_job()]
    _save(pg_conn, bob)
    count = pg_conn.execute("SELECT COUNT(*) FROM jobs WHERE key = %s", (KEY,)).fetchone()[0]
    assert count == 2


def test_reconcile_for_one_user_leaves_other_users_jobs_active(pg_conn, two_users):
    alice, bob = two_users
    _save(pg_conn, bob, _job(source_id="src-bob"))
    db.reconcile_jobs(pg_conn, alice, set(), set(), [])
    removed_at = pg_conn.execute("SELECT removed_at FROM jobs WHERE user_id = %s", (bob,)).fetchone()[0]
    assert removed_at is None


def test_run_once_for_one_user_leaves_other_users_jobs_active(pg_conn, two_users, monkeypatch):
    alice, bob = two_users
    monkeypatch.setattr(orchestrator, "geocode_pending", lambda *args, **kwargs: None)
    _save(pg_conn, bob, _job(source_id="src-bob"))
    orchestrator.run_once(pg_conn, [], user_id=alice)
    removed_at = pg_conn.execute("SELECT removed_at FROM jobs WHERE user_id = %s", (bob,)).fetchone()[0]
    assert removed_at is None


@pytest.mark.parametrize("mutate", [
    lambda conn, uid: db.mark_job_removed(conn, uid, KEY),
    lambda conn, uid: db.set_job_status(conn, uid, KEY, "applied"),
    lambda conn, uid: db.set_job_duplicate(conn, uid, KEY),
    lambda conn, uid: db.clear_job_duplicate(conn, uid, KEY),
    lambda conn, uid: db.clear_location_override(conn, uid, KEY),
], ids=["remove", "status", "dup", "undup", "clear-override"])
def test_job_mutations_by_a_non_owner_raise_keyerror(pg_conn, two_users, mutate):
    alice, bob = two_users
    _save(pg_conn, alice)
    with pytest.raises(KeyError):
        mutate(pg_conn, bob)
    row = pg_conn.execute(
        "SELECT status, removed_at, is_duplicate FROM jobs WHERE user_id = %s AND key = %s", (alice, KEY),
    ).fetchone()
    assert row == (None, None, False)


def test_clear_jobs_only_deletes_the_callers_jobs(pg_conn, two_users):
    alice, bob = two_users
    _save(pg_conn, alice)
    _save(pg_conn, bob)
    db.clear_jobs(pg_conn, bob)
    owners = [r[0] for r in pg_conn.execute("SELECT user_id::text FROM jobs").fetchall()]
    assert owners == [alice]


def test_mark_emailed_only_touches_the_callers_copy_of_a_shared_key(pg_conn, two_users):
    alice, bob = two_users
    _save(pg_conn, alice)
    _save(pg_conn, bob)
    db.mark_emailed(pg_conn, alice, [KEY])
    bob_emailed = pg_conn.execute(
        "SELECT emailed_at FROM jobs WHERE user_id = %s AND key = %s", (bob, KEY),
    ).fetchone()[0]
    assert bob_emailed is None


def test_status_history_is_kept_per_owner(pg_conn, two_users):
    alice, bob = two_users
    _save(pg_conn, alice)
    _save(pg_conn, bob)
    db.set_job_status(pg_conn, alice, KEY, "applied")
    db.set_job_status(pg_conn, bob, KEY, "rejected")
    history = db.get_job_status_history(pg_conn, [(alice, KEY), (bob, KEY)])
    assert [e["status"] for e in history[(alice, KEY)]] == ["applied"]
    assert [e["status"] for e in history[(bob, KEY)]] == ["rejected"]
```

- [ ] **Step 2: Write the failing route-level IDOR tests**

Create `tests/web/test_tenant_isolation.py`:

```python
import psycopg
import pytest

from app import db
from app.models import Job

KEY = "greenhouse:111"


def _seed_admin_job(pg_dsn) -> str:
    with psycopg.connect(pg_dsn) as conn:
        admin = db.get_user_by_username(conn, "admin")
        job = Job(key=KEY, title="T", url="https://ex.test/1", source_name="S", source_id="src-a")
        db.save_jobs(conn, [job], db.start_run(conn, user_id=admin["id"]), user_id=admin["id"])
        return admin["id"]


def _admin_row(pg_dsn, admin_id: str):
    with psycopg.connect(pg_dsn) as conn:
        return conn.execute(
            "SELECT status, removed_at, is_duplicate, location_override FROM jobs "
            "WHERE user_id = %s AND key = %s", (admin_id, KEY),
        ).fetchone()


@pytest.mark.parametrize("path,data", [
    ("/jobs/remove", {"key": KEY}),
    ("/jobs/status", {"key": KEY, "status": "applied"}),
    ("/jobs/duplicate", {"key": KEY}),
    ("/jobs/duplicate", {"key": KEY, "action": "clear"}),
    ("/jobs/location-override", {"key": KEY, "location": ""}),
], ids=["remove", "status", "dup", "undup", "clear-override"])
def test_member_cannot_mutate_another_users_job(member_client, pg_dsn, path, data):
    admin_id = _seed_admin_job(pg_dsn)
    before = _admin_row(pg_dsn, admin_id)
    resp = member_client.post(path, data=data, headers={"Accept": "application/json"})
    assert resp.status_code == 404
    assert _admin_row(pg_dsn, admin_id) == before


def test_member_clear_cache_leaves_other_users_jobs(member_client, pg_dsn):
    admin_id = _seed_admin_job(pg_dsn)
    resp = member_client.post("/settings/data/clear-cache", follow_redirects=False)
    assert resp.status_code == 303
    assert _admin_row(pg_dsn, admin_id) is not None
```

- [ ] **Step 3: Write the failing migration test** (Review Focus #1)

Create `tests/test_migrations.py`:

```python
import psycopg
from alembic.config import Config

from alembic import command
from app import db


def _cfg(dsn: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", dsn.replace("postgresql://", "postgresql+psycopg://", 1))
    return cfg


def test_migration_0003_assigns_ownerless_jobs_to_the_first_admin(pg_dsn):
    cfg = _cfg(pg_dsn)
    command.downgrade(cfg, "0002")
    with psycopg.connect(pg_dsn) as conn:
        admin = db.create_user(conn, "admin", "admin@test.local", "x", role="admin")
        conn.execute(
            "INSERT INTO jobs (key, title, url, source_name, first_seen_at) "
            "VALUES ('lever:legacy', 'T', 'https://x.test', 'S', '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()
    command.upgrade(cfg, "head")
    with psycopg.connect(pg_dsn) as conn:
        owner = conn.execute("SELECT user_id::text FROM jobs WHERE key = 'lever:legacy'").fetchone()[0]
    assert owner == admin["id"]
```

- [ ] **Step 4: Run the new tests — verify they fail**

Run: `pytest tests/test_tenant_isolation_db.py tests/web/test_tenant_isolation.py tests/test_migrations.py -v`
Expected: FAIL — `TypeError` on the new helper signatures (e.g. `save_jobs() got an unexpected keyword argument` / wrong arg counts), `status_code == 303` instead of 404 for the IDOR tests, and `downgrade` to `0002` failing because revision `0003` doesn't exist yet (`Can't locate revision`… or no-op then `owner` mismatch).

- [ ] **Step 5: Add the migration**

Create `alembic/versions/0003_tenant_scoped_jobs.py`:

```python
"""jobs are owned per user: composite (user_id, key) primary key

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rows left ownerless (single-user install upgraded before an admin was
    # seeded) go to the earliest admin; anything still ownerless has no one
    # who could ever see it.
    op.execute(
        "UPDATE jobs SET user_id = ("
        "SELECT id FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1"
        ") WHERE user_id IS NULL"
    )
    op.execute("DELETE FROM jobs WHERE user_id IS NULL")
    op.execute(
        "UPDATE job_status_history h SET user_id = j.user_id FROM jobs j "
        "WHERE h.user_id IS NULL AND h.job_key = j.key"
    )
    op.execute("DELETE FROM job_status_history WHERE user_id IS NULL")
    op.execute("ALTER TABLE jobs ALTER COLUMN user_id SET NOT NULL")
    op.execute("ALTER TABLE job_status_history ALTER COLUMN user_id SET NOT NULL")
    op.execute("ALTER TABLE jobs DROP CONSTRAINT jobs_pkey")
    op.execute("ALTER TABLE jobs ADD PRIMARY KEY (user_id, key)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_status_history_user_key "
        "ON job_status_history (user_id, job_key)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_job_status_history_user_key")
    op.execute("ALTER TABLE jobs DROP CONSTRAINT jobs_pkey")
    # Collapse per-user copies back to one row per key, keeping the oldest.
    op.execute(
        "DELETE FROM jobs a USING jobs b "
        "WHERE a.key = b.key AND (a.first_seen_at, a.ctid) > (b.first_seen_at, b.ctid)"
    )
    op.execute("ALTER TABLE jobs ADD PRIMARY KEY (key)")
    op.execute("ALTER TABLE jobs ALTER COLUMN user_id DROP NOT NULL")
    op.execute("ALTER TABLE job_status_history ALTER COLUMN user_id DROP NOT NULL")
```

- [ ] **Step 6: Scope the DB helpers in `app/db.py`**

Replace each function body as follows (keep surrounding code as-is):

```python
def get_new_jobs(conn: psycopg.Connection, user_id: str, jobs: list[Job]) -> list[Job]:
    if not jobs:
        return []
    placeholders = ",".join(["%s"] * len(jobs))
    keys = [j.key for j in jobs]
    rows = conn.execute(
        f"SELECT key FROM jobs WHERE user_id = %s AND key IN ({placeholders})", [user_id, *keys],
    ).fetchall()
    known = {r[0] for r in rows}
    return [j for j in jobs if j.key not in known]
```

In `save_jobs`: change the signature to `def save_jobs(conn: psycopg.Connection, jobs: list[Job], run_id: int, *, user_id: str) -> None:` and the conflict clause from `ON CONFLICT DO NOTHING` (the `INSERT INTO jobs` one — leave the `geocoded_locations` one alone) to `ON CONFLICT (user_id, key) DO NOTHING`.

In `refresh_job_urls`: signature `def refresh_job_urls(conn: psycopg.Connection, user_id: str, jobs: list[Job]) -> int:`; statement and params become:

```python
        cur.executemany(
            "UPDATE jobs SET url = %s WHERE user_id = %s AND key = %s AND url IS DISTINCT FROM %s",
            [(j.url, user_id, j.key, j.url) for j in jobs],
        )
```

```python
def clear_jobs(conn: psycopg.Connection, user_id: str) -> None:
    conn.execute("DELETE FROM jobs WHERE user_id = %s", (user_id,))
    conn.commit()
```

```python
def reconcile_jobs(conn: psycopg.Connection, user_id: str, configured_source_ids: set[str],
                    succeeded_source_ids: set[str], found_jobs: list[Job]) -> None:
    found_keys = {j.key for j in found_jobs}
    now = _now()

    active_rows = conn.execute(
        "SELECT key, source_id FROM jobs "
        "WHERE user_id = %s AND removed_at IS NULL AND source_id IS NOT NULL",
        (user_id,),
    ).fetchall()
    deleted_source_ids = {sid for _, sid in active_rows if sid not in configured_source_ids}

    remove_keys = [
        key for key, sid in active_rows
        if (sid in succeeded_source_ids and key not in found_keys) or sid in deleted_source_ids
    ]
    if remove_keys:
        placeholders = ",".join(["%s"] * len(remove_keys))
        conn.execute(
            f"UPDATE jobs SET removed_at = %s WHERE user_id = %s AND key IN ({placeholders})",
            [now, user_id, *remove_keys],
        )

    removed_rows = conn.execute(
        "SELECT key FROM jobs WHERE user_id = %s AND removed_at IS NOT NULL", (user_id,),
    ).fetchall()
    reactivate_keys = [key for (key,) in removed_rows if key in found_keys]
    if reactivate_keys:
        placeholders = ",".join(["%s"] * len(reactivate_keys))
        # Reset emailed_at so reactivated jobs are picked up by the next digest run.
        conn.execute(
            f"UPDATE jobs SET removed_at = NULL, emailed_at = NULL "
            f"WHERE user_id = %s AND key IN ({placeholders})",
            [user_id, *reactivate_keys],
        )

    conn.commit()


def mark_job_removed(conn: psycopg.Connection, user_id: str, key: str) -> None:
    exists = conn.execute(
        "SELECT 1 FROM jobs WHERE user_id = %s AND key = %s", (user_id, key),
    ).fetchone()
    if exists is None:
        raise KeyError(key)
    conn.execute(
        "UPDATE jobs SET removed_at = %s WHERE user_id = %s AND key = %s AND removed_at IS NULL",
        (_now(), user_id, key),
    )
    conn.commit()


def set_job_status(conn: psycopg.Connection, user_id: str, key: str, status: str | None) -> None:
    now = _now()
    cur = conn.execute(
        "UPDATE jobs SET status = %s WHERE user_id = %s AND key = %s", (status, user_id, key),
    )
    if cur.rowcount == 0:
        raise KeyError(key)
    conn.execute(
        "INSERT INTO job_status_history (user_id, job_key, status, changed_at) VALUES (%s, %s, %s, %s)",
        (user_id, key, status, now),
    )
    conn.commit()
```

In `set_location_override`: add `user_id: str` as the second parameter; the existence check becomes `conn.execute("SELECT key FROM jobs WHERE user_id = %s AND key = %s", (user_id, key))` and the final update `conn.execute("UPDATE jobs SET location_override = %s WHERE user_id = %s AND key = %s", (location, user_id, key))`. The shared `geocoded_locations` upsert is unchanged.

```python
def clear_location_override(conn: psycopg.Connection, user_id: str, key: str) -> None:
    cur = conn.execute(
        "UPDATE jobs SET location_override = NULL WHERE user_id = %s AND key = %s", (user_id, key),
    )
    if cur.rowcount == 0:
        raise KeyError(key)
    conn.commit()


def get_job_statuses(conn: psycopg.Connection, user_id: str, keys: list[str]) -> dict[str, str | None]:
    if not keys:
        return {}
    placeholders = ",".join(["%s"] * len(keys))
    rows = conn.execute(
        f"SELECT key, status FROM jobs WHERE user_id = %s AND key IN ({placeholders})",
        [user_id, *keys],
    ).fetchall()
    return {key: status for key, status in rows}


def get_emailed_keys(conn: psycopg.Connection, user_id: str, keys: list[str]) -> set[str]:
    if not keys:
        return set()
    placeholders = ",".join(["%s"] * len(keys))
    rows = conn.execute(
        f"SELECT key FROM jobs WHERE user_id = %s AND key IN ({placeholders}) "
        f"AND emailed_at IS NOT NULL",
        [user_id, *keys],
    ).fetchall()
    return {r[0] for r in rows}


def set_job_duplicate(conn: psycopg.Connection, user_id: str, key: str,
                      duplicate_of: str | None = None) -> None:
    cur = conn.execute(
        "UPDATE jobs SET is_duplicate = TRUE, duplicate_of = %s WHERE user_id = %s AND key = %s",
        (duplicate_of, user_id, key),
    )
    if cur.rowcount == 0:
        raise KeyError(key)
    conn.commit()


def clear_job_duplicate(conn: psycopg.Connection, user_id: str, key: str) -> None:
    cur = conn.execute(
        "UPDATE jobs SET is_duplicate = FALSE, duplicate_of = NULL WHERE user_id = %s AND key = %s",
        (user_id, key),
    )
    if cur.rowcount == 0:
        raise KeyError(key)
    conn.commit()


def mark_emailed(conn: psycopg.Connection, user_id: str, keys: list[str]) -> None:
    if not keys:
        return
    now = _now()
    placeholders = ",".join(["%s"] * len(keys))
    conn.execute(
        f"UPDATE jobs SET emailed_at = %s WHERE user_id = %s AND key IN ({placeholders})",
        [now, user_id, *keys],
    )
    conn.commit()


def get_job_status_history(
    conn: psycopg.Connection, owned_keys: list[tuple[str, str]],
) -> dict[tuple[str, str], list[dict]]:
    """History for (user_id, key) pairs -- the same key can belong to several users."""
    if not owned_keys:
        return {}
    placeholders = ",".join(["(%s::uuid, %s)"] * len(owned_keys))
    params = [value for pair in owned_keys for value in pair]
    rows = conn.execute(
        f"SELECT user_id::text, job_key, status, changed_at FROM job_status_history "
        f"WHERE (user_id, job_key) IN ({placeholders}) ORDER BY changed_at DESC, id DESC",
        params,
    ).fetchall()
    history: dict[tuple[str, str], list[dict]] = {}
    for user_id, job_key, status, changed_at in rows:
        history.setdefault((user_id, job_key), []).append({"status": status, "changed_at": changed_at})
    return history
```

(Before replacing `mark_emailed`/`get_emailed_keys`/`set_job_duplicate`/`clear_job_duplicate`, read their current bodies and keep any behavior not shown above, e.g. early returns or commit placement.)

In `list_jobs`: append `, jobs.user_id::text` to the SELECT list (after `users.username`) and `"user_id": r[19],` to the row dict.

- [ ] **Step 7: Update `app/checker.py` to update by `(user_id, key)`**

Replace the two SELECTs and the update block:

```python
    if user_id is not None:
        rows = conn.execute(
            "SELECT user_id::text, key, url FROM jobs WHERE removed_at IS NULL AND user_id = %s",
            (user_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT user_id::text, key, url FROM jobs WHERE removed_at IS NULL"
        ).fetchall()
```

```python
    removed: list[tuple[str, str]] = []
    if rows:
        executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="url-check")
        futures = {executor.submit(_is_removed, key, url): (owner, key) for owner, key, url in rows}
        done, not_done = wait(futures, timeout=deadline_s)
        # Don't block on stragglers: queued checks are cancelled, in-flight
        # ones finish on their own (bounded by the per-request timeout).
        executor.shutdown(wait=False, cancel_futures=True)
        removed = [futures[f] for f in done if f.result()]
        if not_done:
            logger.warning(
                "URL check deadline (%.0fs) reached; %d of %d URLs left unchecked this pass",
                deadline_s, len(not_done), len(rows),
            )

    if removed:
        now = datetime.now(UTC).isoformat()
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE jobs SET removed_at = %s WHERE user_id = %s AND key = %s",
                [(now, owner, key) for owner, key in removed],
            )
        conn.commit()

    return len(removed)
```

- [ ] **Step 8: Update the pipeline callers**

`app/orchestrator.py` — signature and the scoped calls:

```python
def run_once(
    conn: psycopg.Connection, sources: list[SourceConfig],
    geocoder: Geocoder | None = None, *, user_id: str,
) -> RunSummary:
```

```python
        new_jobs = db.get_new_jobs(conn, user_id, deduped_jobs)
        db.save_jobs(conn, new_jobs, run_id, user_id=user_id)
        ...
        db.refresh_job_urls(conn, user_id, deduped_raw_jobs)
        ...
        db.reconcile_jobs(conn, user_id, configured_source_ids, succeeded_source_ids, deduped_raw_jobs)
        ...
            url_removed_count = checker.check_job_urls(conn, user_id=user_id)
```

`app/scheduler.py` — in `_run_user`: `db.get_job_statuses(conn, user_id, [...])`, `db.get_emailed_keys(conn, user_id, [...])`, `db.mark_emailed(conn, user_id, [...])`. Add above `run_and_notify`:

```python
def _record_empty_run(conn, user_id: str | None = None) -> None:
    """Record a run row when there is nothing to scrape, so the dashboard
    still shows the scheduler fired."""
    run_id = db.start_run(conn, user_id=user_id)
    db.finish_run(conn, run_id, 0, [])
```

and replace `orchestrator.run_once(conn, [])` in `run_and_notify` with `_record_empty_run(conn)`.

`app/web/routes_jobs.py` — pass the caller's id everywhere:

```python
            db.set_job_status(conn, current_user["id"], key, status)          # /jobs/status
            db.mark_job_removed(conn, current_user["id"], key)                # /jobs/remove
            row = conn.execute(
                "SELECT removed_at FROM jobs WHERE user_id = %s AND key = %s",
                (current_user["id"], key),
            ).fetchone()                                                       # /jobs/remove JSON branch
                db.clear_job_duplicate(conn, current_user["id"], key)         # /jobs/duplicate
                db.set_job_duplicate(conn, current_user["id"], key, duplicate_of)
                db.clear_location_override(conn, current_user["id"], key)     # /jobs/location-override
            db.set_location_override(conn, current_user["id"], key, location, ...)
```

and in `jobs()`:

```python
        history = db.get_job_status_history(conn, [(row["user_id"], row["key"]) for row in rows])
        for row in rows:
            ...
            row["history"] = [
                {"status_label": STATUSES.get(entry["status"], "No status"), "changed_at": entry["changed_at"]}
                for entry in history.get((row["user_id"], row["key"]), [])
            ]
```

`app/web/routes_settings.py` `clear_cache`: `db.clear_jobs(conn, current_user["id"])`.

- [ ] **Step 9: Add the test helper and codemod existing tests**

Add to `tests/conftest.py` (after `seed_admin`):

```python
def owner_id_for(conn) -> str:
    """Id of the 'admin' user, seeding one on a bare pg_conn. Jobs are owned
    per user since migration 0003, so tests that save jobs need an owner."""
    user = db.get_user_by_username(conn, "admin")
    return user["id"] if user is not None else seed_admin(conn)["id"]
```

(Deliberately not named `test_*` — test modules import it, and pytest would collect a `test_`-prefixed import as a test.)

Save this one-off script to the scratchpad (not the repo) as `codemod_owner.py` and run `python <scratchpad>/codemod_owner.py tests`:

```python
"""One-off codemod (security plan Task 1): pass the owning user's id to job
helpers in tests. Skips calls whose text already mentions user_id."""
import pathlib
import re
import sys

POSITIONAL = {
    "get_new_jobs", "mark_job_removed", "set_job_status", "set_job_duplicate",
    "clear_job_duplicate", "set_location_override", "clear_location_override",
    "get_job_statuses", "get_emailed_keys", "mark_emailed", "refresh_job_urls",
    "reconcile_jobs", "clear_jobs",
}
KEYWORD = {"save_jobs", "run_once"}
CALL = re.compile(r"\b(?:db|orchestrator)\.(" + "|".join(sorted(POSITIONAL | KEYWORD)) + r")\(")
IMPORT = "from tests.conftest import owner_id_for\n"


def _args(src: str, start: int) -> tuple[int, list[tuple[int, int]]]:
    depth, i, arg_start, spans, quote = 0, start, start, [], None
    while True:
        c = src[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                spans.append((arg_start, i))
                return i, spans
            depth -= 1
        elif c == "," and depth == 0:
            spans.append((arg_start, i))
            arg_start = i + 1
        i += 1


def rewrite(src: str) -> str:
    edits: list[tuple[int, str]] = []
    for m in CALL.finditer(src):
        close, spans = _args(src, m.end())
        if "user_id" in src[m.start():close]:
            continue
        owner = f"owner_id_for({src[spans[0][0]:spans[0][1]].strip()})"
        if m.group(1) in KEYWORD:
            last = src[spans[-1][0]:spans[-1][1]]
            if last.strip():
                edits.append((spans[-1][1], f", user_id={owner}"))
            else:  # trailing comma: insert before the closing paren
                edits.append((close, f" user_id={owner}"))
        else:
            edits.append((spans[0][1], f", {owner}"))
    for index, text in sorted(edits, reverse=True):
        src = src[:index] + text + src[index:]
    return src


def add_import(src: str) -> str:
    if IMPORT in src:
        return src
    lines = src.splitlines(keepends=True)
    last = max(i for i, line in enumerate(lines[:80]) if line.startswith(("import ", "from ")))
    if lines[last].rstrip().endswith("("):
        while not lines[last].startswith(")"):
            last += 1
    lines.insert(last + 1, IMPORT)
    return "".join(lines)


for path in pathlib.Path(sys.argv[1]).rglob("*.py"):
    if path.as_posix().endswith("tests/conftest.py"):
        continue
    src = path.read_text(encoding="utf-8")
    new = rewrite(src)
    if new != src:
        path.write_text(add_import(new), encoding="utf-8")
        print("rewrote", path)
```

Then: `ruff check --fix tests` (import ordering), and by hand update every `get_job_status_history(` call in `tests/` to pass `[(owner_id_for(conn), key), ...]` and index results by `(owner, key)` (`grep -rn "get_job_status_history" tests`).

- [ ] **Step 10: Run the full suite**

Run: `pytest -q`
Expected: all pass, including Steps 1–3. Any remaining `NotNullViolation: null value in column "user_id"` is a call the codemod skipped (its text already contained `user_id`, e.g. a nested `start_run(conn, user_id=...)`) — add `user_id=owner_id_for(conn)` by hand. A test that creates its own `"admin"` user after calling `owner_id_for` will hit a unique violation — create the user first or reuse the seeded one. Also run `ruff check app tests && mypy`.

- [ ] **Step 11: Commit**

```bash
git add alembic/versions/0003_tenant_scoped_jobs.py app/ tests/
git commit -m "fix(security): scope jobs to their owner — composite (user_id, key) PK, per-user pipeline and job routes (H1, H2, H3)"
```

---

### Task 2: Per-user filter dropdowns and a read-only admin cross-user view

Fixes L2; covers Review Focus #3.

**Files:**
- Modify: `app/db.py` (`list_job_locations`, `list_job_states`)
- Modify: `app/web/routes_jobs.py` (`jobs`, `jobs_map`)
- Modify: `app/web/templates/jobs.html` (row action controls, lines ~135-185)
- Test: `tests/web/test_tenant_isolation.py`

**Interfaces:**
- Consumes: Task 1's `list_jobs` row `"user_id"`, `get_job_status_history(conn, owned_keys)`.
- Produces: `db.list_job_locations(conn, user_id: str | None = None) -> list[str]`, `db.list_job_states(conn, user_id: str | None = None) -> list[str]`; template context key `current_user_id: str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_tenant_isolation.py`:

```python
def _seed_geocoded_admin_job(pg_dsn) -> None:
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "INSERT INTO geocoded_locations (location, display_name, region, status, lat, lng) "
            "VALUES ('Secret City, ZZ', 'Secret City, Zedland', 'Zedland', 'resolved', 1, 1)"
        )
        conn.commit()
        admin = db.get_user_by_username(conn, "admin")
        job = Job(key="lever:secret", title="T", url="https://ex.test/s", source_name="S",
                  source_id="src-a", location="Secret City, ZZ")
        db.save_jobs(conn, [job], db.start_run(conn, user_id=admin["id"]), user_id=admin["id"])


def test_member_filter_dropdowns_exclude_other_users_locations(member_client, pg_dsn):
    _seed_geocoded_admin_job(pg_dsn)
    for path in ("/jobs", "/jobs/map"):
        body = member_client.get(path).text
        assert "Secret City, Zedland" not in body
        assert "Zedland" not in body


def test_admin_filter_dropdowns_still_list_all_locations(client, pg_dsn):
    _seed_geocoded_admin_job(pg_dsn)
    assert "Secret City, Zedland" in client.get("/jobs").text


def test_admin_view_has_no_action_controls_on_other_users_rows(client, pg_dsn, member_user_id_for_admin):
    with psycopg.connect(pg_dsn) as conn:
        job = Job(key="lever:m1", title="Member Job", url="https://ex.test/m", source_name="S", source_id="src-m")
        db.save_jobs(conn, [job], db.start_run(conn, user_id=member_user_id_for_admin), user_id=member_user_id_for_admin)
    body = client.get("/jobs").text
    assert "Member Job" in body
    assert 'action="/jobs/remove"' not in body
    assert 'action="/jobs/status"' not in body


def test_admin_view_keeps_each_owners_history_separate(client, pg_dsn, admin_user_id, member_user_id_for_admin):
    with psycopg.connect(pg_dsn) as conn:
        for owner, status in ((admin_user_id, "applied"), (member_user_id_for_admin, "rejected")):
            job = Job(key="lever:shared", title="Shared", url="https://ex.test/x", source_name="S", source_id="src")
            db.save_jobs(conn, [job], db.start_run(conn, user_id=owner), user_id=owner)
            db.set_job_status(conn, owner, "lever:shared", status)
    body = client.get("/jobs").text
    assert body.count("Shared") >= 2
    assert body.count("Applied") >= 1 and body.count("Rejected") >= 1
```

Add this fixture to `tests/web/conftest.py` (a member that exists while the **admin** client is logged in — `member_client` would log the shared client out of admin):

```python
@pytest.fixture
def member_user_id_for_admin(client):
    """A member user's id, created without changing who `client` is logged in as."""
    from app import db
    from app.web.auth import hash_password
    with client.app.state.pool.connection() as conn:
        user = db.create_user(conn, "member2", "member2@test.local", hash_password("member123"))
    return user["id"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/web/test_tenant_isolation.py -v -k "dropdown or action_controls or history_separate"`
Expected: `test_member_filter_dropdowns_exclude_other_users_locations` FAILS ("Secret City, Zedland" present); `test_admin_view_has_no_action_controls_on_other_users_rows` FAILS (forms present). The history test may already pass after Task 1 — keep it as a regression guard.

- [ ] **Step 3: Implement**

`app/db.py`:

```python
def list_job_locations(conn: psycopg.Connection, user_id: str | None = None) -> list[str]:
    owner_sql, params = ("AND jobs.user_id = %s", [user_id]) if user_id is not None else ("", [])
    rows = conn.execute(
        "SELECT display_name FROM ("
        "SELECT DISTINCT gl.display_name FROM jobs "
        "JOIN geocoded_locations gl ON gl.location = jobs.location "
        f"WHERE gl.status = 'resolved' AND gl.display_name IS NOT NULL {owner_sql}"
        ") t ORDER BY LOWER(display_name)",
        params,
    ).fetchall()
    return [r[0] for r in rows]


def list_job_states(conn: psycopg.Connection, user_id: str | None = None) -> list[str]:
    owner_sql, params = ("AND jobs.user_id = %s", [user_id]) if user_id is not None else ("", [])
    rows = conn.execute(
        "SELECT region FROM ("
        "SELECT DISTINCT gl.region FROM jobs "
        "JOIN geocoded_locations gl ON gl.location = jobs.location "
        f"WHERE gl.status IN ('resolved', 'manual') AND gl.region IS NOT NULL {owner_sql}"
        ") t ORDER BY LOWER(region)",
        params,
    ).fetchall()
    return [r[0] for r in rows]
```

`app/web/routes_jobs.py`: in `jobs()` use `db.list_job_locations(conn, filter_user_id)` / `db.list_job_states(conn, filter_user_id)` and add `"current_user_id": current_user["id"],` to the template context; same two calls in `jobs_map()` with its `filter_user_id`.

`app/web/templates/jobs.html`: wrap the per-row `<form method="post" action="/jobs/remove" …>` block, the `<form method="post" action="/jobs/status" …>` block, and the row's duplicate/location-override trigger buttons in

```jinja
{% if job.user_id == current_user_id %}
  … existing controls …
{% else %}
  <span class="muted">—</span>
{% endif %}
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/web/test_tenant_isolation.py tests/web/test_jobs.py -v`
Expected: PASS. Then `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add app/db.py app/web/routes_jobs.py app/web/templates/jobs.html tests/web/
git commit -m "fix(security): per-user job filter dropdowns; admin cross-user job view is read-only (L2)"
```

---

### Task 3: Run-now and check-urls are scoped and rate-limited

Fixes M3.

**Files:**
- Modify: `app/scheduler.py` (`run_and_notify`)
- Modify: `app/web/routes_dashboard.py` (`run_now`, `check_urls`)
- Test: `tests/test_scheduler.py`, `tests/web/test_dashboard.py`

**Interfaces:**
- Consumes: `scheduler._record_empty_run(conn, user_id=None)` (Task 1), `ratelimit.check(key, max_attempts, window_seconds) -> bool`.
- Produces: `scheduler.run_and_notify(pool, tz="UTC", force=False, only_user_id: str | None = None) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduler.py`:

```python
from contextlib import contextmanager


class _FakePool:
    @contextmanager
    def connection(self):
        yield "conn"


def test_run_and_notify_only_user_id_runs_just_that_user(monkeypatch):
    from app import scheduler
    ran = []
    monkeypatch.setattr(scheduler.db, "list_all_sources_by_user", lambda conn: {"a": ["sa"], "b": ["sb"]})
    monkeypatch.setattr(scheduler, "_run_user", lambda conn, uid, sources, tz, force: ran.append((uid, sources)))
    scheduler.run_and_notify(_FakePool(), only_user_id="b")
    assert ran == [("b", ["sb"])]


def test_run_and_notify_only_user_id_without_sources_records_an_empty_run(monkeypatch):
    from app import scheduler
    recorded = []
    monkeypatch.setattr(scheduler.db, "list_all_sources_by_user", lambda conn: {"a": ["sa"]})
    monkeypatch.setattr(scheduler, "_run_user", lambda *args: pytest.fail("no sources, nothing to run"))
    monkeypatch.setattr(scheduler, "_record_empty_run", lambda conn, user_id=None: recorded.append(user_id))
    scheduler.run_and_notify(_FakePool(), only_user_id="b")
    assert recorded == ["b"]
```

(Ensure `import pytest` is at the top of the file.)

Append to `tests/web/test_dashboard.py`:

```python
def test_member_run_now_runs_only_their_own_sources(member_client, member_user_id, monkeypatch):
    calls = []
    monkeypatch.setattr("app.web.routes_dashboard.run_and_notify", lambda *a, **k: calls.append(k))
    resp = member_client.post("/run-now", follow_redirects=False)
    assert resp.status_code == 303
    assert calls == [{"force": True, "only_user_id": member_user_id}]


def test_admin_run_now_runs_everyone(client, monkeypatch):
    calls = []
    monkeypatch.setattr("app.web.routes_dashboard.run_and_notify", lambda *a, **k: calls.append(k))
    client.post("/run-now", follow_redirects=False)
    assert calls == [{"force": True, "only_user_id": None}]


def test_run_now_is_rate_limited_per_user(member_client, monkeypatch):
    calls = []
    monkeypatch.setattr("app.web.routes_dashboard.run_and_notify", lambda *a, **k: calls.append(k))
    for _ in range(3):
        member_client.post("/run-now", follow_redirects=False)
    resp = member_client.post("/run-now", follow_redirects=False)
    assert resp.status_code == 303
    assert "Too+many+runs" in resp.headers["location"]
    assert len(calls) == 3


def test_check_urls_is_rate_limited_per_user(member_client, monkeypatch):
    monkeypatch.setattr("app.web.routes_dashboard._run_url_check", lambda *a, **k: None)
    for _ in range(3):
        member_client.post("/check-urls", follow_redirects=False)
    resp = member_client.post("/check-urls", follow_redirects=False)
    assert "Too+many+runs" in resp.headers["location"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_scheduler.py tests/web/test_dashboard.py -v -k "only_user_id or run_now or rate_limited"`
Expected: FAIL — `run_and_notify() got an unexpected keyword argument 'only_user_id'`; `calls == [{"force": True}]`; no rate limiting.

- [ ] **Step 3: Implement**

`app/scheduler.py`:

```python
def run_and_notify(pool: ConnectionPool, tz: str = "UTC", force: bool = False,
                   only_user_id: str | None = None) -> None:
    """Run every user's sources (the cron job), or just `only_user_id`'s
    (a member's "Run now")."""
    with pool.connection() as conn:
        sources_by_user = db.list_all_sources_by_user(conn)
        if only_user_id is not None:
            sources_by_user = {only_user_id: sources_by_user.get(only_user_id, [])}
        if not any(sources_by_user.values()):
            _record_empty_run(conn, only_user_id)
            return
        for user_id, sources in sources_by_user.items():
            if not sources:
                continue
            try:
                _run_user(conn, user_id, sources, tz, force)
            except Exception:
                logger.exception("Failed run for user %s", user_id)
```

`app/web/routes_dashboard.py` (add imports `from app.web import ratelimit` and `from app.web.flash import flash_redirect`):

```python
# Each run launches Chromium for JS-rendered sources and holds _run_lock, so a
# member mashing the button must not be able to starve the scheduler (M3).
_RUN_LIMIT = 3
_RUN_WINDOW_S = 600
_RUN_LIMITED = "Too many runs started recently. Try again in a few minutes."


@router.post("/run-now")
def run_now(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_user),
):
    if not ratelimit.check(f"run-now:{current_user['id']}", _RUN_LIMIT, _RUN_WINDOW_S):
        return flash_redirect("/", _RUN_LIMITED)
    only_user_id = None if current_user["role"] == "admin" else current_user["id"]
    background_tasks.add_task(
        run_and_notify, request.app.state.pool, request.app.state.tz,
        force=True, only_user_id=only_user_id,
    )
    return RedirectResponse(url="/", status_code=303)
```

and at the top of `check_urls`:

```python
    if not ratelimit.check(f"check-urls:{current_user['id']}", _RUN_LIMIT, _RUN_WINDOW_S):
        return flash_redirect("/", _RUN_LIMITED)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_scheduler.py tests/web/test_dashboard.py -v` then `pytest -q`
Expected: PASS. Existing tests asserting `calls == [{"force": True}]` must be updated to include `"only_user_id": None` for the admin client.

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py app/web/routes_dashboard.py tests/
git commit -m "fix(security): members' Run now only runs their sources; rate-limit run-now and check-urls (M3)"
```

---

### Task 4: Source ids can't be used to overwrite another user's sources

Fixes M4.

**Files:**
- Modify: `app/db.py` (`import_sources`)
- Modify: `app/web/routes_sources.py` (`create_source`)
- Test: `tests/web/test_tenant_isolation.py`

**Interfaces:**
- Consumes: `seed_source` fixture (`tests/web/conftest.py`) which inserts a source for the admin.
- Produces: `db.import_sources(conn, user_id, sources) -> int` (unchanged signature; never updates rows owned by someone else).

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_tenant_isolation.py`:

```python
import json

from app.config import GreenhouseSource


def _admin_source(pg_dsn, source_id: str):
    with psycopg.connect(pg_dsn) as conn:
        admin = db.get_user_by_username(conn, "admin")
        return db.get_source(conn, admin["id"], source_id)


def _seed_admin_source(pg_dsn) -> str:
    with psycopg.connect(pg_dsn) as conn:
        admin = db.get_user_by_username(conn, "admin")
        db.add_source(conn, admin["id"], GreenhouseSource(
            id="victim000001", type="greenhouse", name="Victim", board_token="victim"))
    return "victim000001"


def test_import_with_another_users_source_id_does_not_touch_it(member_client, member_user_id, pg_dsn):
    victim_id = _seed_admin_source(pg_dsn)
    payload = json.dumps({"sources": [
        {"id": victim_id, "type": "greenhouse", "name": "Hijack", "board_token": "evil"},
    ]})
    resp = member_client.post(
        "/settings/data/import", files={"file": ("s.json", payload, "application/json")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert _admin_source(pg_dsn, victim_id).board_token == "victim"
    with psycopg.connect(pg_dsn) as conn:
        mine = db.list_sources(conn, member_user_id)
    assert [s.name for s in mine] == ["Hijack"]
    assert mine[0].id != victim_id


def test_new_source_ignores_a_submitted_id(member_client, member_user_id, pg_dsn):
    victim_id = _seed_admin_source(pg_dsn)
    resp = member_client.post("/sources/new", data={
        "id": victim_id, "type": "greenhouse", "name": "Mine", "board_token": "mine",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)
    assert resp.status_code == 303
    with psycopg.connect(pg_dsn) as conn:
        mine = db.list_sources(conn, member_user_id)
    assert len(mine) == 1 and mine[0].id != victim_id
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/web/test_tenant_isolation.py -v -k "import_with or new_source_ignores"`
Expected: FAIL — the admin's `board_token` becomes `"evil"` (import) and `/sources/new` raises a unique-violation (`psycopg.errors.UniqueViolation`, surfaced as a server exception).

- [ ] **Step 3: Implement**

`app/db.py` (add `import uuid` at the top):

```python
def import_sources(conn: psycopg.Connection, user_id: str, sources: list) -> int:
    """Upsert the importer's sources; returns count of upserted rows.

    A source id already owned by a different user gets a fresh id instead --
    ids travel in shared export files, and an import must never rewrite
    someone else's source (audit M4)."""
    count = 0
    for source in sources:
        owner = conn.execute("SELECT user_id::text FROM sources WHERE id = %s", (source.id,)).fetchone()
        if owner is not None and owner[0] != str(user_id):
            source = source.model_copy(update={"id": uuid.uuid4().hex[:12]})
        data = source.model_dump()
        conn.execute(
            "INSERT INTO sources (id, user_id, type, name, secondary, config) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(id) DO UPDATE SET "
            "type=excluded.type, name=excluded.name, secondary=excluded.secondary, "
            "config=excluded.config, updated_at=NOW() "
            "WHERE sources.user_id = excluded.user_id",
            (source.id, user_id, source.type, source.name, source.secondary,
             json.dumps(data)),
        )
        count += 1
    conn.commit()
    return count
```

`app/web/routes_sources.py` `create_source`, right after `form = dict(...)`:

```python
    # A new source always gets a server-minted id; a submitted one could
    # collide with (and 500 on) another user's source id.
    form.pop("id", None)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/web/test_tenant_isolation.py tests/web/test_settings.py tests/web/test_source_form.py -v` then `pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/db.py app/web/routes_sources.py tests/web/test_tenant_isolation.py
git commit -m "fix(security): settings import and new-source can't overwrite another user's source (M4)"
```

### Phase 1 wrap-up

- [ ] Bump `pyproject.toml` to `1.5.0`; add a `CHANGELOG.md` entry (Security: H1, H2, H3, M3, M4, L2; note the one-time migration 0003 and that the admin's all-users job view is now read-only).
- [ ] `pytest -q && ruff check app tests && mypy`
- [ ] Commit, push, open PR "Security: tenant isolation (audit 2026-09-27 phase 1)". **Stop for review.**

---

# Phase 2 — Auth and sessions (H5, M5, M6, M7, L1, L4)

Branch: `git switch -c fix/security-auth-hardening origin/master` (after Phase 1 merges).

### Task 5: Fail-closed startup config; reset links never built from the request

Fixes H5, M6, and the `Secure`-cookie half of M5.

**Files:**
- Create: `app/web/config_checks.py`
- Modify: `app/web/main.py` (`_resolve_secret_key`, `lifespan`, `SessionMiddleware` registration)
- Modify: `app/web/routes_auth.py` (`account_recovery`), `app/web/routes_users.py` (`invite_user`)
- Modify: `tests/web/conftest.py:37`, `tests/web/e2e/conftest.py:45` (strong `SECRET_KEY`, `PUBLIC_BASE_URL`)
- Test: `tests/web/test_config_checks.py` (new), `tests/web/test_auth.py`

**Interfaces:**
- Produces: `config_checks.validate_secret_key(key: str) -> None` (raises `RuntimeError`), `config_checks.public_base_url() -> str | None`, `config_checks.session_cookie_secure(base_url: str | None) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_config_checks.py`:

```python
import secrets

import pytest
from fastapi.testclient import TestClient

from app.web.config_checks import public_base_url, session_cookie_secure, validate_secret_key


@pytest.mark.parametrize("key", [
    "", "dev-insecure-secret-change-me", "change-me-generate-a-real-secret", "change-me", "short-key",
])
def test_weak_secret_keys_are_rejected(key):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        validate_secret_key(key)


def test_a_generated_secret_key_is_accepted():
    validate_secret_key(secrets.token_hex(32))


def test_public_base_url_strips_trailing_slash_and_blank(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://jobs.example.com/")
    assert public_base_url() == "https://jobs.example.com"
    monkeypatch.setenv("PUBLIC_BASE_URL", "  ")
    assert public_base_url() is None


@pytest.mark.parametrize("base,expected", [
    ("https://jobs.example.com", True), ("http://nas.local:32600", False), (None, False),
])
def test_session_cookie_is_secure_only_for_https_deployments(base, expected):
    assert session_cookie_secure(base) is expected


def test_app_refuses_to_start_with_a_placeholder_secret_key(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "change-me-generate-a-real-secret")
    from app.web.main import app
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        with TestClient(app):
            pass
```

Append to `tests/web/test_auth.py`:

```python
def test_recovery_link_uses_public_base_url_not_the_host_header(unauthed_client, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://jobs.example.com")
    sent = []
    monkeypatch.setattr("app.web.routes_auth.emailer.send_email", lambda **kw: sent.append(kw))
    resp = unauthed_client.post(
        "/account-recovery", data={"email": "admin@test.local"}, headers={"Host": "evil.example"},
    )
    assert resp.status_code == 200
    assert len(sent) == 1
    assert "https://jobs.example.com/reset-password?token=" in sent[0]["html_body"]
    assert "evil.example" not in sent[0]["html_body"]


def test_recovery_email_is_not_sent_without_public_base_url(unauthed_client, monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    sent = []
    monkeypatch.setattr("app.web.routes_auth.emailer.send_email", lambda **kw: sent.append(kw))
    resp = unauthed_client.post("/account-recovery", data={"email": "admin@test.local"})
    assert resp.status_code == 200  # same "check your email" page -- no enumeration signal
    assert sent == []
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/web/test_config_checks.py tests/web/test_auth.py -v -k "secret or public_base or cookie or recovery_link or without_public"`
Expected: FAIL — `ModuleNotFoundError: app.web.config_checks`; recovery link contains `evil.example`; email sent without `PUBLIC_BASE_URL`.

- [ ] **Step 3: Implement**

Create `app/web/config_checks.py`:

```python
"""Startup/configuration checks that must fail closed (audit 2026-09-27 H5, M5, M6)."""
import os

# Values that are published in this repo (code default, .env.example) or
# obviously placeholders -- a session/reset-token key must never be one.
_INSECURE_SECRET_KEYS = frozenset({
    "", "dev-insecure-secret-change-me", "change-me-generate-a-real-secret", "change-me",
})
_MIN_SECRET_KEY_LENGTH = 32


def validate_secret_key(key: str) -> None:
    if key in _INSECURE_SECRET_KEYS or len(key) < _MIN_SECRET_KEY_LENGTH:
        raise RuntimeError(
            "SECRET_KEY is missing, a published placeholder, or shorter than "
            f"{_MIN_SECRET_KEY_LENGTH} characters. Generate one with: "
            'python -c "import secrets; print(secrets.token_hex(32))"'
        )


def public_base_url() -> str | None:
    """The canonical external URL, or None. Security-sensitive links (password
    reset, invites) are built from this, never from the request's Host header."""
    value = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    return value or None


def session_cookie_secure(base_url: str | None) -> bool:
    # Only mark the cookie Secure when the site is actually served over HTTPS;
    # a plain-HTTP LAN deployment would otherwise be unable to log in.
    return bool(base_url and base_url.startswith("https://"))
```

`app/web/main.py`:

```python
from app.web.config_checks import public_base_url, session_cookie_secure, validate_secret_key


def _resolve_secret_key() -> str:
    # Import-time value for SessionMiddleware; lifespan() refuses to serve
    # unless the real env value passes validate_secret_key.
    return os.environ.get("SECRET_KEY", "") or "dev-insecure-secret-change-me"
```

First lines of `lifespan`:

```python
    validate_secret_key(os.environ.get("SECRET_KEY", ""))
```

Replace the `PUBLIC_BASE_URL` warning block with:

```python
    if public_base_url() is None:
        logger.warning(
            "PUBLIC_BASE_URL is not set — password-reset emails are disabled. "
            "Set PUBLIC_BASE_URL to the canonical public URL of this instance."
        )
```

Session middleware registration:

```python
app.add_middleware(
    SessionMiddleware, secret_key=_resolve_secret_key(), max_age=7 * 24 * 3600,
    same_site="lax", https_only=session_cookie_secure(public_base_url()),
)
```

`app/web/routes_auth.py` `account_recovery` — replace the `if user_with_hash and smtp and smtp.get("smtp_host"):` block's `base_url = …` line and guard:

```python
    base_url = public_base_url()
    if base_url is None:
        logger.error(
            "Account recovery requested but PUBLIC_BASE_URL is not set; refusing to "
            "build a reset link from the request's Host header."
        )
    elif user_with_hash and smtp and smtp.get("smtp_host"):
        token = generate_reset_token(...)          # unchanged
        reset_url = base_url + f"/reset-password?token={token}"
        ...                                          # unchanged send
```

(import `from app.web.config_checks import public_base_url`.)

`app/web/routes_users.py` `invite_user`: `base = public_base_url() or str(request.base_url).rstrip("/")`.

Tests config: in `tests/web/conftest.py` `_make_client`, set `SECRET_KEY` to `"test-secret-key-0123456789abcdef-0123456789abcdef"` and add `monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")`; in `tests/web/e2e/conftest.py:45` set `"SECRET_KEY": "test-secret-key-e2e-0123456789abcdef-0123456789abcdef"`. `grep -rn "SECRET_KEY" tests` to catch any others.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/web/test_config_checks.py tests/web/test_auth.py tests/web/test_users.py -v` then `pytest -q`
Expected: PASS. (If an existing recovery test asserted a `http://testserver/...` link, it now passes via `PUBLIC_BASE_URL`.)

- [ ] **Step 5: Commit**

```bash
git add app/web/config_checks.py app/web/main.py app/web/routes_auth.py app/web/routes_users.py tests/
git commit -m "fix(security): refuse weak SECRET_KEY; reset links only from PUBLIC_BASE_URL; Secure session cookie on https (H5, M6, M5)"
```

---

### Task 6: Password changes and resets revoke other sessions

Fixes M5 (revocation); covers Review Focus #2.

**Files:**
- Modify: `app/web/auth.py` (`get_current_user`, `UserContextMiddleware.dispatch`, new helpers)
- Modify: `app/web/routes_auth.py` (`login`, `register`), `app/web/routes_settings.py` (`change_password`)
- Test: `tests/web/test_session_revocation.py` (new)

**Interfaces:**
- Produces: `auth.password_fingerprint(pw_hash: str) -> str`, `auth.start_session(request, user_with_hash: dict) -> None`, `auth.load_session_user(request) -> dict | None` (user dict **without** `password_hash`).

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_session_revocation.py`:

```python
from fastapi.testclient import TestClient

from app import db
from app.web.auth import generate_reset_token


def _second_browser(client) -> TestClient:
    other = TestClient(client.app)
    other.cookies.set("session", client.cookies.get("session"))
    return other


def test_changing_password_logs_out_other_sessions(member_client):
    other = _second_browser(member_client)
    assert other.get("/jobs", follow_redirects=False).status_code == 200
    resp = member_client.post("/settings/account/password", data={
        "current_password": "member123", "new_password": "newpass123", "new_password_confirm": "newpass123",
    }, follow_redirects=False)
    assert resp.status_code == 303
    stale = other.get("/jobs", follow_redirects=False)
    assert stale.status_code == 303 and stale.headers["location"] == "/login"
    assert member_client.get("/jobs", follow_redirects=False).status_code == 200


def test_password_reset_logs_out_existing_sessions(member_client, member_user_id):
    with member_client.app.state.pool.connection() as conn:
        user = db.get_user_by_id_with_hash(conn, member_user_id)
    token = generate_reset_token(member_client.app.state.secret_key, user["id"], user["email"], user["password_hash"])
    anon = TestClient(member_client.app)
    anon.post("/reset-password", data={"token": token, "password": "resetpass1", "password_confirm": "resetpass1"})
    resp = member_client.get("/jobs", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/login"


def test_legacy_session_without_fingerprint_is_logged_out(member_client, member_user_id, monkeypatch):
    # A cookie minted before this change carries only user_id (same encoding
    # as starlette.middleware.sessions: base64(json) signed with TimestampSigner).
    import base64
    import json

    from itsdangerous import TimestampSigner
    signer = TimestampSigner(member_client.app.state.secret_key)
    legacy = signer.sign(base64.b64encode(json.dumps({"user_id": member_user_id}).encode())).decode()
    other = TestClient(member_client.app)
    other.cookies.set("session", legacy)
    resp = other.get("/jobs", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/login"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/web/test_session_revocation.py -v`
Expected: FAIL — stale sessions still get `200`.

- [ ] **Step 3: Implement**

`app/web/auth.py`:

```python
def password_fingerprint(pw_hash: str) -> str:
    """Short digest of the stored hash. Kept in the session so any password
    change or reset invalidates every other session (audit M5)."""
    return hashlib.sha256(pw_hash.encode()).hexdigest()[:16]


def start_session(request: Request, user_with_hash: dict) -> None:
    request.session["user_id"] = user_with_hash["id"]
    request.session["pw_fp"] = password_fingerprint(user_with_hash["password_hash"])


def load_session_user(request: Request) -> dict | None:
    """The session's user (without password_hash), or None -- clearing the
    session if the user is gone, deactivated, or changed password since."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with request.app.state.pool.connection() as conn:
        user = db.get_user_by_id_with_hash(conn, user_id)
    if (
        user is None or not user["is_active"]
        or request.session.get("pw_fp") != password_fingerprint(user["password_hash"])
    ):
        request.session.clear()
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}


def get_current_user(request: Request) -> dict | None:
    """Returns the session user dict, or None if the session has no valid user."""
    return load_session_user(request)
```

`UserContextMiddleware.dispatch` body:

```python
        if not request.url.path.startswith("/static"):
            try:
                request.state.user = load_session_user(request)
            except Exception:
                logger.exception("UserContextMiddleware: failed to load session user")
                request.state.user = None
        return await call_next(request)
```

`routes_auth.login`: replace `request.session["user_id"] = user["id"]` with `start_session(request, user)` (`get_user_by_username` already returns `password_hash` — confirm by reading `db.get_user_by_username`; if it doesn't, fetch with `get_user_by_id_with_hash`).
`routes_auth.register`: replace `request.session["user_id"] = user["id"]` with

```python
    with request.app.state.pool.connection() as conn:
        start_session(request, db.get_user_by_id_with_hash(conn, user["id"]))
```

`routes_settings.change_password`, after `db.update_password(...)`:

```python
        start_session(request, db.get_user_by_id_with_hash(conn, current_user["id"]))
```

(keep it inside the same `with … as conn:` block.)

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/web/test_session_revocation.py tests/web/test_auth.py tests/web/test_settings_account.py -v` then `pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/web/auth.py app/web/routes_auth.py app/web/routes_settings.py tests/web/test_session_revocation.py
git commit -m "fix(security): bind sessions to a password fingerprint so changes/resets revoke other sessions (M5)"
```

---

### Task 7: Auth handlers don't block the event loop; rate limits; bcrypt length

Fixes M7, L1.

**Files:**
- Modify: `app/web/auth.py` (`verify_password`, new `password_too_long`, `MAX_PASSWORD_BYTES`)
- Modify: `app/web/routes_auth.py` (`login`, `account_recovery`, `reset_password`, `register`)
- Modify: `app/web/routes_settings.py` (`change_password`)
- Test: `tests/web/test_auth.py`, `tests/web/test_settings_account.py`

**Interfaces:**
- Consumes: `start_session` (Task 6), `public_base_url` (Task 5).
- Produces: `auth.MAX_PASSWORD_BYTES = 72`, `auth.password_too_long(plaintext: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_auth.py`:

```python
def test_login_with_an_overlong_password_is_a_plain_401(unauthed_client):
    resp = unauthed_client.post("/login", data={"username": "admin", "password": "x" * 100})
    assert resp.status_code == 401


def test_reset_password_post_is_rate_limited(unauthed_client):
    for _ in range(10):
        unauthed_client.post("/reset-password", data={"token": "bogus", "password": "a", "password_confirm": "a"})
    resp = unauthed_client.post("/reset-password", data={"token": "bogus", "password": "a", "password_confirm": "a"})
    assert resp.status_code == 429


def test_register_post_is_rate_limited(unauthed_client):
    for _ in range(10):
        unauthed_client.post("/register", data={"token": "bogus"})
    assert unauthed_client.post("/register", data={"token": "bogus"}).status_code == 429


def _invite_token(tc, email: str) -> str:
    """Create an invite from the seeded admin. Uses the one client's pool --
    requesting both `client` and `unauthed_client` would run the lifespan twice."""
    from app import db
    with tc.app.state.pool.connection() as conn:
        admin = db.get_user_by_username(conn, "admin")
        return str(db.create_invite(conn, email, admin["id"])["token"])


def test_register_rejects_passwords_over_72_bytes(unauthed_client):
    resp = unauthed_client.post("/register", data={
        "token": _invite_token(unauthed_client, "new@test.local"), "username": "newbie",
        "password": "é" * 40, "password_confirm": "é" * 40,   # 80 UTF-8 bytes
    })
    assert resp.status_code == 400
    assert "72 bytes" in resp.text
```

Append to `tests/web/test_settings_account.py`:

```python
def test_change_password_rejects_passwords_over_72_bytes(member_client):
    resp = member_client.post("/settings/account/password", data={
        "current_password": "member123", "new_password": "x" * 73, "new_password_confirm": "x" * 73,
    })
    assert resp.status_code == 400
    assert "72 bytes" in resp.text


def test_change_password_current_password_guess_is_rate_limited(member_client):
    for _ in range(10):
        member_client.post("/settings/account/password", data={
            "current_password": "wrong", "new_password": "newpass123", "new_password_confirm": "newpass123",
        })
    resp = member_client.post("/settings/account/password", data={
        "current_password": "wrong", "new_password": "newpass123", "new_password_confirm": "newpass123",
    })
    assert resp.status_code == 429
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/web/test_auth.py tests/web/test_settings_account.py -v -k "overlong or rate_limited or 72_bytes"`
Expected: FAIL — `ValueError: password cannot be longer than 72 bytes` (500) and no 429s.

- [ ] **Step 3: Implement**

`app/web/auth.py`:

```python
# bcrypt only hashes the first 72 bytes and bcrypt>=5 raises beyond that.
MAX_PASSWORD_BYTES = 72


def password_too_long(plaintext: str) -> bool:
    return len(plaintext.encode()) > MAX_PASSWORD_BYTES


def verify_password(plaintext: str, hashed: str) -> bool:
    if password_too_long(plaintext):
        return False
    return _bcrypt.checkpw(plaintext.encode(), hashed.encode())
```

`app/web/routes_auth.py` (imports: `from fastapi import BackgroundTasks`, `from fastapi.concurrency import run_in_threadpool`, `password_too_long`, `start_session`):

```python
_TOO_LONG = "Password must be at most 72 bytes."
# Verified against for unknown usernames so a miss costs the same bcrypt time
# as a hit -- response timing must not reveal which usernames exist.
_DUMMY_HASH = hash_password("not-a-real-password")
```

In `login`, replace the lookup/verify block:

```python
    with request.app.state.pool.connection() as conn:
        user = db.get_user_by_username(conn, username)
    stored_hash = user["password_hash"] if user is not None else _DUMMY_HASH
    password_ok = await run_in_threadpool(verify_password, password, stored_hash)
    if user is None or not user["is_active"] or not password_ok:
        return templates.TemplateResponse(... unchanged 401 ...)
    start_session(request, user)
```

`account_recovery(request: Request, background_tasks: BackgroundTasks)` — replace the inline `emailer.send_email(...)` try/except with:

```python
            background_tasks.add_task(
                _send_recovery_email, smtp, email, user_with_hash["username"], reset_url,
            )
```

and add at module level:

```python
def _send_recovery_email(smtp: dict, to: str, username: str, reset_url: str) -> None:
    """Runs after the response is sent: keeps SMTP off the event loop and makes
    known and unknown emails respond in the same time (audit M7)."""
    try:
        emailer.send_email(
            smtp_host=smtp["smtp_host"], smtp_port=smtp["smtp_port"], smtp_user=smtp["smtp_user"],
            smtp_password=os.environ.get("SMTP_PASSWORD", ""), email_from=smtp["email_from"],
            email_to=[to], subject="CareerSpyder account recovery",
            html_body=_recovery_email_html(username, reset_url),
        )
    except Exception:
        logger.exception("Failed to send recovery email to %s", to)
```

`reset_password`: first lines

```python
    if not rate_limit(request, "reset-password", max_attempts=10, window_seconds=900):
        return templates.TemplateResponse(
            request, "reset_password.html",
            {"error": "Too many attempts. Please wait a few minutes and try again."},
            status_code=429,
        )
```

then after the `len(password) < 8` check add `if password_too_long(password): return _form_error(_TOO_LONG)`, and hash off-loop:

```python
        new_hash = await run_in_threadpool(hash_password, password)
        db.update_password(conn, user["id"], new_hash)
```

`register`: first lines

```python
    if not rate_limit(request, "register", max_attempts=10, window_seconds=3600):
        return templates.TemplateResponse(
            request, "register.html",
            {"error": "Too many attempts. Please wait and try again."}, status_code=429,
        )
```

after the `len(password) < 8` check add `if password_too_long(password): return _error(_TOO_LONG)`, and compute `pw_hash = await run_in_threadpool(hash_password, password)` **before** opening the DB connection, then pass `pw_hash` to `db.create_user`.

`app/web/routes_settings.py` `change_password` (imports `from fastapi.concurrency import run_in_threadpool`, `from app.web import ratelimit`, `password_too_long`, `start_session`):

```python
    if not ratelimit.check(f"change-password:{current_user['id']}", 10, 900):
        return templates.TemplateResponse(
            request, "settings_account.html",
            {"error": "Too many attempts. Please wait a few minutes and try again."},
            status_code=429,
        )
    ...
    current_ok = user_with_hash is not None and await run_in_threadpool(
        verify_password, current_password, user_with_hash["password_hash"],
    )
    if not current_ok:
        return _error("Current password is incorrect.")
    if len(new_password) < 8:
        return _error("New password must be at least 8 characters.")
    if password_too_long(new_password):
        return _error("New password must be at most 72 bytes.")
    if new_password != new_password_confirm:
        return _error("New passwords do not match.")

    new_hash = await run_in_threadpool(hash_password, new_password)
    with request.app.state.pool.connection() as conn:
        db.update_password(conn, current_user["id"], new_hash)
        start_session(request, db.get_user_by_id_with_hash(conn, current_user["id"]))
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/web/test_auth.py tests/web/test_settings_account.py tests/web/test_ratelimit.py -v` then `pytest -q`
Expected: PASS. Existing recovery tests that monkeypatch `emailer.send_email` keep working — TestClient runs `BackgroundTasks` before returning.

- [ ] **Step 5: Commit**

```bash
git add app/web/auth.py app/web/routes_auth.py app/web/routes_settings.py tests/web/
git commit -m "fix(security): bcrypt/SMTP off the event loop, constant-time login miss, rate-limit reset/register/change-password, 72-byte cap (M7, L1)"
```

---

### Task 8: Invites are single-use under concurrency; usernames are constrained

Fixes L4.

**Files:**
- Modify: `app/db.py` (`use_invite` → `claim_invite`)
- Modify: `app/web/routes_auth.py` (`register`)
- Test: `tests/test_db.py`, `tests/web/test_auth.py`

**Interfaces:**
- Consumes: `_invite_token(tc, email) -> str` test helper in `tests/web/test_auth.py` (added in Task 7).
- Produces: `db.claim_invite(conn, token: str) -> bool` (True only for the one caller that flips `used_at`). `db.use_invite` is removed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
def test_claim_invite_succeeds_exactly_once(pg_conn):
    admin = seed_admin(pg_conn)
    invite = db.create_invite(pg_conn, "x@test.local", admin["id"])
    token = str(invite["token"])
    assert db.claim_invite(pg_conn, token) is True
    assert db.claim_invite(pg_conn, token) is False
```

(import `seed_admin` from `tests.conftest` if not already.)

Append to `tests/web/test_auth.py`:

```python
import pytest


@pytest.mark.parametrize("username", ["x" * 33, "has space", "semi;colon", "<b>"])
def test_register_rejects_bad_usernames(unauthed_client, username):
    resp = unauthed_client.post("/register", data={
        "token": _invite_token(unauthed_client, "u@test.local"), "username": username,
        "password": "goodpass1", "password_confirm": "goodpass1",
    })
    assert resp.status_code == 400
    assert "Username" in resp.text
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_db.py tests/web/test_auth.py -v -k "claim_invite or bad_usernames"`
Expected: FAIL — `AttributeError: module 'app.db' has no attribute 'claim_invite'`; bad usernames accepted (303).

- [ ] **Step 3: Implement**

`app/db.py` — replace `use_invite`:

```python
def claim_invite(conn: psycopg.Connection, token: str) -> bool:
    """Atomically mark an invite used. Returns True only for the one request
    that flipped used_at, so concurrent registrations can't share an invite."""
    cur = conn.execute(
        "UPDATE invite_tokens SET used_at = NOW() WHERE token = %s AND used_at IS NULL", (token,),
    )
    conn.commit()
    return cur.rowcount == 1
```

`app/web/routes_auth.py` (`import re`):

```python
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
```

replace the two username checks with:

```python
    if not _USERNAME_RE.match(username):
        return _error("Username must be 3–32 characters: letters, digits, '.', '_' or '-'.")
```

and in the DB block, after the uniqueness checks and **before** `db.create_user`:

```python
        if not db.claim_invite(conn, token):
            return _error("This invite link has already been used.")
```

then delete the old `db.use_invite(conn, token)` line. `grep -rn "use_invite" app tests` must return nothing.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_db.py tests/web/test_auth.py -v` then `pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/db.py app/web/routes_auth.py tests/
git commit -m "fix(security): atomic single-use invites; constrain usernames (L4)"
```

### Phase 2 wrap-up

- [ ] Bump to `1.6.0`; `CHANGELOG.md` (Security: H5, M5, M6, M7, L1, L4). Call out **breaking config**: the app refuses to start without a strong `SECRET_KEY`; reset emails require `PUBLIC_BASE_URL`; everyone is logged out once on deploy.
- [ ] Before merging: confirm production `.env` has a ≥32-char `SECRET_KEY` and `PUBLIC_BASE_URL` (Portainer host, `/opt/careerspyder`).
- [ ] `pytest -q && ruff check app tests && mypy`; push; open PR. **Stop for review.**

---

# Phase 3 — Outbound requests (H4, M1, M2, M9, L3)

Branch: `git switch -c fix/security-outbound-requests origin/master`.

### Task 9: SSRF guard blocks all non-global space and pins the validated IP

Fixes M2, L3.

**Files:**
- Modify: `app/security/ssrf_guard.py`
- Modify: `app/web/routes_sources.py` (`test_source_preview`)
- Test: `tests/security/test_ssrf_guard.py`, `tests/web/test_source_preview.py`

**Interfaces:**
- Produces: `ssrf_guard.UNSAFE_URL_MESSAGE: str`, `ssrf_guard.safe_request(method, url, *, max_redirects=5, **kwargs)` (now pinned), `ssrf_guard.safe_head(url, **kwargs)`; `UnsafeUrlError` messages no longer contain resolved IPs.

- [ ] **Step 1: Write the failing tests**

Append to `tests/security/test_ssrf_guard.py`:

```python
import socket

import pytest
import requests

from app.security import ssrf_guard
from app.security.ssrf_guard import UnsafeUrlError, _is_disallowed_ip


@pytest.mark.parametrize("ip", [
    "100.64.0.1", "100.101.102.103",        # CGNAT / Tailscale
    "64:ff9b::7f00:1",                        # NAT64 of 127.0.0.1
    "::ffff:10.0.0.1", "198.18.0.1", "192.0.0.1", "0.0.0.0", "fd00::1",
])
def test_non_global_addresses_are_blocked(ip):
    assert _is_disallowed_ip(ip) is True


@pytest.mark.parametrize("ip", ["93.184.216.34", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(ip):
    assert _is_disallowed_ip(ip) is False


def _ai(ip: str, port: int = 80):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (ip, port))]


def test_safe_get_pins_the_validated_address_against_dns_rebinding(monkeypatch):
    calls = []

    def rebinding(host, *args, **kwargs):
        calls.append(host)
        return _ai("93.184.216.34") if len(calls) == 1 else _ai("127.0.0.1")

    monkeypatch.setattr(socket, "getaddrinfo", rebinding)
    with pytest.raises(UnsafeUrlError):
        ssrf_guard.safe_get("http://rebind.test/")


def test_safe_get_connects_to_the_address_it_validated(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _ai("93.184.216.34"))
    dialed = []

    def fake_create_connection(address, *args, **kwargs):
        dialed.append(address)
        raise OSError("no network in tests")

    monkeypatch.setattr(ssrf_guard._u3conn, "create_connection", fake_create_connection)
    with pytest.raises(requests.ConnectionError):
        ssrf_guard.safe_get("http://public.test/")
    assert dialed == [("93.184.216.34", 80)]


def test_unsafe_url_errors_do_not_reveal_resolved_addresses(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _ai("10.0.0.5"))
    with pytest.raises(UnsafeUrlError) as exc:
        ssrf_guard.assert_safe_url("http://intranet.test/")
    assert "10.0.0.5" not in str(exc.value)
```

Append to `tests/web/test_source_preview.py`:

```python
def test_preview_reports_blocked_urls_without_internal_details(client):
    from app.security.ssrf_guard import UnsafeUrlError

    def blocked(source):
        raise UnsafeUrlError("URL resolves to a disallowed address: 10.0.0.5")

    with patch("app.web.routes_sources.ADAPTERS", {"greenhouse": blocked}):
        resp = client.post("/sources/test-preview", data={
            "type": "greenhouse", "name": "Acme", "board_token": "acme",
            "include_keywords": "", "exclude_keywords": "",
        })
    error = resp.json()["error"]
    assert "10.0.0.5" not in error
    assert "private or internal" in error
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/security/test_ssrf_guard.py tests/web/test_source_preview.py -v`
Expected: FAIL — `100.64.0.1` allowed; rebinding test raises `ConnectionError` instead of `UnsafeUrlError`; `_u3conn` attribute missing; IP present in messages.

- [ ] **Step 3: Implement**

Rewrite the top half of `app/security/ssrf_guard.py` (keep `install_ssrf_guard` until Task 11):

```python
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError
from urllib3.util import connection as _u3conn

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}
_DEFAULT_MAX_REDIRECTS = 5
_DEFAULT_TIMEOUT = 30
_NAT64 = ipaddress.ip_network("64:ff9b::/96")

UNSAFE_URL_MESSAGE = "That URL points to a private or internal network address, which isn't allowed."


class UnsafeUrlError(ValueError):
    pass


def _is_disallowed_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip in _NAT64:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    # is_global excludes CGNAT (100.64/10 -- Tailscale), benchmarking, and the
    # other special-purpose ranges the individual is_* flags miss (audit M2).
    return (
        not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def _resolve_public_ip(host: str, port: int | None) -> str:
    """Resolve `host`, reject it if *any* answer is non-public, and return the
    address to dial -- the caller connects to exactly this IP (no second lookup)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Could not resolve host: {host!r}") from exc
    for info in infos:
        if _is_disallowed_ip(str(info[4][0])):
            logger.info("Blocked outbound request to %s (resolves to %s)", host, info[4][0])
            raise UnsafeUrlError(UNSAFE_URL_MESSAGE)
    return str(infos[0][4][0])


def assert_safe_url(url: str) -> None:
    """Raises UnsafeUrlError unless `url` is http(s) and its host resolves only
    to public addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"Disallowed URL scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise UnsafeUrlError("URL has no hostname")
    _resolve_public_ip(parsed.hostname, parsed.port)


class _PinnedConnectionMixin:
    """Resolve-validate-connect in one step, closing the DNS-rebinding window
    between assert_safe_url's lookup and urllib3's own. TLS SNI and certificate
    checks still use the hostname (urllib3 takes those from self.host)."""

    def _new_conn(self):  # type: ignore[no-untyped-def]
        ip = _resolve_public_ip(self._dns_host, self.port)  # type: ignore[attr-defined]
        try:
            return _u3conn.create_connection(
                (ip, self.port), self.timeout,  # type: ignore[attr-defined]
                source_address=self.source_address,  # type: ignore[attr-defined]
                socket_options=self.socket_options,  # type: ignore[attr-defined]
            )
        except OSError as exc:
            raise NewConnectionError(self, f"Failed to establish a new connection: {exc}") from exc  # type: ignore[arg-type]


class _PinnedHTTPConnection(_PinnedConnectionMixin, HTTPConnection):
    pass


class _PinnedHTTPSConnection(_PinnedConnectionMixin, HTTPSConnection):
    pass


class _PinnedHTTPPool(HTTPConnectionPool):
    ConnectionCls = _PinnedHTTPConnection


class _PinnedHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _PinnedHTTPSConnection


class _PinnedAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _PinnedHTTPPool, "https": _PinnedHTTPSPool}


def _guarded_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False  # an env proxy would dial the target itself, unpinned
    adapter = _PinnedAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def safe_request(method: str, url: str, *, max_redirects: int = _DEFAULT_MAX_REDIRECTS,
                  **kwargs) -> requests.Response:
    """requests.request wrapper that SSRF-validates every hop and dials only
    the validated address."""
    assert_safe_url(url)
    kwargs["allow_redirects"] = False
    kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
    current_url = url
    with _guarded_session() as session:
        for _ in range(max_redirects + 1):
            response = session.request(method, current_url, **kwargs)
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                if not location:
                    return response
                current_url = urljoin(current_url, location)
                assert_safe_url(current_url)
                continue
            return response
    raise UnsafeUrlError(f"Too many redirects (> {max_redirects})")


def safe_get(url: str, **kwargs) -> requests.Response:
    return safe_request("GET", url, **kwargs)


def safe_post(url: str, **kwargs) -> requests.Response:
    return safe_request("POST", url, **kwargs)


def safe_head(url: str, **kwargs) -> requests.Response:
    kwargs.pop("allow_redirects", None)  # redirects are always followed hop-by-hop
    return safe_request("HEAD", url, **kwargs)
```

`app/web/routes_sources.py` `test_source_preview` — before the generic `except Exception`:

```python
    except UnsafeUrlError:
        return {"error": UNSAFE_URL_MESSAGE}
```

(import `from app.security.ssrf_guard import UNSAFE_URL_MESSAGE, UnsafeUrlError`.)

Verify `_dns_host`, `source_address`, `socket_options` exist on `urllib3.connection.HTTPConnection` for the installed urllib3 (`python -c "import urllib3, inspect; print(urllib3.__version__); print(inspect.getsource(urllib3.connection.HTTPConnection._new_conn))"`); the mixin mirrors that method, so adjust attribute names if the installed version differs.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/security tests/web/test_source_preview.py tests/adapters -v` then `pytest -q`
Expected: PASS. Existing `test_ssrf_guard.py` tests that monkeypatch `requests.request` must now patch `requests.Session.request` (or `ssrf_guard._guarded_session`) instead — update them.

- [ ] **Step 5: Commit**

```bash
git add app/security/ssrf_guard.py app/web/routes_sources.py tests/
git commit -m "fix(security): SSRF guard blocks all non-global ranges and pins the validated IP; generic blocked-URL error (M2, L3)"
```

---

### Task 10: URL checker goes through the SSRF guard

Fixes M9.

**Files:**
- Modify: `app/checker.py`
- Modify: `tests/conftest.py` (`_offline_head` signature)
- Test: `tests/test_checker.py`

**Interfaces:**
- Consumes: `ssrf_guard.safe_head`, `UnsafeUrlError` (Task 9).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_checker.py`:

```python
import inspect

from app import checker
from app.security import ssrf_guard
from app.security.ssrf_guard import UnsafeUrlError


def test_checker_defaults_to_the_ssrf_guarded_head():
    default = inspect.signature(checker.check_job_urls).parameters["http_head"].default
    assert default is ssrf_guard.safe_head


def test_blocked_job_urls_are_skipped_not_removed(pg_conn):
    from tests.conftest import owner_id_for
    from app import db
    from app.models import Job
    owner = owner_id_for(pg_conn)
    job = Job(key="html:x", title="T", url="http://169.254.169.254/latest", source_name="S", source_id="s")
    db.save_jobs(pg_conn, [job], db.start_run(pg_conn, user_id=owner), user_id=owner)

    def blocked(url, **kwargs):
        raise UnsafeUrlError(ssrf_guard.UNSAFE_URL_MESSAGE)

    assert checker.check_job_urls(pg_conn, http_head=blocked) == 0
    assert pg_conn.execute("SELECT removed_at FROM jobs WHERE key = 'html:x'").fetchone()[0] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_checker.py -v -k "defaults_to or blocked_job"`
Expected: FAIL — default is `requests.head`; `UnsafeUrlError` propagates out of the worker (`f.result()` raises).

- [ ] **Step 3: Implement**

`app/checker.py`: `from app.security.ssrf_guard import UnsafeUrlError, safe_head`; signature default `http_head: Callable = safe_head`; in `_is_removed`:

```python
        try:
            resp = http_head(url, timeout=10, allow_redirects=True)
        except UnsafeUrlError:
            logger.info("URL check skipped for job %s: URL is not a public address", key)
            return False
        except requests.exceptions.RequestException:
            logger.debug("URL check skipped for job %s (%s): request failed", key, url)
            return False
```

`tests/conftest.py` `_offline_head`: change to `def _offline_head(url, **kwargs):` (safe_head's call shape).

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_checker.py -v` then `pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/checker.py tests/
git commit -m "fix(security): URL checker HEADs through the SSRF guard and skips blocked URLs (M9)"
```

---

### Task 11: Browser guard validates every request and walks redirect chains itself

Fixes H4; covers Review Focus #4.

**Background (verified 2026-09-27, Playwright 1.62):** `page.route` sees only the
*first* URL of a redirect chain — Chromium follows 3xx hops without routing
them, even when the handler fulfils the 3xx itself. The only way to vet each
hop is for the handler to fetch hop-by-hop with `route.fetch(url=…, max_redirects=0)`,
validate each `Location`, and `route.fulfill` the final response. The document
keeps its original URL (relative links resolve against it); Playwright's
`route.fetch` resolves DNS separately from our check, so a rebinding window
remains on the browser path — documented residual.

**Files:**
- Modify: `app/security/ssrf_guard.py` (`install_ssrf_guard`, new `make_route_handler`)
- Modify: `app/adapters/browser.py:18`, `app/adapters/infor.py` (the `new_page(...)` before `install_ssrf_guard(page)` ~line 169)
- Test: `tests/security/test_browser_guard.py` (new, fakes — no browser), `tests/web/e2e/test_ssrf_browser_guard.py` (new, real Chromium)

**Interfaces:**
- Consumes: `assert_safe_url`, `UnsafeUrlError` (Task 9).
- Produces: `ssrf_guard.make_route_handler(check: Callable[[str], None] = assert_safe_url) -> Callable[[Route], None]`, `ssrf_guard.install_ssrf_guard(page, check=assert_safe_url) -> None`.

- [ ] **Step 1: Write the failing unit tests (fake Route — no browser)**

Create `tests/security/test_browser_guard.py`:

```python
from types import SimpleNamespace

from app.security.ssrf_guard import UnsafeUrlError, make_route_handler


class _Resp:
    def __init__(self, status: int, location: str | None = None):
        self.status = status
        self.headers = {"location": location} if location else {}


class _Route:
    def __init__(self, url: str, resource_type: str, responses: dict[str, _Resp] | None = None):
        self.request = SimpleNamespace(url=url, resource_type=resource_type)
        self._responses = responses or {}
        self.fetched: list[str] = []
        self.outcome: tuple = ()

    def fetch(self, url=None, max_redirects=None):
        assert max_redirects == 0
        self.fetched.append(url)
        return self._responses[url]

    def fulfill(self, response):
        self.outcome = ("fulfill", response)

    def continue_(self):
        self.outcome = ("continue",)

    def abort(self, error_code=None):
        self.outcome = ("abort", error_code)


def _block_internal(url: str) -> None:
    if "internal" in url:
        raise UnsafeUrlError("blocked")


def test_redirect_to_a_blocked_host_is_aborted_before_it_is_fetched():
    route = _Route("https://pub.test/a", "document", {
        "https://pub.test/a": _Resp(302, "https://pub.test/b"),
        "https://pub.test/b": _Resp(302, "http://internal.test/secret"),
    })
    make_route_handler(_block_internal)(route)
    assert route.outcome == ("abort", "blockedbyclient")
    assert "http://internal.test/secret" not in route.fetched


def test_allowed_redirect_chain_is_followed_and_fulfilled():
    final = _Resp(200)
    route = _Route("http://pub.test/a", "document", {
        "http://pub.test/a": _Resp(301, "https://pub.test/a"),
        "https://pub.test/a": _Resp(302, "/careers/"),
        "https://pub.test/careers/": final,
    })
    make_route_handler(_block_internal)(route)
    assert route.outcome == ("fulfill", final)


def test_too_many_redirects_is_aborted():
    loop = {f"https://pub.test/{i}": _Resp(302, f"https://pub.test/{i + 1}") for i in range(20)}
    route = _Route("https://pub.test/0", "document", loop)
    make_route_handler(_block_internal)(route)
    assert route.outcome == ("abort", "blockedbyclient")


def test_subresource_to_a_blocked_host_is_aborted():
    route = _Route("http://internal.test/pixel.gif", "image")
    make_route_handler(_block_internal)(route)
    assert route.outcome == ("abort", "blockedbyclient")


def test_allowed_subresource_is_continued():
    route = _Route("https://cdn.test/app.js", "script")
    make_route_handler(_block_internal)(route)
    assert route.outcome == ("continue",)
```

- [ ] **Step 2: Write the failing e2e test (real Chromium — lives under `tests/web/e2e/`)**

Create `tests/web/e2e/test_ssrf_browser_guard.py`:

```python
import http.server
import threading

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from app.security.ssrf_guard import UnsafeUrlError, install_ssrf_guard

_REDIRECTS = {"/a": "/b", "/b": "/c"}


@pytest.fixture
def redirect_server():
    hits: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            if self.path in _REDIRECTS:
                self.send_response(302)
                self.send_header("Location", _REDIRECTS[self.path])
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(f"<p>reached {self.path}</p>".encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", hits
    server.shutdown()


def _block_c(url: str) -> None:
    if url.endswith("/c"):
        raise UnsafeUrlError("blocked")


def test_second_redirect_hop_to_a_blocked_url_is_never_requested(redirect_server):
    base, hits = redirect_server
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(service_workers="block")
        install_ssrf_guard(page, check=_block_c)
        with pytest.raises(PlaywrightError):
            page.goto(f"{base}/a")
        browser.close()
    assert "/c" not in hits


def test_allowed_redirect_chain_renders_the_final_page(redirect_server):
    base, _ = redirect_server
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(service_workers="block")
        install_ssrf_guard(page, check=lambda url: None)
        page.goto(f"{base}/a")
        assert page.inner_text("p") == "reached /c"
        browser.close()
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/security/test_browser_guard.py tests/web/e2e/test_ssrf_browser_guard.py -v`
Expected: FAIL — `ImportError: make_route_handler`; `install_ssrf_guard() got an unexpected keyword argument 'check'`.

- [ ] **Step 4: Implement**

Replace `install_ssrf_guard` in `app/security/ssrf_guard.py` (add `from collections.abc import Callable`):

```python
def make_route_handler(check: Callable[[str], None] = assert_safe_url):
    """Playwright route handler enforcing `check` on every request.

    page.route only sees the first URL of a redirect chain -- Chromium follows
    3xx hops unrouted (audit H4, verified against Playwright 1.62). So for
    documents the handler fetches hop-by-hop itself, vets every Location, and
    fulfils the final response. Subresources are vetted on their first URL.
    """

    def _handle(route) -> None:
        request = route.request
        try:
            check(request.url)
        except UnsafeUrlError:
            route.abort("blockedbyclient")
            return
        if request.resource_type != "document":
            route.continue_()
            return
        url = request.url
        for _ in range(_DEFAULT_MAX_REDIRECTS + 1):
            response = route.fetch(url=url, max_redirects=0)
            location = response.headers.get("location")
            if not (300 <= response.status < 400 and location):
                route.fulfill(response=response)
                return
            url = urljoin(url, location)
            try:
                check(url)
            except UnsafeUrlError:
                route.abort("blockedbyclient")
                return
        route.abort("blockedbyclient")

    return _handle


def install_ssrf_guard(page, check: Callable[[str], None] = assert_safe_url) -> None:
    page.route("**/*", make_route_handler(check))
```

`app/adapters/browser.py:18`: `page = browser.new_page(user_agent=user_agent, service_workers="block")`.
`app/adapters/infor.py`: add `service_workers="block"` to the `new_page(...)` call that precedes `install_ssrf_guard(page)`.

- [ ] **Step 5: Run to verify pass**

Run: `pytest tests/security/test_browser_guard.py tests/web/e2e/test_ssrf_browser_guard.py tests/adapters -v`, then the infor live check if env is available (`pytest -m integration -k infor -v`), then `pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/security/ssrf_guard.py app/adapters/browser.py app/adapters/infor.py tests/security/test_browser_guard.py tests/web/e2e/test_ssrf_browser_guard.py
git commit -m "fix(security): browser SSRF guard vets every request and walks redirect chains itself; block service workers (H4)"
```

---

### Task 12: SMTP verifies the server certificate

Fixes M1; covers Review Focus #5.

**Files:**
- Modify: `app/emailer.py`
- Test: `tests/test_emailer.py`, `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_emailer.py`:

```python
import ssl

from app import emailer


class _FakeSMTP:
    instances: list = []

    def __init__(self, host, port, timeout=None, context=None):
        self.context = context
        self.starttls_context = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.starttls_context = context

    def login(self, user, password):
        pass

    def sendmail(self, frm, to, msg):
        pass


def _verifying(ctx) -> bool:
    return isinstance(ctx, ssl.SSLContext) and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_starttls_verifies_the_certificate(monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(emailer.smtplib, "SMTP", _FakeSMTP)
    emailer.send_email("smtp.test", 587, "u", "p", "f@x.test", ["t@x.test"], "s", "<p>b</p>")
    assert _verifying(_FakeSMTP.instances[0].starttls_context)


def test_implicit_tls_verifies_the_certificate(monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(emailer.smtplib, "SMTP_SSL", _FakeSMTP)
    emailer.send_email("smtp.test", 465, "u", "p", "f@x.test", ["t@x.test"], "s", "<p>b</p>")
    assert _verifying(_FakeSMTP.instances[0].context)
```

Append to `tests/test_scheduler.py` (Review Focus #5 — the scheduler's existing `except Exception` must keep the run alive):

```python
def test_run_completes_when_smtp_certificate_is_rejected(monkeypatch, caplog):
    import ssl
    from app import scheduler
    from app.digest import Digest
    monkeypatch.setattr(scheduler.db, "get_settings", lambda conn, uid: {
        "email_days": None, "resend_jobs": False, "email_to": "t@x.test",
        "digest_exclude_statuses": "", "digest_max_per_company": 0,
    })
    monkeypatch.setattr(scheduler.orchestrator, "run_once", lambda conn, sources, **kw: type(
        "S", (), {"run_id": 1, "new_jobs": [], "found_jobs": [], "failed_sources": []})())
    for name in ("get_unemailed_jobs", "list_jobs"):
        monkeypatch.setattr(scheduler.db, name, lambda *a, **k: [])
    monkeypatch.setattr(scheduler.db, "get_job_statuses", lambda *a, **k: {})
    monkeypatch.setattr(scheduler.digest, "build_digest", lambda *a, **k: Digest("s", "<p>b</p>"))
    monkeypatch.setattr(scheduler.db, "get_admin_smtp_settings", lambda conn: {
        "smtp_host": "smtp.test", "smtp_port": 587, "smtp_user": "u", "email_from": "f@x.test"})

    def reject(*a, **k):
        raise ssl.SSLCertVerificationError("certificate verify failed: self-signed certificate")

    monkeypatch.setattr(scheduler.emailer, "send_email", reject)
    scheduler._run_user("conn", "u1", [], "UTC", force=True)   # must not raise
    assert "certificate verify failed" in caplog.text
```

(Adjust the stubbed settings keys to match `_run_user`'s current reads if they differ.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_emailer.py tests/test_scheduler.py -v -k "verifies or certificate"`
Expected: the two emailer tests FAIL (`starttls_context is None`; `SMTP_SSL` got no `context`). The scheduler test should already PASS — it pins existing behavior.

- [ ] **Step 3: Implement**

`app/emailer.py`:

```python
import smtplib
import ssl
from email.mime.text import MIMEText
...
def send_email(...) -> None:
    ...
    # smtplib's default context skips certificate and hostname checks, which
    # would hand SMTP_PASSWORD to anyone on-path (audit M1).
    context = ssl.create_default_context()
    if smtp_port == _IMPLICIT_TLS_PORT:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30, context=context) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(email_from, email_to, msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls(context=context)
            server.login(smtp_user, smtp_password)
            server.sendmail(email_from, email_to, msg.as_string())
```

Update any existing fake SMTP classes in `tests/test_emailer.py` to accept `context=` / `starttls(context=None)`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_emailer.py tests/test_scheduler.py -v` then `pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/emailer.py tests/test_emailer.py tests/test_scheduler.py
git commit -m "fix(security): verify SMTP server certificates for STARTTLS and implicit TLS (M1)"
```

### Phase 3 wrap-up

- [ ] Bump to `1.7.0`; `CHANGELOG.md` (Security: H4, M1, M2, M9, L3). Call out: **SMTP relays with self-signed certs now fail** (logged `certificate verify failed`) — use a relay with a publicly-trusted cert.
- [ ] Rebuild the image and smoke-test a `generic_html` + `render_js` preview and one Infor source against the running container.
- [ ] `pytest -q && ruff check app tests && mypy`; push; open PR. **Stop for review.**

---

# Phase 4 — Hardening and docs (M8, L5, L7, L8)

Branch: `git switch -c chore/security-hardening-docs origin/master`.

### Task 13: Spike — run Chromium sandboxed in the container (M8)

Time-boxed investigation with an explicit go/no-go; ships as an opt-in flag either way.

**Files:**
- Modify: `app/adapters/browser.py`, `app/adapters/infor.py` (launch call)
- Test: `tests/adapters/test_browser_launch.py` (new, fakes)

**Interfaces:**
- Produces: `browser.chromium_launch_kwargs() -> dict` — `{"chromium_sandbox": True}` when env `CHROMIUM_SANDBOX` is `1`/`true`, else `{}`.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from app.adapters.browser import chromium_launch_kwargs


@pytest.mark.parametrize("value,expected", [
    ("1", {"chromium_sandbox": True}), ("true", {"chromium_sandbox": True}),
    ("0", {}), ("", {}),
])
def test_chromium_sandbox_is_opt_in(monkeypatch, value, expected):
    monkeypatch.setenv("CHROMIUM_SANDBOX", value)
    assert chromium_launch_kwargs() == expected
```

- [ ] **Step 2: Run — expect `ImportError`.** `pytest tests/adapters/test_browser_launch.py -v`

- [ ] **Step 3: Implement** in `app/adapters/browser.py`:

```python
import os


def chromium_launch_kwargs() -> dict:
    """Playwright launches Chromium with its sandbox off by default. Opt in with
    CHROMIUM_SANDBOX=1 where the container runtime supports it (audit M8)."""
    if os.environ.get("CHROMIUM_SANDBOX", "").lower() in ("1", "true"):
        return {"chromium_sandbox": True}
    return {}
```

and use `p.chromium.launch(**chromium_launch_kwargs())` in `browser.py` and `infor.py`.

- [ ] **Step 4: Spike in Docker.** Build (`docker compose build`), run with `CHROMIUM_SANDBOX=1`, trigger a `render_js` preview.
  - **Go** if the preview succeeds with only a compose-level change (e.g. `security_opt: ["seccomp=./chromium-seccomp.json"]` from Chromium's published profile, or the host already permits unprivileged user namespaces). Then set `CHROMIUM_SANDBOX: "1"` in both compose files and document the `security_opt`.
  - **No-go** if it needs `--privileged` or `SYS_ADMIN` — those are worse than the risk they remove. Leave the flag off by default and record the residual risk in `SECURITY.md` (Task 15).
  - Record the result and exact error text in the PR description.

- [ ] **Step 5: Run `pytest -q`; commit**

```bash
git add app/adapters/ tests/adapters/test_browser_launch.py docker-compose*.yml
git commit -m "feat(security): opt-in Chromium sandbox via CHROMIUM_SANDBOX (M8 spike)"
```

---

### Task 14: Cap digest recipients (L5)

**Files:**
- Modify: `app/web/routes_settings.py` (`save_preferences`, `_parse_preferences_import`)
- Test: `tests/web/test_settings.py`

**Interfaces:**
- Produces: `routes_settings.MAX_DIGEST_RECIPIENTS = 5`.

- [ ] **Step 1: Write the failing tests**

```python
def test_preferences_reject_more_than_five_recipients(member_client):
    resp = member_client.post("/settings/preferences", data={
        "email_to": [f"r{i}@x.test" for i in range(6)], "email_days": ["mon"],
    })
    assert resp.status_code == 400
    assert "at most 5" in resp.text


def test_import_keeps_only_the_first_five_recipients():
    from app.web.routes_settings import _parse_preferences_import
    parsed = _parse_preferences_import({"preferences": {"email_to": [f"r{i}@x.test" for i in range(8)]}})
    assert parsed[2].count(",") == 4
```

- [ ] **Step 2: Run — expect FAIL** (`200`/`303` accepted; 8 recipients kept). `pytest tests/web/test_settings.py -v -k recipients`

- [ ] **Step 3: Implement** — module constant `MAX_DIGEST_RECIPIENTS = 5`; in `save_preferences`, after the `invalid` check:

```python
    if len(submitted_emails) > MAX_DIGEST_RECIPIENTS:
        with request.app.state.pool.connection() as conn:
            settings = db.get_settings(conn, current_user["id"])
        return templates.TemplateResponse(
            request, "settings_preferences.html",
            {
                "settings": settings,
                "email_days_selected": selected_days,
                "email_to_list": submitted_emails,
                "digest_exclude_statuses_set": raw_exclude,
                "error": f"Digests can go to at most {MAX_DIGEST_RECIPIENTS} addresses.",
            },
            status_code=400,
        )
```

In `_parse_preferences_import`, build the list first and slice: 

```python
    valid = [addr.strip() for addr in emails
             if isinstance(addr, str) and addr.strip() and _is_valid_email(addr.strip())]
    email_to = ",".join(valid[:MAX_DIGEST_RECIPIENTS])
```

- [ ] **Step 4: Run** `pytest tests/web/test_settings.py -v` then `pytest -q` — PASS.

- [ ] **Step 5: Commit** `git commit -am "fix(security): cap digest recipients at 5 (L5)"`

---

### Task 15: Documentation, CI permissions, image pinning (L7, L8) and release

**Files:**
- Modify: `SECURITY.md`, `app/web/csrf_protection.py` (docstring), `app/web/security_headers.py` (comment), `README.md` (config table), `.env.example`, `.github/workflows/ci.yml`, `docker-compose.yml`, `docker-compose.prod.yml`, `ROADMAP.md`, `CHANGELOG.md`, `pyproject.toml`

- [ ] **Step 1: `SECURITY.md`** — replace "Known, accepted posture" with the current model: invite-only multi-user app with per-user data isolation; admin role can view (read-only) all users' jobs; required config (`SECRET_KEY` ≥32 chars, `PUBLIC_BASE_URL`, recommended `ALLOWED_HOSTS`, TLS via reverse proxy); SSRF guard scope and **residual risks** (browser-path DNS rebinding via `route.fetch`; subresource redirects not re-vetted; Chromium sandbox status from Task 13; flash messages via query string, L6, accepted). Link the 2026-09-27 audit.
- [ ] **Step 2: Docstrings** — `csrf_protection.py`: describe the Origin/`Sec-Fetch-Site` check as a complement to the `SameSite=Lax` session cookie, and why requests carrying neither header are allowed (non-browser clients carry no session cookie). `security_headers.py`: drop "no auth" wording.
- [ ] **Step 3: `.env.example`** — mark `SECRET_KEY` and `PUBLIC_BASE_URL` as **required**, remove the working-looking placeholder value from `SECRET_KEY=` (leave it empty with the generate command in the comment), add `ALLOWED_HOSTS=jobs.example.com,localhost` with a comment (`localhost` keeps the Docker healthcheck working), add `CHROMIUM_SANDBOX=` per Task 13.
- [ ] **Step 4: CI** — add at the top of `.github/workflows/ci.yml`:

```yaml
permissions:
  contents: read
```

- [ ] **Step 5: Pin Postgres** — `docker buildx imagetools inspect postgres:17 --format '{{json .Manifest.Digest}}'`, then in both compose files `image: postgres:17@sha256:<digest>` (Dependabot's docker ecosystem will keep it current). Pass `ALLOWED_HOSTS: ${ALLOWED_HOSTS:-}` and `CHROMIUM_SANDBOX: ${CHROMIUM_SANDBOX:-}` through in both compose files.
- [ ] **Step 6: ROADMAP/README** — add L6 (move flash messages into the session) to ROADMAP as a deferred item; update README's configuration table for the new required/optional vars.
- [ ] **Step 7: Verify** — `pytest -q && ruff check app tests && mypy`; `docker compose build && docker compose up -d`; `docker compose top` shows uvicorn as uid 1000; healthcheck healthy.
- [ ] **Step 8: Release** — bump to `1.7.1`, `CHANGELOG.md` entry, commit, push, open PR. **Stop for review.**

```bash
git add SECURITY.md README.md ROADMAP.md CHANGELOG.md pyproject.toml .env.example .github/workflows/ci.yml docker-compose*.yml app/web/csrf_protection.py app/web/security_headers.py
git commit -m "docs(security): update threat model and config docs; CI least-privilege token; pin postgres image (L7, L8)"
```

---

## Coverage map

| Finding | Task(s) |
|---|---|
| H1 cross-tenant job IDOR | 1 |
| H2 clear-cache wipes all tenants | 1 |
| H3 un-scoped scrape pipeline | 1 |
| H4 browser guard redirect bypass | 11 |
| H5 reset-link Host poisoning | 5 |
| M1 SMTP TLS unverified | 12 |
| M2 DNS rebinding / CGNAT | 9 |
| M3 run-now for all tenants | 3 |
| M4 import overwrites others' sources | 4 |
| M5 sessions unrevocable / not Secure | 5, 6 |
| M6 SECRET_KEY fails open | 5 |
| M7 event-loop blocking, missing rate limits, enumeration | 7 |
| M8 unsandboxed Chromium | 13 (spike) |
| M9 URL checker SSRF | 10 |
| L1 bcrypt >72 bytes | 7 |
| L2 dropdown metadata leak | 2 |
| L3 preview error leaks IPs | 9 |
| L4 invite race / usernames | 8 |
| L5 unbounded recipients | 14 |
| L6 flash via query string | Deferred — ROADMAP (Task 15) |
| L7 stale docs | 15 |
| L8 CI permissions / image pin | 15 |
