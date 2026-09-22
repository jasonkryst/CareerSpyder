import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clear_rate_limits():
    """Rate-limit buckets are process-global; reset before each test so tests
    that POST /login or /account-recovery don't bleed into each other."""
    from app.web import ratelimit
    ratelimit.clear()
    yield


@pytest.fixture(autouse=True)
def _clear_geocode_zip_cache():
    """The _geocode_zip lru_cache persists across tests; clear it so each test
    gets a fresh geocode call rather than a stale cached result."""
    from app.web.routes_jobs import _geocode_zip
    _geocode_zip.cache_clear()
    yield
    _geocode_zip.cache_clear()


def _make_client(pg_dsn, monkeypatch, *, authenticated: bool = True):
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password123")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@test.local")
    monkeypatch.setenv("RUN_CRON", "0 8 * * *")
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("EMAIL_FROM", "from@x.test")
    monkeypatch.setenv("EMAIL_TO", "to@x.test")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")

    # The startup catch-up would otherwise fire a real run whenever the suite
    # runs after RUN_CRON's hour, leaving a stray scrape row in the DB.
    monkeypatch.setattr("app.web.main.catch_up_missed_run", lambda *a, **k: False)

    from app.web.main import app

    test_client = TestClient(app, raise_server_exceptions=True)
    test_client.__enter__()

    if authenticated:
        resp = test_client.post(
            "/login",
            data={"username": "admin", "password": "password123"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303), f"Login failed: {resp.status_code}"

    return test_client


@pytest.fixture
def client(pg_dsn, monkeypatch):
    """Authenticated admin test client."""
    tc = _make_client(pg_dsn, monkeypatch, authenticated=True)
    with tc.app.state.pool.connection() as conn:
        tc.app.state.conn = conn
        yield tc
    tc.__exit__(None, None, None)


@pytest.fixture
def unauthed_client(pg_dsn, monkeypatch):
    """Unauthenticated test client — for auth-flow tests."""
    tc = _make_client(pg_dsn, monkeypatch, authenticated=False)
    with tc.app.state.pool.connection() as conn:
        tc.app.state.conn = conn
        yield tc
    tc.__exit__(None, None, None)


@pytest.fixture
def admin_user_id(client):
    """Returns the UUID string of the seeded admin user."""
    from app import db
    with client.app.state.pool.connection() as conn:
        user = db.get_user_by_username(conn, "admin")
    assert user is not None
    return str(user["id"])


@pytest.fixture
def member_client(pg_dsn, monkeypatch):
    """Authenticated test client logged in as a regular member (role='member')."""
    tc = _make_client(pg_dsn, monkeypatch, authenticated=False)
    from app import db
    from app.web.auth import hash_password
    with tc.app.state.pool.connection() as conn:
        db.create_user(conn, "member1", "member1@test.local", hash_password("member123"))
    resp = tc.post("/login", data={"username": "member1", "password": "member123"},
                   follow_redirects=False)
    assert resp.status_code in (302, 303), f"Member login failed: {resp.status_code}"
    with tc.app.state.pool.connection() as conn:
        tc.app.state.conn = conn
        yield tc
    tc.__exit__(None, None, None)


@pytest.fixture
def member_user_id(member_client):
    """Returns the UUID string of the seeded member user."""
    from app import db
    with member_client.app.state.pool.connection() as conn:
        user = db.get_user_by_username(conn, "member1")
    assert user is not None
    return str(user["id"])


@pytest.fixture
def seed_source(client, admin_user_id):
    """Factory fixture: seed_source(source) → inserts source into DB for admin."""
    from app import db

    def _seed(source):
        with client.app.state.pool.connection() as conn:
            db.add_source(conn, admin_user_id, source)
        return source

    return _seed
