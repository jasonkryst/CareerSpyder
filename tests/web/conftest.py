import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREERSPYDER_DB_PATH", str(tmp_path / "state.db"))
    sources_path = tmp_path / "sources.json"
    sources_path.write_text(json.dumps({"sources": []}))
    monkeypatch.setenv("CAREERSPYDER_SOURCES_PATH", str(sources_path))
    monkeypatch.setenv("RUN_HOUR", "8")
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
