import secrets

import pytest
from fastapi.testclient import TestClient

from app.web.config_checks import (
    public_base_url,
    session_cookie_secure,
    validate_secret_key,
)


@pytest.mark.parametrize("key", [
    "", "dev-insecure-secret-change-me", "change-me-generate-a-real-secret", "change-me", "short-key",
])
def test_weak_secret_keys_are_rejected(key):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        validate_secret_key(key)


def test_a_generated_secret_key_is_accepted():
    validate_secret_key(secrets.token_hex(32))


def test_public_base_url_strips_trailing_slash_and_blank(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://jobs.example.com/")
    assert public_base_url() == "https://jobs.example.com"
    monkeypatch.setenv("PUBLIC_BASE_URL", "  ")
    assert public_base_url() is None


@pytest.mark.parametrize("base,expected", [
    ("https://jobs.example.com", True), ("http://nas.local:32600", False), (None, False),
])
def test_session_cookie_is_secure_only_for_https_deployments(base, expected):
    assert session_cookie_secure(base) is expected


def test_app_refuses_to_start_with_a_placeholder_secret_key(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "change-me-generate-a-real-secret")
    from app.web.main import app
    with pytest.raises(RuntimeError, match="SECRET_KEY"), TestClient(app):
        pass
