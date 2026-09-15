import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clear_geocode_zip_cache():
    """The _geocode_zip lru_cache persists across tests; clear it so each test
    gets a fresh geocode call rather than a stale cached result."""
    from app.web.routes_jobs import _geocode_zip
    _geocode_zip.cache_clear()
    yield
    _geocode_zip.cache_clear()


@pytest.fixture
def client(pg_dsn, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    sources_path = tmp_path / "sources.json"
    sources_path.write_text(json.dumps({"sources": []}))
    monkeypatch.setenv("CAREERSPYDER_SOURCES_PATH", str(sources_path))
    monkeypatch.setenv("RUN_CRON", "0 8 * * *")
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("EMAIL_FROM", "from@x.test")
    monkeypatch.setenv("EMAIL_TO", "to@x.test")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")

    from app.web.main import app

    with TestClient(app) as test_client:
        yield test_client
