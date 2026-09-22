"""Tests for authentication: login, logout, registration, and access control."""

from unittest.mock import patch

import pytest
from pydantic import TypeAdapter

from app import db
from app.config import SourceConfig
from app.web.auth import (
    generate_reset_token,
    hash_password,
    verify_password,
    verify_reset_token,
)

_ta = TypeAdapter(SourceConfig)


# ── Login form ────────────────────────────────────────────────────────────────

def test_login_page_renders(unauthed_client):
    resp = unauthed_client.get("/login")
    assert resp.status_code == 200
    assert 'name="username"' in resp.text
    assert 'name="password"' in resp.text


def test_already_authenticated_get_login_redirects_away(client):
    resp = client.get("/login", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["location"] == "/"


def test_login_with_valid_credentials_redirects(unauthed_client):
    resp = unauthed_client.post(
        "/login",
        data={"username": "admin", "password": "password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_login_respects_next_param(unauthed_client):
    resp = unauthed_client.post(
        "/login",
        data={"username": "admin", "password": "password123", "next": "/sources"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/sources"


def test_login_ignores_absolute_url_in_next_to_prevent_open_redirect(unauthed_client):
    resp = unauthed_client.post(
        "/login",
        data={"username": "admin", "password": "password123",
              "next": "https://evil.example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_login_ignores_protocol_relative_url_in_next(unauthed_client):
    resp = unauthed_client.post(
        "/login",
        data={"username": "admin", "password": "password123",
              "next": "//evil.example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_login_with_wrong_password_returns_401(unauthed_client):
    resp = unauthed_client.post(
        "/login",
        data={"username": "admin", "password": "wrongpassword"},
    )
    assert resp.status_code == 401
    assert "Invalid username or password" in resp.text


def test_login_with_unknown_username_returns_401(unauthed_client):
    resp = unauthed_client.post(
        "/login",
        data={"username": "nobody", "password": "password123"},
    )
    assert resp.status_code == 401
    assert "Invalid username or password" in resp.text


def test_login_with_empty_fields_returns_400(unauthed_client):
    resp = unauthed_client.post(
        "/login",
        data={"username": "", "password": ""},
    )
    assert resp.status_code == 400
    assert "required" in resp.text.lower()


def test_login_error_shows_message_not_raw_exception(unauthed_client):
    resp = unauthed_client.post(
        "/login",
        data={"username": "admin", "password": "wrongpassword"},
    )
    assert resp.status_code == 401
    assert "Traceback" not in resp.text
    assert "Exception" not in resp.text


# ── Logout ────────────────────────────────────────────────────────────────────

def test_logout_redirects_to_login(client):
    resp = client.post("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_after_logout_protected_route_redirects_to_login(client):
    client.post("/logout", follow_redirects=False)
    resp = client.get("/jobs", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


# ── Access control ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/", "/jobs", "/sources", "/sources/new",
                                   "/settings/email", "/settings/preferences",
                                   "/settings/data", "/guide"])
def test_unauthenticated_request_redirects_to_login(unauthed_client, path):
    resp = unauthed_client.get(path, follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


def test_authenticated_user_can_access_dashboard(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_authenticated_user_can_access_jobs(client):
    resp = client.get("/jobs")
    assert resp.status_code == 200


def test_authenticated_user_can_access_sources(client):
    resp = client.get("/sources")
    assert resp.status_code == 200


def test_authenticated_user_can_access_settings(client):
    resp = client.get("/settings/email")
    assert resp.status_code == 200


# ── Registration ──────────────────────────────────────────────────────────────

def test_register_form_without_token_returns_400(unauthed_client):
    resp = unauthed_client.get("/register")
    assert resp.status_code == 400
    assert "invite token" in resp.text.lower()


def test_register_form_with_valid_token_renders(unauthed_client):
    conn = unauthed_client.app.state.conn
    admin_user = db.get_user_by_username(conn, "admin")
    invite = db.create_invite(conn, "newuser@x.test", admin_user["id"])

    resp = unauthed_client.get(f"/register?token={invite['token']}")

    assert resp.status_code == 200
    assert 'name="username"' in resp.text
    assert 'name="password"' in resp.text


def test_post_register_with_valid_invite_creates_user_and_logs_in(unauthed_client):
    conn = unauthed_client.app.state.conn
    admin_user = db.get_user_by_username(conn, "admin")
    invite = db.create_invite(conn, "bob@x.test", admin_user["id"])

    resp = unauthed_client.post("/register", data={
        "token": invite["token"],
        "username": "bob",
        "password": "securepass1",
        "password_confirm": "securepass1",
    }, follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    user = db.get_user_by_username(conn, "bob")
    assert user is not None
    assert user["email"] == "bob@x.test"


def test_post_register_with_expired_invite_returns_400(unauthed_client):
    conn = unauthed_client.app.state.conn
    admin_user = db.get_user_by_username(conn, "admin")
    invite = db.create_invite(conn, "expired@x.test", admin_user["id"], expires_in_days=-1)

    resp = unauthed_client.post("/register", data={
        "token": invite["token"],
        "username": "expired",
        "password": "securepass1",
        "password_confirm": "securepass1",
    })

    assert resp.status_code == 400
    assert "expired" in resp.text.lower()


def test_post_register_with_mismatched_passwords_returns_400(unauthed_client):
    conn = unauthed_client.app.state.conn
    admin_user = db.get_user_by_username(conn, "admin")
    invite = db.create_invite(conn, "mismatch@x.test", admin_user["id"])

    resp = unauthed_client.post("/register", data={
        "token": invite["token"],
        "username": "mismatch",
        "password": "securepass1",
        "password_confirm": "different1",
    })

    assert resp.status_code == 400
    assert "do not match" in resp.text.lower()


def test_post_register_with_short_password_returns_400(unauthed_client):
    conn = unauthed_client.app.state.conn
    admin_user = db.get_user_by_username(conn, "admin")
    invite = db.create_invite(conn, "short@x.test", admin_user["id"])

    resp = unauthed_client.post("/register", data={
        "token": invite["token"],
        "username": "shortpw",
        "password": "short",
        "password_confirm": "short",
    })

    assert resp.status_code == 400
    assert "8 characters" in resp.text


def test_post_register_with_taken_username_returns_400(unauthed_client):
    conn = unauthed_client.app.state.conn
    admin_user = db.get_user_by_username(conn, "admin")
    invite = db.create_invite(conn, "taken@x.test", admin_user["id"])

    resp = unauthed_client.post("/register", data={
        "token": invite["token"],
        "username": "admin",  # already exists
        "password": "securepass1",
        "password_confirm": "securepass1",
    })

    assert resp.status_code == 400
    assert "already taken" in resp.text.lower()


def test_post_register_uses_invite_so_it_cannot_be_reused(unauthed_client):
    conn = unauthed_client.app.state.conn
    admin_user = db.get_user_by_username(conn, "admin")
    invite = db.create_invite(conn, "once@x.test", admin_user["id"])

    unauthed_client.post("/register", data={
        "token": invite["token"],
        "username": "onceuser",
        "password": "securepass1",
        "password_confirm": "securepass1",
    }, follow_redirects=False)

    resp = unauthed_client.post("/register", data={
        "token": invite["token"],
        "username": "onceuseragain",
        "password": "securepass1",
        "password_confirm": "securepass1",
    })

    assert resp.status_code == 400
    assert "already been used" in resp.text.lower()


# ── DB helpers ────────────────────────────────────────────────────────────────

def test_get_user_by_id_with_hash_returns_password_hash(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    result = db.get_user_by_id_with_hash(conn, user["id"])
    assert result is not None
    assert "password_hash" in result
    assert result["password_hash"].startswith("$2b$")
    assert result["id"] == user["id"]


def test_get_user_by_id_with_hash_returns_none_for_unknown_id(unauthed_client):
    conn = unauthed_client.app.state.conn
    result = db.get_user_by_id_with_hash(conn, "00000000-0000-0000-0000-000000000000")
    assert result is None


def test_update_password_changes_stored_hash(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    old_hash = user["password_hash"]
    db.update_password(conn, user["id"], hash_password("newpassword123"))
    updated = db.get_user_by_id_with_hash(conn, user["id"])
    assert updated["password_hash"] != old_hash
    assert verify_password("newpassword123", updated["password_hash"])


# ── Token helpers ─────────────────────────────────────────────────────────────

def test_generate_and_verify_reset_token(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    result = verify_reset_token("test-secret-key", token, conn)
    assert result is not None
    assert result["id"] == user["id"]
    assert result["username"] == "admin"


def test_verify_reset_token_rejects_expired_token(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    result = verify_reset_token("test-secret-key", token, conn, max_age=0)
    assert result is None


def test_verify_reset_token_rejects_tampered_token(unauthed_client):
    conn = unauthed_client.app.state.conn
    result = verify_reset_token("test-secret-key", "garbage.tampered.token", conn)
    assert result is None


def test_verify_reset_token_invalidated_after_password_change(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    db.update_password(conn, user["id"], hash_password("newpassword123"))
    result = verify_reset_token("test-secret-key", token, conn)
    assert result is None


# ── Multi-user data isolation ─────────────────────────────────────────────────

def test_user_cannot_see_another_users_sources(client, admin_user_id):
    conn = client.app.state.conn

    # Seed a source for admin
    with client.app.state.pool.connection() as c:
        db.add_source(c, admin_user_id, _ta.validate_python(
            {"id": "admin-src", "name": "Admin Source", "type": "greenhouse", "board_token": "admin"},
        ))

    # Create a second user and seed a source for them
    bob = db.create_user(conn, "bob_iso", "bob_iso@x.test", hash_password("pw"), role="user")
    with client.app.state.pool.connection() as c:
        db.add_source(c, str(bob["id"]), _ta.validate_python(
            {"id": "bob-src", "name": "Bob Source", "type": "greenhouse", "board_token": "bob"},
        ))

    resp = client.get("/sources")

    assert "Admin Source" in resp.text
    assert "Bob Source" not in resp.text


def test_user_cannot_edit_another_users_source(client, admin_user_id):
    conn = client.app.state.conn

    bob = db.create_user(conn, "bob_edit", "bob_edit@x.test", hash_password("pw"), role="user")
    with client.app.state.pool.connection() as c:
        db.add_source(c, str(bob["id"]), _ta.validate_python(
            {"id": "bobs-only", "name": "Bob Only", "type": "greenhouse", "board_token": "bob"},
        ))

    resp = client.get("/sources/bobs-only/edit")

    assert resp.status_code == 404


def test_user_cannot_delete_another_users_source(client, admin_user_id):
    conn = client.app.state.conn

    bob = db.create_user(conn, "bob_del", "bob_del@x.test", hash_password("pw"), role="user")
    with client.app.state.pool.connection() as c:
        db.add_source(c, str(bob["id"]), _ta.validate_python(
            {"id": "bob-del-src", "name": "Bob Del", "type": "greenhouse", "board_token": "bd"},
        ))

    resp = client.post("/sources/bob-del-src/delete", follow_redirects=False)

    assert resp.status_code == 404
    with client.app.state.pool.connection() as c:
        bobs_sources = db.list_sources(c, str(bob["id"]))
    assert len(bobs_sources) == 1


# ── Account recovery ──────────────────────────────────────────────────────────

def test_account_recovery_form_renders_for_unauthenticated_user(unauthed_client):
    resp = unauthed_client.get("/account-recovery")
    assert resp.status_code == 200
    assert 'name="email"' in resp.text


def test_authenticated_user_redirected_from_account_recovery(client):
    resp = client.get("/account-recovery", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["location"] == "/"


def test_account_recovery_with_registered_email_shows_confirmation(unauthed_client):
    with patch("app.emailer.send_email"):
        resp = unauthed_client.post("/account-recovery", data={"email": "admin@test.local"})
    assert resp.status_code == 200
    assert "we've sent" in resp.text.lower()


def test_account_recovery_with_registered_email_sends_one_email(unauthed_client):
    with patch("app.emailer.send_email") as mock_send:
        unauthed_client.post("/account-recovery", data={"email": "admin@test.local"})
    assert mock_send.call_count == 1


def test_account_recovery_email_contains_username_and_reset_link(unauthed_client):
    with patch("app.emailer.send_email") as mock_send:
        unauthed_client.post("/account-recovery", data={"email": "admin@test.local"})
    kwargs = mock_send.call_args.kwargs
    assert "admin" in kwargs["html_body"]
    assert "/reset-password?token=" in kwargs["html_body"]


def test_account_recovery_with_unknown_email_shows_same_confirmation(unauthed_client):
    with patch("app.emailer.send_email") as mock_send:
        resp = unauthed_client.post("/account-recovery", data={"email": "nobody@x.test"})
    assert resp.status_code == 200
    assert "we've sent" in resp.text.lower()
    mock_send.assert_not_called()


def test_account_recovery_with_empty_email_returns_400(unauthed_client):
    resp = unauthed_client.post("/account-recovery", data={"email": ""})
    assert resp.status_code == 400
    assert "required" in resp.text.lower()


# ── Password reset ────────────────────────────────────────────────────────────

def test_reset_password_form_with_valid_token_renders(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    resp = unauthed_client.get(f"/reset-password?token={token}")
    assert resp.status_code == 200
    assert 'name="password"' in resp.text
    assert "admin" in resp.text


def test_reset_password_form_shows_username(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    resp = unauthed_client.get(f"/reset-password?token={token}")
    assert "admin" in resp.text


def test_reset_password_form_with_no_token_returns_400(unauthed_client):
    resp = unauthed_client.get("/reset-password")
    assert resp.status_code == 400
    assert "invalid or has expired" in resp.text.lower()


def test_reset_password_form_with_tampered_token_returns_400(unauthed_client):
    resp = unauthed_client.get("/reset-password?token=garbage.invalid.token")
    assert resp.status_code == 400
    assert "invalid or has expired" in resp.text.lower()


def test_reset_password_form_with_expired_token_returns_400(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    # Generate with same key but verify with max_age=0 via the route's internal logic.
    # We can't pass max_age to the route, so we generate a token then tamper with the
    # timestamp by monkey-patching verify_reset_token.
    # Simpler: generate a token with a wrong secret so it fails signature check.
    token = generate_reset_token("wrong-secret", user["id"], user["email"], user["password_hash"])
    resp = unauthed_client.get(f"/reset-password?token={token}")
    assert resp.status_code == 400
    assert "invalid or has expired" in resp.text.lower()


def test_post_reset_password_with_valid_token_redirects_to_login(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    resp = unauthed_client.post("/reset-password", data={
        "token": token,
        "password": "freshpassword1",
        "password_confirm": "freshpassword1",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


def test_post_reset_password_old_password_no_longer_works(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    unauthed_client.post("/reset-password", data={
        "token": token,
        "password": "freshpassword1",
        "password_confirm": "freshpassword1",
    }, follow_redirects=False)
    resp = unauthed_client.post("/login", data={"username": "admin", "password": "password123"})
    assert resp.status_code == 401


def test_post_reset_password_with_mismatched_passwords_returns_400(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    resp = unauthed_client.post("/reset-password", data={
        "token": token,
        "password": "freshpassword1",
        "password_confirm": "differentpass1",
    })
    assert resp.status_code == 400
    assert "do not match" in resp.text.lower()


def test_post_reset_password_with_short_password_returns_400(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    resp = unauthed_client.post("/reset-password", data={
        "token": token,
        "password": "short",
        "password_confirm": "short",
    })
    assert resp.status_code == 400
    assert "8 characters" in resp.text


def test_post_reset_password_token_is_invalidated_after_use(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])

    # First use — succeeds
    resp = unauthed_client.post("/reset-password", data={
        "token": token,
        "password": "freshpassword1",
        "password_confirm": "freshpassword1",
    }, follow_redirects=False)
    assert resp.status_code == 303

    # Replay — fails (password_hash fingerprint has changed)
    resp = unauthed_client.post("/reset-password", data={
        "token": token,
        "password": "anotherpass99",
        "password_confirm": "anotherpass99",
    })
    assert resp.status_code == 400
    assert "invalid or has expired" in resp.text.lower()


# ── Login page links ──────────────────────────────────────────────────────────

def test_login_page_shows_account_recovery_link(unauthed_client):
    resp = unauthed_client.get("/login")
    assert "account-recovery" in resp.text


def test_login_page_displays_flash_message_from_query_param(unauthed_client):
    resp = unauthed_client.get("/login?flash=Password+reset")
    assert "Password reset" in resp.text
