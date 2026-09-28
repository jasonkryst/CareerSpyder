from fastapi.testclient import TestClient

from app import db
from app.web.auth import generate_reset_token


def _second_browser(client) -> TestClient:
    other = TestClient(client.app)
    other.cookies.set("session", client.cookies.get("session"))
    return other


def test_changing_password_logs_out_other_sessions(member_client):
    other = _second_browser(member_client)
    assert other.get("/jobs", follow_redirects=False).status_code == 200
    resp = member_client.post("/settings/account/password", data={
        "current_password": "member123", "new_password": "newpass123", "new_password_confirm": "newpass123",
    }, follow_redirects=False)
    assert resp.status_code == 303
    stale = other.get("/jobs", follow_redirects=False)
    assert stale.status_code == 303 and stale.headers["location"] == "/login"
    assert member_client.get("/jobs", follow_redirects=False).status_code == 200


def test_password_reset_logs_out_existing_sessions(member_client, member_user_id):
    with member_client.app.state.pool.connection() as conn:
        user = db.get_user_by_id_with_hash(conn, member_user_id)
    token = generate_reset_token(member_client.app.state.secret_key, user["id"], user["email"], user["password_hash"])
    anon = TestClient(member_client.app)
    anon.post("/reset-password", data={"token": token, "password": "resetpass1", "password_confirm": "resetpass1"})
    resp = member_client.get("/jobs", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/login"


def test_stale_session_login_form_shows_form_not_redirect(member_client, member_user_id):
    # A session whose password fingerprint is stale (password changed on another
    # client) must not redirect GET /login to "/" -- request.state.user is None
    # for it (set by UserContextMiddleware after the fingerprint check), even
    # though the raw session cookie still carries a user_id.
    from app.web.auth import hash_password

    other = _second_browser(member_client)
    with member_client.app.state.pool.connection() as conn:
        db.update_password(conn, member_user_id, hash_password("changed12345"))
    resp = other.get("/login", follow_redirects=False)
    assert resp.status_code == 200


def test_legacy_session_without_fingerprint_is_logged_out(member_client, member_user_id, monkeypatch):
    # A cookie minted before this change carries only user_id (same encoding
    # as starlette.middleware.sessions: base64(json) signed with TimestampSigner).
    import base64
    import json

    from itsdangerous import TimestampSigner
    signer = TimestampSigner(member_client.app.state.secret_key)
    legacy = signer.sign(base64.b64encode(json.dumps({"user_id": member_user_id}).encode())).decode()
    other = TestClient(member_client.app)
    other.cookies.set("session", legacy)
    resp = other.get("/jobs", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/login"
