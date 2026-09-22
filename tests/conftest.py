import os
import uuid

import psycopg
import pytest
import requests
from alembic.config import Config
from pytest_postgresql import factories

from alembic import command
from app import checker, db
from app.web.auth import hash_password

# If PGTEST_HOST is set, connect to an already-running PostgreSQL (e.g. a
# Docker container) instead of spawning a managed pg_ctl process.
if os.environ.get("PGTEST_HOST"):
    postgresql_proc = factories.postgresql_noproc(
        host=os.environ.get("PGTEST_HOST", "localhost"),
        port=int(os.environ.get("PGTEST_PORT", "5432")),
        user=os.environ.get("PGTEST_USER", "postgres"),
        password=os.environ.get("PGTEST_PASSWORD", "") or None,
    )
else:
    # Session-scoped PostgreSQL process (shared across all tests in a session)
    postgresql_proc = factories.postgresql_proc(port=None)


def _offline_head(url, *, timeout, allow_redirects):
    raise requests.ConnectionError(f"live network disabled in tests: {url}")


@pytest.fixture(autouse=True)
def _no_live_url_checks(monkeypatch):
    """run_once and /check-urls call checker.check_job_urls with the real
    requests.head; route those through an offline fake so no test makes a
    live HEAD request. Tests that inject their own http_head are unaffected."""
    real = checker.check_job_urls

    def _check(conn, http_head=None, **kwargs):
        return real(conn, http_head=http_head or _offline_head, **kwargs)

    monkeypatch.setattr(checker, "check_job_urls", _check)


@pytest.fixture(scope="function")
def pg_dsn(postgresql_proc):
    """Creates a fresh database for this test, applies Alembic migrations, yields DSN."""
    dbname = f"cs_test_{uuid.uuid4().hex[:12]}"
    host = postgresql_proc.host
    port = postgresql_proc.port
    user = postgresql_proc.user
    password = getattr(postgresql_proc, "password", None) or os.environ.get("PGPASSWORD", "") or None

    admin = psycopg.connect(
        f"host={host} port={port} user={user} dbname=postgres",
        password=password,
        autocommit=True,
    )
    admin.execute(f"CREATE DATABASE {dbname}")
    admin.close()

    userinfo = f"{user}:{password}" if password else user
    dsn = f"postgresql://{userinfo}@{host}:{port}/{dbname}"

    cfg = Config("alembic.ini")
    cfg.set_main_option(
        "sqlalchemy.url", dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    )
    try:
        command.upgrade(cfg, "head")
        yield dsn
    finally:
        admin = psycopg.connect(
            f"host={host} port={port} user={user} dbname=postgres",
            password=password,
            autocommit=True,
        )
        admin.execute(f"DROP DATABASE IF EXISTS {dbname} WITH (FORCE)")
        admin.close()


@pytest.fixture
def pg_conn(pg_dsn):
    """psycopg3 connection to a fresh, migrated test database."""
    conn = psycopg.connect(pg_dsn)
    yield conn
    conn.close()


def seed_admin(conn, *, username: str = "admin", password: str = "password123") -> dict:
    """Create an admin user and seed empty settings. Returns the user dict."""
    user = db.create_user(
        conn, username, f"{username}@test.local",
        hash_password(password), role="admin",
    )
    db.save_settings(conn, user["id"], "smtp.example.com", 587, "user", "from@x.test")
    return user
