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
