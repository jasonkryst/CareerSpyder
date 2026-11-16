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
    try:
        with psycopg.connect(pg_dsn) as conn:
            admin = db.create_user(conn, "admin", "admin@test.local", "x", role="admin")
            conn.execute(
                "INSERT INTO jobs (key, title, url, source_name, first_seen_at) "
                "VALUES ('lever:legacy', 'T', 'https://x.test', 'S', '2026-01-01T00:00:00+00:00')"
            )
            conn.commit()
        command.upgrade(cfg, "head")
        with psycopg.connect(pg_dsn) as conn:
            owner = conn.execute(
                "SELECT user_id::text FROM jobs WHERE key = 'lever:legacy'"
            ).fetchone()[0]
        assert owner == admin["id"]
    finally:
        command.upgrade(cfg, "head")


def test_migration_0003_without_an_admin_holds_ownerless_jobs_instead_of_deleting(pg_dsn):
    cfg = _cfg(pg_dsn)
    command.downgrade(cfg, "0002")
    try:
        with psycopg.connect(pg_dsn) as conn:
            conn.execute(
                "INSERT INTO jobs (key, title, url, source_name, first_seen_at) "
                "VALUES ('lever:orphan', 'T', 'https://x.test', 'S', '2026-01-01T00:00:00+00:00')"
            )
            conn.execute(
                "INSERT INTO job_status_history (job_key, status, changed_at) "
                "VALUES ('lever:orphan', 'applied', '2026-01-01T00:00:00+00:00')"
            )
            conn.commit()

        command.upgrade(cfg, "head")

        with psycopg.connect(pg_dsn) as conn:
            jobs_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            unowned_row = conn.execute(
                "SELECT key FROM jobs_unowned WHERE key = 'lever:orphan'"
            ).fetchone()
            assert jobs_count == 0
            assert unowned_row is not None

            admin = db.seed_admin_if_empty(
                conn, "admin", "admin@test.local", "x", "", 587, "", "", "",
            )

            owner = conn.execute(
                "SELECT user_id::text FROM jobs WHERE key = 'lever:orphan'"
            ).fetchone()
            assert owner is not None
            assert owner[0] == admin["id"]

            history_owner = conn.execute(
                "SELECT user_id::text FROM job_status_history WHERE job_key = 'lever:orphan'"
            ).fetchone()
            assert history_owner is not None
            assert history_owner[0] == admin["id"]

            remaining_jobs = conn.execute("SELECT COUNT(*) FROM jobs_unowned").fetchone()[0]
            remaining_history = conn.execute(
                "SELECT COUNT(*) FROM job_status_history_unowned"
            ).fetchone()[0]
            assert remaining_jobs == 0
            assert remaining_history == 0
    finally:
        command.upgrade(cfg, "head")


def test_migration_0007_lowercases_emails_and_skips_collisions(pg_dsn):
    cfg = _cfg(pg_dsn)
    command.downgrade(cfg, "0006")
    try:
        with psycopg.connect(pg_dsn) as conn:
            for name, email in [
                ("mixed", " Mixed@Example.COM "),
                ("clash_a", "Clash@x.test"),
                ("clash_b", "clash@x.test"),
                ("plain", "plain@x.test"),
            ]:
                conn.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, 'x')",
                    (name, email),
                )
            admin_id = conn.execute("SELECT id FROM users WHERE username = 'plain'").fetchone()[0]
            conn.execute(
                "INSERT INTO invite_tokens (email, created_by, expires_at) "
                "VALUES ('Invitee@X.test', %s, NOW() + interval '1 day')",
                (admin_id,),
            )
            conn.commit()

        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0006")  # no-op downgrade...
        command.upgrade(cfg, "head")    # ...and re-running is idempotent

        with psycopg.connect(pg_dsn) as conn:
            emails = dict(conn.execute("SELECT username, email FROM users").fetchall())
            invite_email = conn.execute("SELECT email FROM invite_tokens").fetchone()[0]
        assert emails["mixed"] == "mixed@example.com"
        assert emails["plain"] == "plain@x.test"
        # Collision: the mixed-case row is left alone rather than breaking UNIQUE.
        assert emails["clash_a"] == "Clash@x.test"
        assert emails["clash_b"] == "clash@x.test"
        assert invite_email == "invitee@x.test"
    finally:
        command.upgrade(cfg, "head")
