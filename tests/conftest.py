import uuid

import psycopg
import pytest
from alembic.config import Config
from pytest_postgresql import factories

from alembic import command
from app import db
from app.web.auth import hash_password

# Session-scoped PostgreSQL process (shared across all tests in a session)
postgresql_proc = factories.postgresql_proc(port=None)


@pytest.fixture(scope="function")
def pg_dsn(postgresql_proc):
    """Creates a fresh database for this test, applies Alembic migrations, yields DSN."""
    dbname = f"cs_test_{uuid.uuid4().hex[:12]}"
    host = postgresql_proc.host
    port = postgresql_proc.port
    user = postgresql_proc.user

    admin = psycopg.connect(
        f"host={host} port={port} user={user} dbname=postgres", autocommit=True
    )
    admin.execute(f"CREATE DATABASE {dbname}")
    admin.close()

    dsn = f"postgresql://{user}@{host}:{port}/{dbname}"

    cfg = Config("alembic.ini")
    cfg.set_main_option(
        "sqlalchemy.url", dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    )
    try:
        command.upgrade(cfg, "head")
        yield dsn
    finally:
        admin = psycopg.connect(
            f"host={host} port={port} user={user} dbname=postgres", autocommit=True
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
