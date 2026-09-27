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
