"""Tests for /users: listing, inviting, and deactivating users."""

import re


def test_users_page_shows_source_and_job_counts_per_user(client, admin_user_id):
    from app import db
    from app.config import GreenhouseSource

    with client.app.state.pool.connection() as conn:
        db.add_source(conn, admin_user_id, GreenhouseSource(
            id="s1", name="S1", type="greenhouse", board_token="s1",
        ))

    resp = client.get("/users")
    assert resp.status_code == 200
    assert '<th scope="col">Sources</th>' in resp.text
    assert '<th scope="col">Jobs</th>' in resp.text


def test_invite_link_uses_public_base_url_not_the_host_header(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://jobs.example.com")
    resp = client.post(
        "/users/invite", data={"email": "new@test.local"}, headers={"Host": "evil.example"},
    )
    assert resp.status_code == 200
    assert "https://jobs.example.com/register?token=" in resp.text
    assert "evil.example" not in resp.text


def test_invite_link_falls_back_to_request_base_url_without_public_base_url(client, monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    resp = client.post("/users/invite", data={"email": "new2@test.local"})
    assert resp.status_code == 200
    assert "http://testserver/register?token=" in resp.text


def _invite_token(client, email: str) -> str:
    from app import db
    with client.app.state.pool.connection() as conn:
        admin = db.get_user_by_username(conn, "admin")
        invite = db.create_invite(conn, email, admin["id"])
    return str(invite["token"])


def test_pending_invite_appears_on_users_page_with_a_copy_link(client):
    token = _invite_token(client, "pending@test.local")

    resp = client.get("/users")

    assert resp.status_code == 200
    assert "pending@test.local" in resp.text
    assert f"/register?token={token}" in resp.text


def test_revoke_invite_route_expires_it_and_removes_its_copy_link(client):
    token = _invite_token(client, "revoke-me@test.local")

    resp = client.post(f"/users/invites/{token}/revoke", follow_redirects=False)
    assert resp.status_code == 303

    page = client.get("/users")
    assert f"/register?token={token}" not in page.text


def test_revoke_unknown_invite_returns_404(client):
    resp = client.post("/users/invites/00000000-0000-0000-0000-000000000000/revoke")
    assert resp.status_code == 404


def test_resend_invite_route_shows_a_new_link_and_invalidates_the_old_one(client):
    old_token = _invite_token(client, "resend-me@test.local")

    resp = client.post("/users/invite/resend", data={"token": old_token})
    assert resp.status_code == 200
    assert "resend-me@test.local" in resp.text

    new_token_match = re.search(r"/register\?token=([0-9a-f-]+)", resp.text)
    assert new_token_match is not None
    new_token = new_token_match.group(1)
    assert new_token != old_token

    from datetime import UTC, datetime

    from app import db
    with client.app.state.pool.connection() as conn:
        old_invite = db.get_invite(conn, old_token)
        assert old_invite is not None
        assert datetime.fromisoformat(old_invite["expires_at"]) <= datetime.now(UTC)
        assert db.claim_invite(conn, new_token) is True


def test_resend_unknown_invite_returns_404(client):
    resp = client.post("/users/invite/resend", data={"token": "00000000-0000-0000-0000-000000000000"})
    assert resp.status_code == 404


def test_non_admin_cannot_revoke_or_resend_invites(member_client):
    token = "00000000-0000-0000-0000-000000000000"
    assert member_client.post(f"/users/invites/{token}/revoke").status_code == 403
    assert member_client.post("/users/invite/resend", data={"token": token}).status_code == 403
