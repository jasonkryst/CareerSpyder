"""#269: the shared new-password policy is enforced on registration, password
reset, and change-password; the strength meter appears on those forms and
never on login. HIBP is always faked (see conftest's ``_no_live_hibp``)."""
import hashlib

import pytest
import requests

from app import db
from app.security import password_policy
from app.web.auth import generate_reset_token, verify_password

BREACHED = "tr0ub4dor&three"
CLEAN = "violet lantern orbit 42"


def _suffix(pw: str) -> str:
    return hashlib.sha1(pw.encode()).hexdigest().upper()[5:]  # noqa: S324 -- HIBP's format


class _Resp:
    def __init__(self, text):
        self.text = text
        self.status_code = 200

    def raise_for_status(self):
        pass


class FakeHIBP:
    """Reports BREACHED as seen 9,876 times; everything else as clean."""

    def __init__(self):
        self.calls = 0

    def __call__(self, url, **kwargs):
        self.calls += 1
        return _Resp(f"{_suffix(BREACHED)}:9876\r\n" + "0" * 35 + ":0\r\n")


@pytest.fixture
def hibp(monkeypatch):
    monkeypatch.setenv("CHECK_BREACHED_PASSWORDS", "true")
    fake = FakeHIBP()
    monkeypatch.setattr(password_policy, "_http_get", fake)
    return fake


@pytest.fixture
def hibp_down(monkeypatch):
    monkeypatch.setenv("CHECK_BREACHED_PASSWORDS", "true")

    def _fail(*_a, **_k):
        raise requests.ConnectionError("no egress")

    monkeypatch.setattr(password_policy, "_http_get", _fail)


def _invite(tc, email="new@test.local"):
    with tc.app.state.pool.connection() as conn:
        admin = db.get_user_by_username(conn, "admin")
        return str(db.create_invite(conn, email, admin["id"])["token"])


def _register(tc, password, *, username="newbie", email="new@test.local"):
    return tc.post("/register", data={
        "token": _invite(tc, email), "username": username,
        "password": password, "password_confirm": password,
    }, follow_redirects=False)


def _reset_token(tc):
    with tc.app.state.pool.connection() as conn:
        user = db.get_user_by_username(conn, "admin")
    return generate_reset_token(tc.app.state.secret_key, user["id"], user["email"], user["password_hash"])


def _reset(tc, password):
    return tc.post("/reset-password", data={
        "token": _reset_token(tc), "password": password, "password_confirm": password,
    }, follow_redirects=False)


def _change(tc, password):
    return tc.post("/settings/account/password", data={
        "current_password": "password123",
        "new_password": password, "new_password_confirm": password,
    }, follow_redirects=False)


def _admin_hash(tc):
    with tc.app.state.pool.connection() as conn:
        return db.get_user_by_username(conn, "admin")["password_hash"]


# ── registration ─────────────────────────────────────────────────────────────

def test_register_rejects_breached_password_with_explanation(unauthed_client, hibp):
    resp = _register(unauthed_client, BREACHED)
    assert resp.status_code == 400
    assert "data breach" in resp.text
    assert "9,876" in resp.text
    with unauthed_client.app.state.pool.connection() as conn:
        assert db.get_user_by_username(conn, "newbie") is None
    assert hibp.calls == 1


def test_register_accepts_clean_password_with_check_enabled(unauthed_client, hibp):
    resp = _register(unauthed_client, CLEAN)
    assert resp.status_code == 303
    assert hibp.calls == 1


def test_register_fails_open_when_hibp_unreachable(unauthed_client, hibp_down):
    assert _register(unauthed_client, CLEAN).status_code == 303


def test_register_does_not_call_hibp_when_disabled(unauthed_client):
    # conftest's guard raises if _http_get is touched.
    assert _register(unauthed_client, CLEAN).status_code == 303


def test_register_rejects_password_containing_username(unauthed_client):
    resp = _register(unauthed_client, "kestrel-likes-jobs", username="kestrel")
    assert resp.status_code == 400
    assert "must not contain your username" in resp.text


def test_register_rejects_password_containing_email(unauthed_client):
    resp = _register(unauthed_client, "x-heronfield-9", email="heronfield@test.local")
    assert resp.status_code == 400
    assert "must not contain your email" in resp.text


def test_register_rejects_common_password(unauthed_client):
    resp = _register(unauthed_client, "iloveyou")
    assert resp.status_code == 400
    assert "most common passwords" in resp.text


def test_register_honours_configured_min_length(unauthed_client, monkeypatch):
    monkeypatch.setenv("PASSWORD_MIN_LENGTH", "15")
    resp = _register(unauthed_client, "short but ok?")  # 13 chars
    assert resp.status_code == 400
    assert "at least 15 characters" in resp.text


# ── password reset ───────────────────────────────────────────────────────────

def test_reset_rejects_breached_password(unauthed_client, hibp):
    before = _admin_hash(unauthed_client)
    resp = _reset(unauthed_client, BREACHED)
    assert resp.status_code == 400
    assert "data breach" in resp.text
    assert _admin_hash(unauthed_client) == before


def test_reset_accepts_clean_password_with_check_enabled(unauthed_client, hibp):
    resp = _reset(unauthed_client, CLEAN)
    assert resp.status_code == 303
    assert verify_password(CLEAN, _admin_hash(unauthed_client))


def test_reset_rejects_password_containing_username(unauthed_client):
    resp = _reset(unauthed_client, "admin-new-pass-1")
    assert resp.status_code == 400
    assert "must not contain your username" in resp.text


def test_reset_fails_open_when_hibp_unreachable(unauthed_client, hibp_down):
    assert _reset(unauthed_client, CLEAN).status_code == 303


# ── change password ──────────────────────────────────────────────────────────

def test_change_password_rejects_breached_password(client, hibp):
    before = _admin_hash(client)
    resp = _change(client, BREACHED)
    assert resp.status_code == 400
    assert "data breach" in resp.text
    assert _admin_hash(client) == before


def test_change_password_accepts_clean_password_with_check_enabled(client, hibp):
    assert _change(client, CLEAN).status_code == 303
    assert verify_password(CLEAN, _admin_hash(client))


def test_change_password_rejects_common_password(client):
    resp = _change(client, "Password1")
    assert resp.status_code == 400
    assert "most common passwords" in resp.text


def test_change_password_wrong_current_password_skips_hibp(client, hibp):
    resp = client.post("/settings/account/password", data={
        "current_password": "nope", "new_password": CLEAN, "new_password_confirm": CLEAN,
    })
    assert resp.status_code == 400
    assert hibp.calls == 0


# ── login is untouched ───────────────────────────────────────────────────────

def test_login_never_runs_the_breach_check(unauthed_client, hibp):
    resp = unauthed_client.post("/login", data={"username": "admin", "password": "password123"},
                                follow_redirects=False)
    assert resp.status_code == 303
    assert hibp.calls == 0


# ── strength meter markup ────────────────────────────────────────────────────

def test_login_page_has_no_strength_meter(unauthed_client):
    resp = unauthed_client.get("/login")
    assert "data-password-strength" not in resp.text
    assert "password-strength.js" not in resp.text


def test_register_page_has_accessible_strength_meter(unauthed_client):
    resp = unauthed_client.get(f"/register?token={_invite(unauthed_client)}")
    assert resp.status_code == 200
    assert 'data-password-strength="password"' in resp.text
    assert 'aria-live="polite"' in resp.text
    assert 'aria-describedby="password-hint password-strength-text"' in resp.text
    assert "password-strength.js" in resp.text


def test_reset_page_has_strength_meter(unauthed_client):
    resp = unauthed_client.get(f"/reset-password?token={_reset_token(unauthed_client)}")
    assert 'data-password-strength="password"' in resp.text
    assert "password-strength.js" in resp.text


def test_account_page_meter_on_new_password_only(client):
    resp = client.get("/settings/account")
    assert 'data-password-strength="new_password"' in resp.text
    assert 'data-password-strength="current_password"' not in resp.text
    assert "password-strength.js" in resp.text


def test_forms_reflect_configured_min_length(unauthed_client, monkeypatch):
    monkeypatch.setenv("PASSWORD_MIN_LENGTH", "15")
    resp = unauthed_client.get(f"/register?token={_invite(unauthed_client)}")
    assert 'minlength="15"' in resp.text
    assert "At least 15 characters" in resp.text
