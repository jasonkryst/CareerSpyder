"""#291: sign-in behind a proxy, case-insensitive login/recovery, Retry-After."""

from unittest.mock import patch

import pytest

from app import db
from app.web import ratelimit
from app.web.auth import hash_password


def _conn(tc):
    return tc.app.state.conn


def _make_user(tc, username: str, email: str, password: str = "password123") -> dict:
    return db.create_user(_conn(tc), username, email, hash_password(password))


# ── Case- and whitespace-insensitive login ───────────────────────────────────

@pytest.mark.parametrize("typed", ["Admin", "ADMIN", "  admin  ", "aDmIn"])
def test_login_username_is_case_and_whitespace_insensitive(unauthed_client, typed):
    resp = unauthed_client.post(
        "/login", data={"username": typed, "password": "password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_login_mixed_case_stored_username_matches_lowercase_input(unauthed_client):
    _make_user(unauthed_client, "Jason", "jason@x.test")
    resp = unauthed_client.post(
        "/login", data={"username": "jason", "password": "password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_login_case_insensitive_username_still_needs_right_password(unauthed_client):
    resp = unauthed_client.post(
        "/login", data={"username": "ADMIN", "password": "Password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 401


def test_get_user_by_username_prefers_exact_case_on_legacy_collision(unauthed_client):
    """Rows created before #291 may differ only by case; the exact one wins."""
    upper = _make_user(unauthed_client, "Sam", "sam1@x.test")
    lower = _make_user(unauthed_client, "sam", "sam2@x.test")
    conn = _conn(unauthed_client)
    assert db.get_user_by_username(conn, "Sam")["id"] == upper["id"]
    assert db.get_user_by_username(conn, "sam")["id"] == lower["id"]


def test_get_user_by_username_unknown_returns_none(unauthed_client):
    assert db.get_user_by_username(_conn(unauthed_client), "nobody") is None


def test_get_user_by_email_is_case_and_whitespace_insensitive(unauthed_client):
    conn = _conn(unauthed_client)
    # A legacy mixed-case row, inserted directly (create_user now normalizes).
    conn.execute(
        "INSERT INTO users (username, email, password_hash) VALUES ('legacy', 'Legacy@X.Test', 'x')"
    )
    conn.commit()
    found = db.get_user_by_email(conn, "  legacy@x.TEST ")
    assert found is not None and found["username"] == "legacy"


def test_create_user_normalizes_email(unauthed_client):
    user = _make_user(unauthed_client, "bob", "  Bob@Example.COM ")
    assert user["email"] == "bob@example.com"


def test_create_invite_normalizes_email(unauthed_client):
    admin = db.get_user_by_username(_conn(unauthed_client), "admin")
    invite = db.create_invite(_conn(unauthed_client), " New@Example.COM ", admin["id"])
    assert invite["email"] == "new@example.com"


# ── Account recovery with mixed-case stored emails ───────────────────────────

def test_account_recovery_matches_mixed_case_stored_email(unauthed_client):
    conn = _conn(unauthed_client)
    conn.execute(
        "INSERT INTO users (username, email, password_hash) VALUES ('mixed', 'Mixed@Example.com', 'x')"
    )
    conn.commit()
    with patch("app.emailer.send_email") as mock_send:
        resp = unauthed_client.post("/account-recovery", data={"email": "MIXED@example.com "})
    assert resp.status_code == 200
    assert mock_send.call_count == 1
    assert "mixed" in mock_send.call_args.kwargs["html_body"]
    # Mailed to the address on file, not whatever casing was typed.
    assert mock_send.call_args.kwargs["email_to"] == ["Mixed@Example.com"]


def test_account_recovery_unknown_email_still_sends_nothing(unauthed_client):
    with patch("app.emailer.send_email") as mock_send:
        unauthed_client.post("/account-recovery", data={"email": "ADMIN@test.localx"})
    assert mock_send.call_count == 0


# ── Registration: no case-only duplicates ────────────────────────────────────

def _invite(tc, email: str) -> str:
    admin = db.get_user_by_username(_conn(tc), "admin")
    return db.create_invite(_conn(tc), email, admin["id"])["token"]


def test_register_rejects_username_differing_only_by_case(unauthed_client):
    token = _invite(unauthed_client, "fresh@x.test")
    resp = unauthed_client.post("/register", data={
        "token": token, "username": "ADMIN",
        "password": "a-Long-unique-passphrase-91", "password_confirm": "a-Long-unique-passphrase-91",
    })
    assert resp.status_code == 400
    assert "already taken" in resp.text


def test_register_with_mixed_case_invite_email_stores_lowercase(unauthed_client):
    token = _invite(unauthed_client, "Casey@Example.com")
    resp = unauthed_client.post("/register", data={
        "token": token, "username": "Casey",
        "password": "a-Long-unique-passphrase-91", "password_confirm": "a-Long-unique-passphrase-91",
    }, follow_redirects=False)
    assert resp.status_code == 303
    user = db.get_user_by_username(_conn(unauthed_client), "casey")
    assert user["username"] == "Casey"  # display case kept
    assert user["email"] == "casey@example.com"


# ── Form inputs don't auto-capitalize ────────────────────────────────────────

@pytest.mark.parametrize("path,field", [
    ("/login", 'name="username"'),
    ("/account-recovery", 'name="email"'),
])
def test_identity_inputs_disable_autocapitalize(unauthed_client, path, field):
    html = unauthed_client.get(path).text
    tag = html[html.index(field):]
    tag = tag[: tag.index(">")]
    assert 'autocapitalize="none"' in tag
    assert 'autocorrect="off"' in tag
    assert 'spellcheck="false"' in tag


# ── 429 says how long to wait ────────────────────────────────────────────────

def _exhaust(tc, path: str, data: dict, n: int):
    for _ in range(n):
        tc.post(path, data=data, follow_redirects=False)
    return tc.post(path, data=data, follow_redirects=False)


def test_login_429_has_retry_after_and_minutes(unauthed_client):
    resp = _exhaust(unauthed_client, "/login", {"username": "x", "password": "y"}, 10)
    assert resp.status_code == 429
    retry = int(resp.headers["Retry-After"])
    assert 1 <= retry <= 900
    assert "Try again in 15 minutes." in resp.text


def test_login_under_limit_has_no_retry_after(unauthed_client):
    resp = unauthed_client.post("/login", data={"username": "x", "password": "y"})
    assert resp.status_code == 401
    assert "Retry-After" not in resp.headers


def test_reset_password_429_has_retry_after(unauthed_client):
    resp = _exhaust(unauthed_client, "/reset-password", {"token": "bad"}, 10)
    assert resp.status_code == 429
    assert 1 <= int(resp.headers["Retry-After"]) <= 900
    assert "Try again in" in resp.text


def test_register_429_has_retry_after(unauthed_client):
    resp = _exhaust(unauthed_client, "/register", {"token": ""}, 10)
    assert resp.status_code == 429
    assert 1 <= int(resp.headers["Retry-After"]) <= 3600
    assert "Try again in" in resp.text


def test_account_recovery_limit_stays_indistinguishable(unauthed_client):
    """Recovery deliberately answers the same when limited (no enumeration
    signal), so it gets no 429/Retry-After."""
    with patch("app.emailer.send_email"):
        resp = _exhaust(unauthed_client, "/account-recovery", {"email": "a@x.test"}, 5)
    assert resp.status_code == 200
    assert "Retry-After" not in resp.headers


# ── Behind a proxy, visitors get separate login limits ───────────────────────

def test_login_limit_is_per_visitor_behind_trusted_proxy(unauthed_client, monkeypatch):
    # TestClient's peer is the literal "testclient", not an IP; treat it as
    # the proxy (CIDR matching itself is covered in test_ratelimit.py).
    monkeypatch.setattr(ratelimit, "_is_trusted", lambda addr: addr.strip() == "testclient")
    bad = {"username": "x", "password": "y"}
    for _ in range(10):
        unauthed_client.post("/login", data=bad, headers={"X-Forwarded-For": "198.51.100.1"})
    blocked = unauthed_client.post("/login", data=bad, headers={"X-Forwarded-For": "198.51.100.1"})
    other = unauthed_client.post("/login", data=bad, headers={"X-Forwarded-For": "198.51.100.2"})
    assert blocked.status_code == 429
    assert other.status_code == 401
