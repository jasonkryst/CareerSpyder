"""Tests for /users: listing, inviting, and deactivating users."""


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
