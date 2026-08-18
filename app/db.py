import json
import sqlite3
from datetime import UTC, datetime

from app.models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS geocoded_locations (
    location TEXT PRIMARY KEY,
    display_name TEXT,
    city TEXT,
    region TEXT,
    country TEXT,
    lat REAL,
    lng REAL,
    status TEXT NOT NULL,
    provider TEXT,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    url TEXT NOT NULL,
    posted_date TEXT,
    source_name TEXT NOT NULL,
    source_id TEXT,
    summary TEXT,
    first_seen_run_id INTEGER,
    first_seen_at TEXT NOT NULL,
    removed_at TEXT,
    emailed_at TEXT,
    status TEXT,
    FOREIGN KEY (location) REFERENCES geocoded_locations(location)
);

CREATE TABLE IF NOT EXISTS job_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL,
    status TEXT,
    changed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    new_job_count INTEGER NOT NULL DEFAULT 0,
    failed_sources TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    smtp_host TEXT,
    smtp_port INTEGER,
    smtp_user TEXT,
    email_from TEXT,
    email_to TEXT
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _add_column_if_missing(conn: sqlite3.Connection, ddl: str) -> None:
    try:
        conn.execute(f"ALTER TABLE settings ADD COLUMN {ddl}")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc):
            raise


_NEW_JOB_COLUMNS = {
    "source_id": "TEXT",
    "summary": "TEXT",
    "removed_at": "TEXT",
    "emailed_at": "TEXT",
    "status": "TEXT",
}


def _migrate_jobs_table(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    for column, col_type in _NEW_JOB_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {col_type}")
    conn.commit()


_JOBS_REBUILD_COLUMNS = (
    "key TEXT PRIMARY KEY, title TEXT NOT NULL, company TEXT, location TEXT, "
    "url TEXT NOT NULL, posted_date TEXT, source_name TEXT NOT NULL, source_id TEXT, "
    "summary TEXT, first_seen_run_id INTEGER, first_seen_at TEXT NOT NULL, "
    "removed_at TEXT, emailed_at TEXT, status TEXT, "
    "FOREIGN KEY (location) REFERENCES geocoded_locations(location)"
)


def _migrate_jobs_location_fk(conn: sqlite3.Connection) -> None:
    fks = conn.execute("PRAGMA foreign_key_list(jobs)").fetchall()
    if any(fk[2] == "geocoded_locations" for fk in fks):
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        "INSERT OR IGNORE INTO geocoded_locations (location, status) "
        "SELECT DISTINCT location, 'pending' FROM jobs WHERE location IS NOT NULL"
    )
    conn.execute(f"CREATE TABLE jobs_new ({_JOBS_REBUILD_COLUMNS})")
    conn.execute(
        "INSERT INTO jobs_new (key, title, company, location, url, posted_date, source_name, "
        "source_id, summary, first_seen_run_id, first_seen_at, removed_at, emailed_at, status) "
        "SELECT key, title, company, location, url, posted_date, source_name, source_id, summary, "
        "first_seen_run_id, first_seen_at, removed_at, emailed_at, status FROM jobs"
    )
    conn.execute("DROP TABLE jobs")
    conn.execute("ALTER TABLE jobs_new RENAME TO jobs")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _add_column_if_missing(conn, "email_days TEXT NOT NULL DEFAULT 'mon,tue,wed,thu,fri,sat,sun'")
    _add_column_if_missing(conn, "resend_jobs INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    _migrate_jobs_table(conn)
    _migrate_jobs_location_fk(conn)
    return conn


def get_new_jobs(conn: sqlite3.Connection, jobs: list[Job]) -> list[Job]:
    if not jobs:
        return []
    placeholders = ",".join("?" * len(jobs))
    keys = [j.key for j in jobs]
    rows = conn.execute(f"SELECT key FROM jobs WHERE key IN ({placeholders})", keys).fetchall()
    known = {r[0] for r in rows}
    return [j for j in jobs if j.key not in known]


def save_jobs(conn: sqlite3.Connection, jobs: list[Job], run_id: int) -> None:
    if not jobs:
        return
    now = _now()
    locations = {j.location for j in jobs if j.location}
    if locations:
        conn.executemany(
            "INSERT OR IGNORE INTO geocoded_locations (location, status) VALUES (?, 'pending')",
            [(loc,) for loc in locations],
        )
    conn.executemany(
        "INSERT OR IGNORE INTO jobs "
        "(key, title, company, location, url, posted_date, source_name, source_id, summary, "
        "first_seen_run_id, first_seen_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (j.key, j.title, j.company, j.location, j.url, j.posted_date, j.source_name,
             j.source_id, j.summary, run_id, now)
            for j in jobs
        ],
    )
    conn.commit()


def clear_jobs(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM jobs")
    conn.commit()


def start_run(conn: sqlite3.Connection) -> int:
    cur = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (_now(),))
    conn.commit()
    if cur.lastrowid is None:
        raise RuntimeError("INSERT INTO runs did not produce a rowid")
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, new_job_count: int, failed_sources: list[str]) -> None:
    conn.execute(
        "UPDATE runs SET finished_at = ?, new_job_count = ?, failed_sources = ? WHERE id = ?",
        (_now(), new_job_count, json.dumps(failed_sources), run_id),
    )
    conn.commit()


_RUN_SORT_COLUMNS = {
    "started_at": "started_at",
    "finished_at": "finished_at",
    "new_job_count": "new_job_count",
}


def _run_filters_sql(failures: str | None) -> tuple[str, list]:
    if failures == "only":
        return "WHERE failed_sources != '[]'", []
    if failures == "clean":
        return "WHERE failed_sources = '[]'", []
    return "", []


def list_runs(
    conn: sqlite3.Connection, limit: int = 50, offset: int = 0, *,
    sort: str = "", direction: str = "", failures: str | None = None,
) -> list[dict]:
    order_column = _RUN_SORT_COLUMNS.get(sort, "id")
    order_dir = "ASC" if direction == "asc" else "DESC"
    where_sql, params = _run_filters_sql(failures)
    query = (
        "SELECT id, started_at, finished_at, new_job_count, failed_sources FROM runs "
        f"{where_sql} ORDER BY {order_column} {order_dir}, id {order_dir} LIMIT ? OFFSET ?"
    )
    rows = conn.execute(query, [*params, limit, offset]).fetchall()
    return [
        {
            "id": r[0], "started_at": r[1], "finished_at": r[2],
            "new_job_count": r[3], "failed_sources": json.loads(r[4]),
        }
        for r in rows
    ]


def count_runs(conn: sqlite3.Connection, *, failures: str | None = None) -> int:
    where_sql, params = _run_filters_sql(failures)
    row = conn.execute(f"SELECT COUNT(*) FROM runs {where_sql}", params).fetchone()
    return row[0]


def get_settings(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT smtp_host, smtp_port, smtp_user, email_from, email_to, email_days, resend_jobs "
        "FROM settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    return {
        "smtp_host": row[0], "smtp_port": row[1], "smtp_user": row[2],
        "email_from": row[3], "email_to": row[4],
        "email_days": row[5], "resend_jobs": bool(row[6]),
    }


def save_settings(conn: sqlite3.Connection, smtp_host: str, smtp_port: int, smtp_user: str,
                   email_from: str) -> None:
    conn.execute(
        "INSERT INTO settings (id, smtp_host, smtp_port, smtp_user, email_from) "
        "VALUES (1, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "smtp_host=excluded.smtp_host, smtp_port=excluded.smtp_port, smtp_user=excluded.smtp_user, "
        "email_from=excluded.email_from",
        (smtp_host, smtp_port, smtp_user, email_from),
    )
    conn.commit()


def save_preferences(conn: sqlite3.Connection, email_days: str, resend_jobs: bool, email_to: str) -> None:
    conn.execute(
        "INSERT INTO settings (id, email_days, resend_jobs, email_to) "
        "VALUES (1, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "email_days=excluded.email_days, resend_jobs=excluded.resend_jobs, email_to=excluded.email_to",
        (email_days, int(resend_jobs), email_to),
    )
    conn.commit()


def seed_settings_if_empty(conn: sqlite3.Connection, smtp_host: str, smtp_port: int, smtp_user: str,
                            email_from: str, email_to: str) -> None:
    if get_settings(conn) is None:
        conn.execute(
            "INSERT INTO settings (id, smtp_host, smtp_port, smtp_user, email_from, email_to) "
            "VALUES (1, ?, ?, ?, ?, ?)",
            (smtp_host, smtp_port, smtp_user, email_from, email_to),
        )
        conn.commit()


_JOB_SORT_COLUMNS = {
    "company": "company COLLATE NOCASE",
    "title": "title COLLATE NOCASE",
    "first_seen_at": "first_seen_at",
    "age_days": "(julianday(COALESCE(removed_at, 'now')) - julianday(first_seen_at))",
}


def _job_filters_sql(
    company: str | None, source_name: str | None, removed: str | None, emailed: str | None,
    status: str | None = None,
) -> tuple[str, list]:
    clauses = []
    params: list = []
    if company:
        clauses.append("LOWER(company) LIKE ?")
        params.append(f"%{company.lower()}%")
    if source_name:
        clauses.append("source_name = ?")
        params.append(source_name)
    if removed == "active":
        clauses.append("removed_at IS NULL")
    elif removed == "removed":
        clauses.append("removed_at IS NOT NULL")
    if emailed == "sent":
        clauses.append("emailed_at IS NOT NULL")
    elif emailed == "not_sent":
        clauses.append("emailed_at IS NULL")
    if status == "none":
        clauses.append("status IS NULL")
    elif status:
        clauses.append("status = ?")
        params.append(status)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


def list_jobs(
    conn: sqlite3.Connection, limit: int = 25, offset: int = 0, *,
    sort: str = "", direction: str = "",
    company: str | None = None, source_name: str | None = None,
    removed: str | None = None, emailed: str | None = None, status: str | None = None,
) -> list[dict]:
    order_column = _JOB_SORT_COLUMNS.get(sort, "first_seen_at")
    order_dir = "ASC" if direction == "asc" else "DESC"
    where_sql, params = _job_filters_sql(company, source_name, removed, emailed, status)
    query = (
        "SELECT key, title, company, location, url, posted_date, source_name, source_id, "
        "summary, first_seen_at, removed_at, emailed_at, status FROM jobs "
        f"{where_sql} ORDER BY {order_column} {order_dir}, rowid {order_dir} LIMIT ? OFFSET ?"
    )
    rows = conn.execute(query, [*params, limit, offset]).fetchall()
    return [
        {
            "key": r[0], "title": r[1], "company": r[2], "location": r[3], "url": r[4],
            "posted_date": r[5], "source_name": r[6], "source_id": r[7], "summary": r[8],
            "first_seen_at": r[9], "removed_at": r[10], "emailed_at": r[11], "status": r[12],
        }
        for r in rows
    ]


def count_jobs(
    conn: sqlite3.Connection, *,
    company: str | None = None, source_name: str | None = None,
    removed: str | None = None, emailed: str | None = None, status: str | None = None,
) -> int:
    where_sql, params = _job_filters_sql(company, source_name, removed, emailed, status)
    row = conn.execute(f"SELECT COUNT(*) FROM jobs {where_sql}", params).fetchone()
    return row[0]


def list_job_source_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT source_name FROM jobs ORDER BY source_name COLLATE NOCASE"
    ).fetchall()
    return [r[0] for r in rows]


def mark_emailed(conn: sqlite3.Connection, keys: list[str]) -> None:
    if not keys:
        return
    now = _now()
    placeholders = ",".join("?" * len(keys))
    conn.execute(f"UPDATE jobs SET emailed_at = ? WHERE key IN ({placeholders})", [now, *keys])
    conn.commit()


def reconcile_jobs(conn: sqlite3.Connection, configured_source_ids: set[str],
                    succeeded_source_ids: set[str], found_jobs: list[Job]) -> None:
    found_keys = {j.key for j in found_jobs}
    now = _now()

    active_rows = conn.execute(
        "SELECT key, source_id FROM jobs WHERE removed_at IS NULL AND source_id IS NOT NULL"
    ).fetchall()
    deleted_source_ids = {sid for _, sid in active_rows if sid not in configured_source_ids}

    remove_keys = [
        key for key, sid in active_rows
        if (sid in succeeded_source_ids and key not in found_keys) or sid in deleted_source_ids
    ]
    if remove_keys:
        placeholders = ",".join("?" * len(remove_keys))
        conn.execute(f"UPDATE jobs SET removed_at = ? WHERE key IN ({placeholders})", [now, *remove_keys])

    removed_rows = conn.execute("SELECT key FROM jobs WHERE removed_at IS NOT NULL").fetchall()
    reactivate_keys = [key for (key,) in removed_rows if key in found_keys]
    if reactivate_keys:
        placeholders = ",".join("?" * len(reactivate_keys))
        conn.execute(f"UPDATE jobs SET removed_at = NULL WHERE key IN ({placeholders})", reactivate_keys)

    conn.commit()


def set_job_status(conn: sqlite3.Connection, key: str, status: str | None) -> None:
    now = _now()
    cur = conn.execute("UPDATE jobs SET status = ? WHERE key = ?", (status, key))
    if cur.rowcount == 0:
        raise KeyError(key)
    conn.execute(
        "INSERT INTO job_status_history (job_key, status, changed_at) VALUES (?, ?, ?)",
        (key, status, now),
    )
    conn.commit()


def get_job_status_history(conn: sqlite3.Connection, keys: list[str]) -> dict[str, list[dict]]:
    if not keys:
        return {}
    placeholders = ",".join("?" * len(keys))
    rows = conn.execute(
        f"SELECT job_key, status, changed_at FROM job_status_history "
        f"WHERE job_key IN ({placeholders}) ORDER BY changed_at DESC, id DESC",
        keys,
    ).fetchall()
    history: dict[str, list[dict]] = {}
    for job_key, status, changed_at in rows:
        history.setdefault(job_key, []).append({"status": status, "changed_at": changed_at})
    return history
