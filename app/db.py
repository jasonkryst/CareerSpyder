import json
import sqlite3
from datetime import UTC, datetime

from app.models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    url TEXT NOT NULL,
    posted_date TEXT,
    source_name TEXT NOT NULL,
    first_seen_run_id INTEGER,
    first_seen_at TEXT NOT NULL
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


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA)
    conn.commit()
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
    conn.executemany(
        "INSERT OR IGNORE INTO jobs "
        "(key, title, company, location, url, posted_date, source_name, first_seen_run_id, first_seen_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (j.key, j.title, j.company, j.location, j.url, j.posted_date, j.source_name, run_id, now)
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
    assert cur.lastrowid is not None
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, new_job_count: int, failed_sources: list[str]) -> None:
    conn.execute(
        "UPDATE runs SET finished_at = ?, new_job_count = ?, failed_sources = ? WHERE id = ?",
        (_now(), new_job_count, json.dumps(failed_sources), run_id),
    )
    conn.commit()


def list_runs(conn: sqlite3.Connection, limit: int = 50, offset: int = 0) -> list[dict]:
    rows = conn.execute(
        "SELECT id, started_at, finished_at, new_job_count, failed_sources "
        "FROM runs ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [
        {
            "id": r[0], "started_at": r[1], "finished_at": r[2],
            "new_job_count": r[3], "failed_sources": json.loads(r[4]),
        }
        for r in rows
    ]


def count_runs(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM runs").fetchone()
    return row[0]


def get_settings(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT smtp_host, smtp_port, smtp_user, email_from, email_to FROM settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    return {
        "smtp_host": row[0], "smtp_port": row[1], "smtp_user": row[2],
        "email_from": row[3], "email_to": row[4],
    }


def save_settings(conn: sqlite3.Connection, smtp_host: str, smtp_port: int, smtp_user: str,
                   email_from: str, email_to: str) -> None:
    conn.execute(
        "INSERT INTO settings (id, smtp_host, smtp_port, smtp_user, email_from, email_to) "
        "VALUES (1, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "smtp_host=excluded.smtp_host, smtp_port=excluded.smtp_port, smtp_user=excluded.smtp_user, "
        "email_from=excluded.email_from, email_to=excluded.email_to",
        (smtp_host, smtp_port, smtp_user, email_from, email_to),
    )
    conn.commit()


def seed_settings_if_empty(conn: sqlite3.Connection, smtp_host: str, smtp_port: int, smtp_user: str,
                            email_from: str, email_to: str) -> None:
    if get_settings(conn) is None:
        save_settings(conn, smtp_host, smtp_port, smtp_user, email_from, email_to)
