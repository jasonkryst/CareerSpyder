import json
from datetime import UTC, datetime

import psycopg
from psycopg_pool import ConnectionPool

from app.models import FailedSource, Job


def _now() -> str:
    return datetime.now(UTC).isoformat()


def init_db(dsn: str) -> ConnectionPool:
    return ConnectionPool(dsn, min_size=1, max_size=10, open=True)


def get_new_jobs(conn: psycopg.Connection, jobs: list[Job]) -> list[Job]:
    if not jobs:
        return []
    placeholders = ",".join(["%s"] * len(jobs))
    keys = [j.key for j in jobs]
    rows = conn.execute(f"SELECT key FROM jobs WHERE key IN ({placeholders})", keys).fetchall()
    known = {r[0] for r in rows}
    return [j for j in jobs if j.key not in known]


def save_jobs(conn: psycopg.Connection, jobs: list[Job], run_id: int, user_id: str | None = None) -> None:
    if not jobs:
        return
    now = _now()
    locations = {j.location for j in jobs if j.location}
    with conn.cursor() as cur:
        if locations:
            cur.executemany(
                "INSERT INTO geocoded_locations (location, status) VALUES (%s, 'pending') ON CONFLICT DO NOTHING",
                [(loc,) for loc in locations],
            )
        cur.executemany(
            "INSERT INTO jobs "
            "(key, title, company, location, url, posted_date, source_name, source_id, summary, "
            "first_seen_run_id, first_seen_at, user_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            [
                (j.key, j.title, j.company, j.location, j.url, j.posted_date, j.source_name,
                 j.source_id, j.summary, run_id, now, user_id)
                for j in jobs
            ],
        )
    conn.commit()


def clear_jobs(conn: psycopg.Connection) -> None:
    conn.execute("DELETE FROM jobs")
    conn.commit()


def start_run(conn: psycopg.Connection, kind: str = "scrape", user_id: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO runs (started_at, kind, user_id) VALUES (%s, %s, %s) RETURNING id",
        (_now(), kind, user_id),
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("INSERT INTO runs did not produce an id")
    conn.commit()
    return row[0]


def finish_run(
    conn: psycopg.Connection, run_id: int, new_job_count: int,
    failed_sources: list[FailedSource],
) -> None:
    serialized = json.dumps([{"name": fs.name, "url": fs.url} for fs in failed_sources])
    conn.execute(
        "UPDATE runs SET finished_at = %s, new_job_count = %s, failed_sources = %s WHERE id = %s",
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
    "started_at": "runs.started_at",
    "finished_at": "runs.finished_at",
    "new_job_count": "runs.new_job_count",
}


def _run_where_sql(failures: str | None, user_id: str | None) -> tuple[str, list]:
    conditions: list[str] = []
    params: list = []
    if failures == "only":
        conditions.append("failed_sources != '[]'")
    elif failures == "clean":
        conditions.append("failed_sources = '[]'")
    if user_id is not None:
        conditions.append("runs.user_id = %s")
        params.append(user_id)
    return ("WHERE " + " AND ".join(conditions) if conditions else ""), params


def list_runs(
    conn: psycopg.Connection, limit: int = 50, offset: int = 0, *,
    sort: str = "", direction: str = "", failures: str | None = None,
    user_id: str | None = None,
) -> list[dict]:
    order_column = _RUN_SORT_COLUMNS.get(sort, "runs.id")
    order_dir = "ASC" if direction == "asc" else "DESC"
    where_sql, params = _run_where_sql(failures, user_id)
    query = (
        "SELECT runs.id, runs.started_at, runs.finished_at, runs.new_job_count, "
        "runs.failed_sources, runs.kind, users.username "
        "FROM runs LEFT JOIN users ON runs.user_id = users.id "
        f"{where_sql} ORDER BY {order_column} {order_dir}, runs.id {order_dir} "
        "LIMIT %s OFFSET %s"
    )
    rows = conn.execute(query, [*params, limit, offset]).fetchall()
    return [
        {
            "id": r[0], "started_at": r[1], "finished_at": r[2],
            "new_job_count": r[3], "failed_sources": _deserialize_failed_sources(r[4]),
            "kind": r[5], "username": r[6],
        }
        for r in rows
    ]


def count_runs(conn: psycopg.Connection, *, failures: str | None = None, user_id: str | None = None) -> int:
    where_sql, params = _run_where_sql(failures, user_id)
    row = conn.execute(f"SELECT COUNT(*) FROM runs {where_sql}", params).fetchone()
    return row[0] if row else 0


def get_settings(conn: psycopg.Connection, user_id: str) -> dict | None:
    row = conn.execute(
        "SELECT smtp_host, smtp_port, smtp_user, email_from, email_to, email_days, resend_jobs, "
        "hide_not_interested_on_map, digest_max_per_company, digest_exclude_statuses "
        "FROM settings WHERE user_id = %s",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "smtp_host": row[0], "smtp_port": row[1], "smtp_user": row[2],
        "email_from": row[3], "email_to": row[4],
        "email_days": row[5], "resend_jobs": row[6],
        "hide_not_interested_on_map": row[7],
        "digest_max_per_company": row[8] or 0,
        "digest_exclude_statuses": row[9] or "",
    }


def save_settings(conn: psycopg.Connection, user_id: str, smtp_host: str, smtp_port: int,
                   smtp_user: str, email_from: str) -> None:
    conn.execute(
        "INSERT INTO settings (user_id, smtp_host, smtp_port, smtp_user, email_from) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT(user_id) DO UPDATE SET "
        "smtp_host=excluded.smtp_host, smtp_port=excluded.smtp_port, "
        "smtp_user=excluded.smtp_user, email_from=excluded.email_from",
        (user_id, smtp_host, smtp_port, smtp_user, email_from),
    )
    conn.commit()


def save_preferences(
    conn: psycopg.Connection, user_id: str, email_days: str, resend_jobs: bool, email_to: str,
    hide_not_interested_on_map: bool = True,
    digest_max_per_company: int = 0,
    digest_exclude_statuses: str = "",
) -> None:
    conn.execute(
        "INSERT INTO settings "
        "(user_id, email_days, resend_jobs, email_to, hide_not_interested_on_map, "
        "digest_max_per_company, digest_exclude_statuses) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT(user_id) DO UPDATE SET "
        "email_days=excluded.email_days, resend_jobs=excluded.resend_jobs, "
        "email_to=excluded.email_to, "
        "hide_not_interested_on_map=excluded.hide_not_interested_on_map, "
        "digest_max_per_company=excluded.digest_max_per_company, "
        "digest_exclude_statuses=excluded.digest_exclude_statuses",
        (user_id, email_days, resend_jobs, email_to, hide_not_interested_on_map,
         digest_max_per_company, digest_exclude_statuses),
    )
    conn.commit()


def _seed_settings(conn: psycopg.Connection, user_id: str, smtp_host: str, smtp_port: int,
                   smtp_user: str, email_from: str, email_to: str) -> None:
    # SMTP fields always sync from env vars so adding/changing them in Portainer takes effect
    # on the next restart without requiring a settings-page visit.  Preference columns
    # (email_to, email_days, resend_jobs, …) are untouched on conflict — they belong to the user.
    conn.execute(
        "INSERT INTO settings (user_id, smtp_host, smtp_port, smtp_user, email_from, email_to) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET "
        "smtp_host = EXCLUDED.smtp_host, smtp_port = EXCLUDED.smtp_port, "
        "smtp_user = EXCLUDED.smtp_user, email_from = EXCLUDED.email_from",
        (user_id, smtp_host, smtp_port, smtp_user, email_from, email_to),
    )
    conn.commit()


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


def _job_filters_sql(
    company: str | None, source_name: list[str] | None, removed: str | None, emailed: str | None,
    status: list[str] | None = None, location: str | None = None, duplicates: str | None = None,
    state: list[str] | None = None,
    zip_lat: float | None = None, zip_lng: float | None = None, radius_miles: float | None = None,
    user_id: str | None = None,
) -> tuple[str, list]:
    clauses = []
    params: list = []
    if company:
        clauses.append("jobs.company ILIKE %s")
        params.append(f"%{company}%")
    if source_name:
        ph = ",".join(["%s"] * len(source_name))
        clauses.append(f"jobs.source_name IN ({ph})")
        params.extend(source_name)
    if removed == "active":
        clauses.append("jobs.removed_at IS NULL")
    elif removed == "removed":
        clauses.append("jobs.removed_at IS NOT NULL")
    if emailed == "sent":
        clauses.append("jobs.emailed_at IS NOT NULL")
    elif emailed == "not_sent":
        clauses.append("jobs.emailed_at IS NULL")
    if status:
        none_selected = "none" in status
        real = [s for s in status if s != "none"]
        if none_selected and real:
            ph = ",".join(["%s"] * len(real))
            clauses.append(f"(jobs.status IS NULL OR jobs.status IN ({ph}))")
            params.extend(real)
        elif none_selected:
            clauses.append("jobs.status IS NULL")
        else:
            ph = ",".join(["%s"] * len(real))
            clauses.append(f"jobs.status IN ({ph})")
            params.extend(real)
    if location == "__unresolved__":
        clauses.append("(geocoded_locations.status IS NULL OR geocoded_locations.status != 'resolved')")
    elif location:
        clauses.append("geocoded_locations.display_name = %s")
        params.append(location)
    if duplicates == "only":
        clauses.append("jobs.is_duplicate = TRUE")
    elif duplicates != "include":
        clauses.append("jobs.is_duplicate = FALSE")
    if state:
        ph = ",".join(["%s"] * len(state))
        clauses.append(f"geocoded_locations.region IN ({ph})")
        params.extend(state)
    if zip_lat is not None and zip_lng is not None and radius_miles is not None:
        clauses.append("haversine_miles(geocoded_locations.lat, geocoded_locations.lng, %s, %s) <= %s")
        params.extend([zip_lat, zip_lng, radius_miles])
    if user_id is not None:
        clauses.append("jobs.user_id = %s")
        params.append(user_id)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


def list_jobs(
    conn: psycopg.Connection, limit: int = 25, offset: int = 0, *,
    sort: str = "", direction: str = "",
    company: str | None = None, source_name: list[str] | None = None,
    removed: str | None = None, emailed: str | None = None, status: list[str] | None = None,
    location: str | None = None, duplicates: str | None = None,
    state: list[str] | None = None,
    zip_lat: float | None = None, zip_lng: float | None = None, radius_miles: float | None = None,
    user_id: str | None = None,
) -> list[dict]:
    order_column = _JOB_SORT_COLUMNS.get(sort, "jobs.first_seen_at")
    order_dir = "ASC" if direction == "asc" else "DESC"
    where_sql, params = _job_filters_sql(
        company, source_name, removed, emailed, status, location, duplicates,
        state=state, zip_lat=zip_lat, zip_lng=zip_lng, radius_miles=radius_miles,
        user_id=user_id,
    )
    query = (
        "SELECT jobs.key, jobs.title, jobs.company, jobs.location, geocoded_locations.display_name, "
        "jobs.location_override, gl_ov.display_name, "
        "jobs.url, jobs.posted_date, jobs.source_name, jobs.source_id, jobs.summary, "
        "jobs.first_seen_at, jobs.removed_at, jobs.emailed_at, jobs.status, "
        "jobs.is_duplicate, jobs.duplicate_of, users.username "
        "FROM jobs "
        "LEFT JOIN geocoded_locations ON jobs.location = geocoded_locations.location "
        "LEFT JOIN geocoded_locations gl_ov ON jobs.location_override = gl_ov.location "
        "LEFT JOIN users ON jobs.user_id = users.id "
        f"{where_sql} ORDER BY {order_column} {order_dir}, jobs.key {order_dir} LIMIT %s OFFSET %s"
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
            "is_duplicate": bool(r[16]), "duplicate_of": r[17], "username": r[18],
        }
        for r in rows
    ]


def count_jobs(
    conn: psycopg.Connection, *,
    company: str | None = None, source_name: list[str] | None = None,
    removed: str | None = None, emailed: str | None = None, status: list[str] | None = None,
    location: str | None = None, duplicates: str | None = None,
    state: list[str] | None = None,
    zip_lat: float | None = None, zip_lng: float | None = None, radius_miles: float | None = None,
    user_id: str | None = None,
) -> int:
    where_sql, params = _job_filters_sql(
        company, source_name, removed, emailed, status, location, duplicates,
        state=state, zip_lat=zip_lat, zip_lng=zip_lng, radius_miles=radius_miles,
        user_id=user_id,
    )
    row = conn.execute(
        "SELECT COUNT(*) FROM jobs LEFT JOIN geocoded_locations "
        f"ON jobs.location = geocoded_locations.location {where_sql}",
        params,
    ).fetchone()
    return row[0] if row else 0


def list_job_source_names(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT source_name FROM (SELECT DISTINCT source_name FROM jobs) t "
        "ORDER BY LOWER(source_name)"
    ).fetchall()
    return [r[0] for r in rows]


def list_job_locations(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT display_name FROM ("
        "SELECT DISTINCT display_name FROM geocoded_locations "
        "WHERE status = 'resolved' AND display_name IS NOT NULL"
        ") t ORDER BY LOWER(display_name)"
    ).fetchall()
    return [r[0] for r in rows]


def list_job_states(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT region FROM ("
        "SELECT DISTINCT region FROM geocoded_locations "
        "WHERE status IN ('resolved', 'manual') AND region IS NOT NULL"
        ") t ORDER BY LOWER(region)"
    ).fetchall()
    return [r[0] for r in rows]


def list_mappable_jobs(
    conn: psycopg.Connection, *,
    company: str | None = None, source_name: list[str] | None = None, location: str | None = None,
    removed: str | None = None, emailed: str | None = None, status: list[str] | None = None,
    exclude_status: str | None = None, duplicates: str | None = None,
    state: list[str] | None = None,
    zip_lat: float | None = None, zip_lng: float | None = None, radius_miles: float | None = None,
) -> list[dict]:
    where_sql, params = _job_filters_sql(
        company, source_name, removed, emailed, status, location, duplicates,
        state=state, zip_lat=zip_lat, zip_lng=zip_lng, radius_miles=radius_miles,
    )
    clauses = ["geocoded_locations.status IN ('resolved', 'manual')"]
    if exclude_status:
        clauses.append("(jobs.status IS NULL OR jobs.status != %s)")
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


def mark_emailed(conn: psycopg.Connection, keys: list[str]) -> None:
    if not keys:
        return
    now = _now()
    placeholders = ",".join(["%s"] * len(keys))
    conn.execute(f"UPDATE jobs SET emailed_at = %s WHERE key IN ({placeholders})", [now, *keys])
    conn.commit()


def get_unemailed_jobs(conn: psycopg.Connection) -> list[Job]:
    """Return Job objects for active jobs that have never been included in a digest email.

    Used to rescue jobs dropped by a crash between save_jobs committing and
    mark_emailed running.  Only active (removed_at IS NULL) rows are returned so
    we don't re-surface jobs that were posted, missed, and then taken down.
    """
    rows = conn.execute(
        "SELECT key, title, company, location, url, posted_date, source_name, source_id, summary "
        "FROM jobs WHERE emailed_at IS NULL AND removed_at IS NULL"
    ).fetchall()
    return [
        Job(key=r[0], title=r[1], company=r[2], location=r[3], url=r[4],
            posted_date=r[5], source_name=r[6] or "", source_id=r[7], summary=r[8])
        for r in rows
    ]


def reconcile_jobs(conn: psycopg.Connection, configured_source_ids: set[str],
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
        placeholders = ",".join(["%s"] * len(remove_keys))
        conn.execute(
            f"UPDATE jobs SET removed_at = %s WHERE key IN ({placeholders})",
            [now, *remove_keys],
        )

    removed_rows = conn.execute("SELECT key FROM jobs WHERE removed_at IS NOT NULL").fetchall()
    reactivate_keys = [key for (key,) in removed_rows if key in found_keys]
    if reactivate_keys:
        placeholders = ",".join(["%s"] * len(reactivate_keys))
        # Reset emailed_at so reactivated jobs are picked up by the next digest run.
        conn.execute(
            f"UPDATE jobs SET removed_at = NULL, emailed_at = NULL WHERE key IN ({placeholders})",
            reactivate_keys,
        )

    conn.commit()


def mark_job_removed(conn: psycopg.Connection, key: str) -> None:
    exists = conn.execute("SELECT 1 FROM jobs WHERE key = %s", (key,)).fetchone()
    if exists is None:
        raise KeyError(key)
    conn.execute("UPDATE jobs SET removed_at = %s WHERE key = %s AND removed_at IS NULL", (_now(), key))
    conn.commit()


def set_job_status(conn: psycopg.Connection, key: str, status: str | None) -> None:
    now = _now()
    cur = conn.execute("UPDATE jobs SET status = %s WHERE key = %s", (status, key))
    if cur.rowcount == 0:
        raise KeyError(key)
    conn.execute(
        "INSERT INTO job_status_history (job_key, status, changed_at) VALUES (%s, %s, %s)",
        (key, status, now),
    )
    conn.commit()


def get_geocoded_location(conn: psycopg.Connection, location: str) -> dict | None:
    row = conn.execute(
        "SELECT display_name, city, region, country, lat, lng, provider FROM geocoded_locations "
        "WHERE location = %s AND status IN ('resolved', 'manual')",
        (location,),
    ).fetchone()
    if row is None:
        return None
    return {
        "display_name": row[0], "city": row[1], "region": row[2],
        "country": row[3], "lat": row[4], "lng": row[5], "provider": row[6],
    }


def set_location_override(
    conn: psycopg.Connection, key: str, location: str,
    display_name: str, city: str | None, region: str | None, country: str | None,
    lat: float, lng: float, provider: str,
) -> None:
    now = _now()
    cur = conn.execute("SELECT key FROM jobs WHERE key = %s", (key,)).fetchone()
    if cur is None:
        raise KeyError(key)
    conn.execute(
        "INSERT INTO geocoded_locations "
        "(location, display_name, city, region, country, lat, lng, status, provider, resolved_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, 'manual', %s, %s) "
        "ON CONFLICT(location) DO UPDATE SET "
        "display_name=excluded.display_name, city=excluded.city, region=excluded.region, "
        "country=excluded.country, lat=excluded.lat, lng=excluded.lng, "
        "status='manual', provider=excluded.provider, resolved_at=excluded.resolved_at",
        (location, display_name, city, region, country, lat, lng, provider, now),
    )
    conn.execute("UPDATE jobs SET location_override = %s WHERE key = %s", (location, key))
    conn.commit()


def clear_location_override(conn: psycopg.Connection, key: str) -> None:
    cur = conn.execute("UPDATE jobs SET location_override = NULL WHERE key = %s", (key,))
    if cur.rowcount == 0:
        raise KeyError(key)
    conn.commit()


def get_job_statuses(conn: psycopg.Connection, keys: list[str]) -> dict[str, str | None]:
    if not keys:
        return {}
    placeholders = ",".join(["%s"] * len(keys))
    rows = conn.execute(
        f"SELECT key, status FROM jobs WHERE key IN ({placeholders})", keys,
    ).fetchall()
    return {key: status for key, status in rows}


def get_emailed_keys(conn: psycopg.Connection, keys: list[str]) -> set[str]:
    """Return the subset of `keys` that have been included in a prior digest email."""
    if not keys:
        return set()
    placeholders = ",".join(["%s"] * len(keys))
    rows = conn.execute(
        f"SELECT key FROM jobs WHERE key IN ({placeholders}) AND emailed_at IS NOT NULL", keys,
    ).fetchall()
    return {row[0] for row in rows}


def set_job_duplicate(conn: psycopg.Connection, key: str, duplicate_of: str | None = None) -> None:
    cur = conn.execute(
        "UPDATE jobs SET is_duplicate = TRUE, duplicate_of = %s WHERE key = %s", (duplicate_of, key)
    )
    if cur.rowcount == 0:
        raise KeyError(key)
    conn.commit()


def clear_job_duplicate(conn: psycopg.Connection, key: str) -> None:
    cur = conn.execute(
        "UPDATE jobs SET is_duplicate = FALSE, duplicate_of = NULL WHERE key = %s", (key,)
    )
    if cur.rowcount == 0:
        raise KeyError(key)
    conn.commit()


def get_job_status_history(conn: psycopg.Connection, keys: list[str]) -> dict[str, list[dict]]:
    if not keys:
        return {}
    placeholders = ",".join(["%s"] * len(keys))
    rows = conn.execute(
        f"SELECT job_key, status, changed_at FROM job_status_history "
        f"WHERE job_key IN ({placeholders}) ORDER BY changed_at DESC, id DESC",
        keys,
    ).fetchall()
    history: dict[str, list[dict]] = {}
    for job_key, status, changed_at in rows:
        history.setdefault(job_key, []).append({"status": status, "changed_at": changed_at})
    return history


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def create_user(
    conn: psycopg.Connection, username: str, email: str,
    password_hash: str, role: str = "member",
) -> dict:
    row = conn.execute(
        "INSERT INTO users (username, email, password_hash, role) "
        "VALUES (%s, %s, %s, %s) RETURNING id, username, email, role, is_active, created_at",
        (username, email, password_hash, role),
    ).fetchone()
    if row is None:
        raise RuntimeError("INSERT INTO users did not produce a row")
    conn.commit()
    return {"id": str(row[0]), "username": row[1], "email": row[2],
            "role": row[3], "is_active": row[4], "created_at": str(row[5])}


def get_user_by_id(conn: psycopg.Connection, user_id: str) -> dict | None:
    row = conn.execute(
        "SELECT id, username, email, role, is_active, created_at FROM users WHERE id = %s",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return {"id": str(row[0]), "username": row[1], "email": row[2],
            "role": row[3], "is_active": row[4], "created_at": str(row[5])}


def get_user_by_username(conn: psycopg.Connection, username: str) -> dict | None:
    row = conn.execute(
        "SELECT id, username, email, password_hash, role, is_active FROM users "
        "WHERE username = %s",
        (username,),
    ).fetchone()
    if row is None:
        return None
    return {"id": str(row[0]), "username": row[1], "email": row[2],
            "password_hash": row[3], "role": row[4], "is_active": row[5]}


def get_user_by_email(conn: psycopg.Connection, email: str) -> dict | None:
    row = conn.execute(
        "SELECT id, username, email, role, is_active FROM users WHERE email = %s",
        (email,),
    ).fetchone()
    if row is None:
        return None
    return {"id": str(row[0]), "username": row[1], "email": row[2],
            "role": row[3], "is_active": row[4]}


def list_users(conn: psycopg.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, username, email, role, is_active, created_at FROM users ORDER BY created_at"
    ).fetchall()
    return [{"id": str(r[0]), "username": r[1], "email": r[2],
             "role": r[3], "is_active": r[4], "created_at": str(r[5])} for r in rows]


def deactivate_user(conn: psycopg.Connection, user_id: str) -> None:
    conn.execute("UPDATE users SET is_active = FALSE WHERE id = %s", (user_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Invite tokens
# ---------------------------------------------------------------------------

def create_invite(
    conn: psycopg.Connection, email: str, created_by: str, expires_in_days: int = 7,
) -> dict:
    from datetime import UTC, datetime, timedelta
    expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)
    row = conn.execute(
        "INSERT INTO invite_tokens (email, created_by, expires_at) "
        "VALUES (%s, %s, %s) "
        "RETURNING token, email, expires_at",
        (email, created_by, expires_at),
    ).fetchone()
    if row is None:
        raise RuntimeError("INSERT INTO invite_tokens did not produce a row")
    conn.commit()
    return {"token": str(row[0]), "email": row[1], "expires_at": str(row[2])}


def get_invite(conn: psycopg.Connection, token: str) -> dict | None:
    row = conn.execute(
        "SELECT token, email, created_by, expires_at, used_at FROM invite_tokens WHERE token = %s",
        (token,),
    ).fetchone()
    if row is None:
        return None
    return {"token": str(row[0]), "email": row[1], "created_by": str(row[2]),
            "expires_at": str(row[3]), "used_at": str(row[4]) if row[4] else None}


def use_invite(conn: psycopg.Connection, token: str) -> None:
    conn.execute(
        "UPDATE invite_tokens SET used_at = NOW() WHERE token = %s AND used_at IS NULL",
        (token,),
    )
    conn.commit()


def list_invites(conn: psycopg.Connection, created_by: str) -> list[dict]:
    rows = conn.execute(
        "SELECT token, email, expires_at, used_at FROM invite_tokens "
        "WHERE created_by = %s ORDER BY expires_at DESC",
        (created_by,),
    ).fetchall()
    return [{"token": str(r[0]), "email": r[1], "expires_at": str(r[2]),
             "used_at": str(r[3]) if r[3] else None} for r in rows]


# ---------------------------------------------------------------------------
# Sources (per-user, replaces sources.json)
# ---------------------------------------------------------------------------

def _source_row_to_model(config_data: dict):
    from pydantic import TypeAdapter

    from app.config import SourceConfig  # local import to avoid circular dep
    return TypeAdapter(SourceConfig).validate_python(config_data)


def list_sources(conn: psycopg.Connection, user_id: str) -> list:
    rows = conn.execute(
        "SELECT config FROM sources WHERE user_id = %s ORDER BY name",
        (user_id,),
    ).fetchall()
    return [_source_row_to_model(r[0]) for r in rows]


def list_all_sources_by_user(conn: psycopg.Connection) -> dict[str, list]:
    """Returns {user_id: [SourceConfig, ...]} for every user that has sources."""
    rows = conn.execute(
        "SELECT user_id::text, config FROM sources ORDER BY user_id, name"
    ).fetchall()
    result: dict[str, list] = {}
    for user_id, config_data in rows:
        result.setdefault(user_id, []).append(_source_row_to_model(config_data))
    return result


def get_source(conn: psycopg.Connection, user_id: str, source_id: str):
    row = conn.execute(
        "SELECT config FROM sources WHERE id = %s AND user_id = %s",
        (source_id, user_id),
    ).fetchone()
    if row is None:
        return None
    return _source_row_to_model(row[0])


def add_source(conn: psycopg.Connection, user_id: str, source) -> None:
    data = source.model_dump()
    conn.execute(
        "INSERT INTO sources (id, user_id, type, name, secondary, config) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (source.id, user_id, source.type, source.name, source.secondary,
         json.dumps(data)),
    )
    conn.commit()


def update_source(conn: psycopg.Connection, user_id: str, source_id: str, source) -> None:
    data = source.model_dump()
    cur = conn.execute(
        "UPDATE sources SET type=%s, name=%s, secondary=%s, config=%s, "
        "updated_at=NOW() WHERE id=%s AND user_id=%s",
        (source.type, source.name, source.secondary, json.dumps(data),
         source_id, user_id),
    )
    if cur.rowcount == 0:
        raise KeyError(source_id)
    conn.commit()


def delete_source(conn: psycopg.Connection, user_id: str, source_id: str) -> None:
    cur = conn.execute(
        "DELETE FROM sources WHERE id = %s AND user_id = %s",
        (source_id, user_id),
    )
    if cur.rowcount == 0:
        raise KeyError(source_id)
    conn.commit()


def import_sources(conn: psycopg.Connection, user_id: str, sources: list) -> int:
    """Upsert a list of SourceConfig objects; returns count of upserted rows."""
    count = 0
    for source in sources:
        data = source.model_dump()
        conn.execute(
            "INSERT INTO sources (id, user_id, type, name, secondary, config) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(id) DO UPDATE SET "
            "type=excluded.type, name=excluded.name, secondary=excluded.secondary, "
            "config=excluded.config, updated_at=NOW()",
            (source.id, user_id, source.type, source.name, source.secondary,
             json.dumps(data)),
        )
        count += 1
    conn.commit()
    return count


# ---------------------------------------------------------------------------
# Admin bootstrap
# ---------------------------------------------------------------------------

def seed_admin_if_empty(
    conn: psycopg.Connection,
    username: str, email: str, password_hash: str,
    smtp_host: str, smtp_port: int, smtp_user: str, email_from: str, email_to: str,
) -> dict:
    """Create the admin user and seed their settings if the user doesn't exist yet.
    Backfills NULL user_id on existing data rows to the admin's id.
    Returns the admin user dict.
    """
    existing = get_user_by_username(conn, username)
    if existing:
        return existing

    admin = create_user(conn, username, email, password_hash, role="admin")
    admin_id = admin["id"]

    _seed_settings(conn, admin_id, smtp_host, smtp_port, smtp_user, email_from, email_to)

    # Backfill any pre-existing rows from a single-user install.
    conn.execute("UPDATE jobs SET user_id = %s WHERE user_id IS NULL", (admin_id,))
    conn.execute("UPDATE runs SET user_id = %s WHERE user_id IS NULL", (admin_id,))
    conn.execute(
        "UPDATE job_status_history SET user_id = %s WHERE user_id IS NULL", (admin_id,)
    )
    conn.commit()
    return admin
