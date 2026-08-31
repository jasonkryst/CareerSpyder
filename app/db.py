import json
import math
import sqlite3
from datetime import UTC, datetime

from app.models import FailedSource, Job

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
    location_override TEXT,
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
    failed_sources TEXT NOT NULL DEFAULT '[]',
    kind TEXT NOT NULL DEFAULT 'scrape'
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


def _add_column_if_missing(conn: sqlite3.Connection, ddl: str, table: str = "settings") -> None:
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc):
            raise


_NEW_JOB_COLUMNS = {
    "source_id": "TEXT",
    "summary": "TEXT",
    "removed_at": "TEXT",
    "emailed_at": "TEXT",
    "status": "TEXT",
    "location_override": "TEXT",
    "is_duplicate": "INTEGER NOT NULL DEFAULT 0",
    "duplicate_of": "TEXT",
}


def _migrate_jobs_table(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    for column, col_type in _NEW_JOB_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {col_type}")
    conn.commit()


_JOBS_REBUILD_COLUMNS = (
    "key TEXT PRIMARY KEY, title TEXT NOT NULL, company TEXT, location TEXT, "
    "location_override TEXT, "
    "url TEXT NOT NULL, posted_date TEXT, source_name TEXT NOT NULL, source_id TEXT, "
    "summary TEXT, first_seen_run_id INTEGER, first_seen_at TEXT NOT NULL, "
    "removed_at TEXT, emailed_at TEXT, status TEXT, "
    "is_duplicate INTEGER NOT NULL DEFAULT 0, duplicate_of TEXT, "
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
        "INSERT INTO jobs_new (key, title, company, location, location_override, url, posted_date, "
        "source_name, source_id, summary, first_seen_run_id, first_seen_at, removed_at, emailed_at, status) "
        "SELECT key, title, company, location, NULL, url, posted_date, source_name, source_id, summary, "
        "first_seen_run_id, first_seen_at, removed_at, emailed_at, status FROM jobs"
    )
    conn.execute("DROP TABLE jobs")
    conn.execute("ALTER TABLE jobs_new RENAME TO jobs")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def _haversine_miles(lat1: float | None, lon1: float | None,
                     lat2: float | None, lon2: float | None) -> float | None:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.create_function("haversine_miles", 4, _haversine_miles)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _add_column_if_missing(conn, "email_days TEXT NOT NULL DEFAULT 'mon,tue,wed,thu,fri,sat,sun'")
    _add_column_if_missing(conn, "resend_jobs INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "hide_not_interested_on_map INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "kind TEXT NOT NULL DEFAULT 'scrape'", table="runs")
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


def start_run(conn: sqlite3.Connection, kind: str = "scrape") -> int:
    cur = conn.execute("INSERT INTO runs (started_at, kind) VALUES (?, ?)", (_now(), kind))
    conn.commit()
    if cur.lastrowid is None:
        raise RuntimeError("INSERT INTO runs did not produce a rowid")
    return cur.lastrowid


def finish_run(
    conn: sqlite3.Connection, run_id: int, new_job_count: int,
    failed_sources: list[FailedSource],
) -> None:
    serialized = json.dumps([{"name": fs.name, "url": fs.url} for fs in failed_sources])
    conn.execute(
        "UPDATE runs SET finished_at = ?, new_job_count = ?, failed_sources = ? WHERE id = ?",
        (_now(), new_job_count, serialized, run_id),
    )
    conn.commit()


def _deserialize_failed_sources(raw: str) -> list[dict]:
    entries = json.loads(raw)
    result = []
    for entry in entries:
        if isinstance(entry, str):
            result.append({"name": entry, "url": None})
        else:
            result.append({"name": entry["name"], "url": entry.get("url")})
    return result


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
        "SELECT id, started_at, finished_at, new_job_count, failed_sources, kind FROM runs "
        f"{where_sql} ORDER BY {order_column} {order_dir}, id {order_dir} LIMIT ? OFFSET ?"
    )
    rows = conn.execute(query, [*params, limit, offset]).fetchall()
    return [
        {
            "id": r[0], "started_at": r[1], "finished_at": r[2],
            "new_job_count": r[3], "failed_sources": _deserialize_failed_sources(r[4]),
            "kind": r[5],
        }
        for r in rows
    ]


def count_runs(conn: sqlite3.Connection, *, failures: str | None = None) -> int:
    where_sql, params = _run_filters_sql(failures)
    row = conn.execute(f"SELECT COUNT(*) FROM runs {where_sql}", params).fetchone()
    return row[0]


def get_settings(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT smtp_host, smtp_port, smtp_user, email_from, email_to, email_days, resend_jobs, "
        "hide_not_interested_on_map FROM settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    return {
        "smtp_host": row[0], "smtp_port": row[1], "smtp_user": row[2],
        "email_from": row[3], "email_to": row[4],
        "email_days": row[5], "resend_jobs": bool(row[6]),
        "hide_not_interested_on_map": bool(row[7]),
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


def save_preferences(
    conn: sqlite3.Connection, email_days: str, resend_jobs: bool, email_to: str,
    hide_not_interested_on_map: bool = True,
) -> None:
    conn.execute(
        "INSERT INTO settings (id, email_days, resend_jobs, email_to, hide_not_interested_on_map) "
        "VALUES (1, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "email_days=excluded.email_days, resend_jobs=excluded.resend_jobs, email_to=excluded.email_to, "
        "hide_not_interested_on_map=excluded.hide_not_interested_on_map",
        (email_days, int(resend_jobs), email_to, int(hide_not_interested_on_map)),
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
    "company": "jobs.company COLLATE NOCASE",
    "title": "jobs.title COLLATE NOCASE",
    "first_seen_at": "jobs.first_seen_at",
    "age_days": "(julianday(COALESCE(jobs.removed_at, 'now')) - julianday(jobs.first_seen_at))",
}


def _job_filters_sql(
    company: str | None, source_name: str | None, removed: str | None, emailed: str | None,
    status: str | None = None, location: str | None = None, duplicates: str | None = None,
    state: str | None = None,
    zip_lat: float | None = None, zip_lng: float | None = None, radius_miles: float | None = None,
) -> tuple[str, list]:
    clauses = []
    params: list = []
    if company:
        clauses.append("LOWER(jobs.company) LIKE ?")
        params.append(f"%{company.lower()}%")
    if source_name:
        clauses.append("jobs.source_name = ?")
        params.append(source_name)
    if removed == "active":
        clauses.append("jobs.removed_at IS NULL")
    elif removed == "removed":
        clauses.append("jobs.removed_at IS NOT NULL")
    if emailed == "sent":
        clauses.append("jobs.emailed_at IS NOT NULL")
    elif emailed == "not_sent":
        clauses.append("jobs.emailed_at IS NULL")
    if status == "none":
        clauses.append("jobs.status IS NULL")
    elif status:
        clauses.append("jobs.status = ?")
        params.append(status)
    if location == "__unresolved__":
        clauses.append("(geocoded_locations.status IS NULL OR geocoded_locations.status != 'resolved')")
    elif location:
        clauses.append("geocoded_locations.display_name = ?")
        params.append(location)
    if duplicates == "only":
        clauses.append("jobs.is_duplicate = 1")
    elif duplicates != "include":
        clauses.append("jobs.is_duplicate = 0")
    if state:
        clauses.append("geocoded_locations.region = ?")
        params.append(state)
    if zip_lat is not None and zip_lng is not None and radius_miles is not None:
        clauses.append("haversine_miles(geocoded_locations.lat, geocoded_locations.lng, ?, ?) <= ?")
        params.extend([zip_lat, zip_lng, radius_miles])
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


def list_jobs(
    conn: sqlite3.Connection, limit: int = 25, offset: int = 0, *,
    sort: str = "", direction: str = "",
    company: str | None = None, source_name: str | None = None,
    removed: str | None = None, emailed: str | None = None, status: str | None = None,
    location: str | None = None, duplicates: str | None = None,
    state: str | None = None,
    zip_lat: float | None = None, zip_lng: float | None = None, radius_miles: float | None = None,
) -> list[dict]:
    order_column = _JOB_SORT_COLUMNS.get(sort, "jobs.first_seen_at")
    order_dir = "ASC" if direction == "asc" else "DESC"
    where_sql, params = _job_filters_sql(
        company, source_name, removed, emailed, status, location, duplicates,
        state=state, zip_lat=zip_lat, zip_lng=zip_lng, radius_miles=radius_miles,
    )
    query = (
        "SELECT jobs.key, jobs.title, jobs.company, jobs.location, geocoded_locations.display_name, "
        "jobs.location_override, gl_ov.display_name, "
        "jobs.url, jobs.posted_date, jobs.source_name, jobs.source_id, jobs.summary, "
        "jobs.first_seen_at, jobs.removed_at, jobs.emailed_at, jobs.status, "
        "jobs.is_duplicate, jobs.duplicate_of "
        "FROM jobs "
        "LEFT JOIN geocoded_locations ON jobs.location = geocoded_locations.location "
        "LEFT JOIN geocoded_locations gl_ov ON jobs.location_override = gl_ov.location "
        f"{where_sql} ORDER BY {order_column} {order_dir}, jobs.rowid {order_dir} LIMIT ? OFFSET ?"
    )
    rows = conn.execute(query, [*params, limit, offset]).fetchall()
    return [
        {
            "key": r[0], "title": r[1], "company": r[2],
            "location": r[6] or r[5] or r[4] or r[3],
            "base_location": r[4] or r[3],
            "location_override": r[5],
            "is_overridden": r[5] is not None,
            "url": r[7],
            "posted_date": r[8], "source_name": r[9], "source_id": r[10], "summary": r[11],
            "first_seen_at": r[12], "removed_at": r[13], "emailed_at": r[14], "status": r[15],
            "is_duplicate": bool(r[16]), "duplicate_of": r[17],
        }
        for r in rows
    ]


def count_jobs(
    conn: sqlite3.Connection, *,
    company: str | None = None, source_name: str | None = None,
    removed: str | None = None, emailed: str | None = None, status: str | None = None,
    location: str | None = None, duplicates: str | None = None,
    state: str | None = None,
    zip_lat: float | None = None, zip_lng: float | None = None, radius_miles: float | None = None,
) -> int:
    where_sql, params = _job_filters_sql(
        company, source_name, removed, emailed, status, location, duplicates,
        state=state, zip_lat=zip_lat, zip_lng=zip_lng, radius_miles=radius_miles,
    )
    row = conn.execute(
        "SELECT COUNT(*) FROM jobs LEFT JOIN geocoded_locations "
        f"ON jobs.location = geocoded_locations.location {where_sql}",
        params,
    ).fetchone()
    return row[0]


def list_job_source_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT source_name FROM jobs ORDER BY source_name COLLATE NOCASE"
    ).fetchall()
    return [r[0] for r in rows]


def list_job_locations(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT display_name FROM geocoded_locations "
        "WHERE status = 'resolved' AND display_name IS NOT NULL "
        "ORDER BY display_name COLLATE NOCASE"
    ).fetchall()
    return [r[0] for r in rows]


def list_job_states(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT region FROM geocoded_locations "
        "WHERE status IN ('resolved', 'manual') AND region IS NOT NULL "
        "ORDER BY region COLLATE NOCASE"
    ).fetchall()
    return [r[0] for r in rows]


def list_mappable_jobs(
    conn: sqlite3.Connection, *,
    company: str | None = None, source_name: str | None = None, location: str | None = None,
    removed: str | None = None, emailed: str | None = None, status: str | None = None,
    exclude_status: str | None = None, duplicates: str | None = None,
    state: str | None = None,
    zip_lat: float | None = None, zip_lng: float | None = None, radius_miles: float | None = None,
) -> list[dict]:
    where_sql, params = _job_filters_sql(
        company, source_name, removed, emailed, status, location, duplicates,
        state=state, zip_lat=zip_lat, zip_lng=zip_lng, radius_miles=radius_miles,
    )
    clauses = ["geocoded_locations.status IN ('resolved', 'manual')"]
    if exclude_status:
        clauses.append("(jobs.status IS NULL OR jobs.status != ?)")
        params.append(exclude_status)
    resolved_clause = " AND ".join(clauses)
    where_sql = f"{where_sql} AND {resolved_clause}" if where_sql else f"WHERE {resolved_clause}"
    query = (
        "SELECT jobs.key, jobs.title, jobs.company, jobs.url, jobs.location_override, "
        "geocoded_locations.display_name, geocoded_locations.lat, geocoded_locations.lng "
        "FROM jobs LEFT JOIN geocoded_locations "
        "ON COALESCE(jobs.location_override, jobs.location) = geocoded_locations.location "
        f"{where_sql}"
    )
    rows = conn.execute(query, params).fetchall()
    return [
        {"key": r[0], "title": r[1], "company": r[2], "url": r[3],
         "is_overridden": r[4] is not None,
         "display_name": r[5], "lat": r[6], "lng": r[7]}
        for r in rows
    ]


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


def mark_job_removed(conn: sqlite3.Connection, key: str) -> None:
    exists = conn.execute("SELECT 1 FROM jobs WHERE key = ?", (key,)).fetchone()
    if exists is None:
        raise KeyError(key)
    conn.execute("UPDATE jobs SET removed_at = ? WHERE key = ? AND removed_at IS NULL", (_now(), key))
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


def set_location_override(
    conn: sqlite3.Connection, key: str, location: str,
    display_name: str, city: str | None, region: str | None, country: str | None,
    lat: float, lng: float, provider: str,
) -> None:
    now = _now()
    cur = conn.execute("SELECT key FROM jobs WHERE key = ?", (key,)).fetchone()
    if cur is None:
        raise KeyError(key)
    conn.execute(
        "INSERT INTO geocoded_locations "
        "(location, display_name, city, region, country, lat, lng, status, provider, resolved_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', ?, ?) "
        "ON CONFLICT(location) DO UPDATE SET "
        "display_name=excluded.display_name, city=excluded.city, region=excluded.region, "
        "country=excluded.country, lat=excluded.lat, lng=excluded.lng, "
        "status='manual', provider=excluded.provider, resolved_at=excluded.resolved_at",
        (location, display_name, city, region, country, lat, lng, provider, now),
    )
    conn.execute("UPDATE jobs SET location_override = ? WHERE key = ?", (location, key))
    conn.commit()


def clear_location_override(conn: sqlite3.Connection, key: str) -> None:
    cur = conn.execute("UPDATE jobs SET location_override = NULL WHERE key = ?", (key,))
    if cur.rowcount == 0:
        raise KeyError(key)
    conn.commit()


def get_job_statuses(conn: sqlite3.Connection, keys: list[str]) -> dict[str, str | None]:
    if not keys:
        return {}
    placeholders = ",".join("?" * len(keys))
    rows = conn.execute(
        f"SELECT key, status FROM jobs WHERE key IN ({placeholders})", keys,
    ).fetchall()
    return {key: status for key, status in rows}


def set_job_duplicate(conn: sqlite3.Connection, key: str, duplicate_of: str | None = None) -> None:
    cur = conn.execute(
        "UPDATE jobs SET is_duplicate = 1, duplicate_of = ? WHERE key = ?", (duplicate_of, key)
    )
    if cur.rowcount == 0:
        raise KeyError(key)
    conn.commit()


def clear_job_duplicate(conn: sqlite3.Connection, key: str) -> None:
    cur = conn.execute(
        "UPDATE jobs SET is_duplicate = 0, duplicate_of = NULL WHERE key = ?", (key,)
    )
    if cur.rowcount == 0:
        raise KeyError(key)
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
