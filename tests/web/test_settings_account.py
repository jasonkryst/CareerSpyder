"""Tests for the Account settings tab: change-password form."""
from app import db
from app.web.auth import verify_password

# ── GET /settings/account ─────────────────────────────────────────────────────

def test_settings_account_renders_for_admin(client):
    resp = client.get("/settings/account")
    assert resp.status_code == 200
    assert 'name="current_password"' in resp.text
    assert 'name="new_password"' in resp.text
    assert 'name="new_password_confirm"' in resp.text


def test_settings_account_renders_for_member(member_client):
    resp = member_client.get("/settings/account")
    assert resp.status_code == 200
    assert 'name="current_password"' in resp.text


def test_settings_account_unauthenticated_redirects_to_login(unauthed_client):
    resp = unauthed_client.get("/settings/account", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


def test_settings_account_shows_account_tab_as_current(client):
    resp = client.get("/settings/account")
    assert resp.status_code == 200
    assert "Account" in resp.text


# ── POST /settings/account/password ──────────────────────────────────────────

def test_change_password_with_correct_current_password_succeeds(client):
    conn = client.app.state.conn
    resp = client.post("/settings/account/password", data={
        "current_password": "password123",
        "new_password": "newpassword99",
        "new_password_confirm": "newpassword99",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "/settings/account" in resp.headers["location"]
    user = db.get_user_by_username(conn, "admin")
    assert verify_password("newpassword99", user["password_hash"])


def test_change_password_with_wrong_current_password_returns_400(client):
    resp = client.post("/settings/account/password", data={
        "current_password": "wrongpassword",
        "new_password": "newpassword99",
        "new_password_confirm": "newpassword99",
    })
    assert resp.status_code == 400
    assert "incorrect" in resp.text.lower()


def test_change_password_with_mismatched_new_passwords_returns_400(client):
    resp = client.post("/settings/account/password", data={
        "current_password": "password123",
        "new_password": "newpassword99",
        "new_password_confirm": "differentpass99",
    })
    assert resp.status_code == 400
    assert "do not match" in resp.text.lower()


def test_change_password_with_short_new_password_returns_400(client):
    resp = client.post("/settings/account/password", data={
        "current_password": "password123",
        "new_password": "short",
        "new_password_confirm": "short",
    })
    assert resp.status_code == 400
    assert "8 characters" in resp.text


def test_change_password_unauthenticated_redirects_to_login(unauthed_client):
    resp = unauthed_client.post("/settings/account/password", data={
        "current_password": "password123",
        "new_password": "newpassword99",
        "new_password_confirm": "newpassword99",
    }, follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers["location"]
