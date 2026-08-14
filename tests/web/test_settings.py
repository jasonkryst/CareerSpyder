def test_settings_redirects_to_email_tab(client):
    resp = client.get("/settings", follow_redirects=False)
    assert resp.status_code in (301, 302, 303, 307, 308)
    assert resp.headers["location"] == "/settings/email"


def test_settings_page_shows_current_values(client):
    resp = client.get("/settings/email")
    assert resp.status_code == 200
    assert 'value="smtp.example.com"' in resp.text


def test_settings_page_does_not_expose_password_field(client):
    resp = client.get("/settings/email")
    assert 'name="smtp_password"' not in resp.text
    assert 'name="password"' not in resp.text


def test_post_settings_saves_new_values(client):
    resp = client.post("/settings/email", data={
        "smtp_host": "smtp2.example.com", "smtp_port": "465",
        "smtp_user": "user2", "email_from": "from2@x.test", "email_to": "to2@x.test",
    }, follow_redirects=False)

    assert resp.status_code == 303

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["smtp_host"] == "smtp2.example.com"
    assert settings["smtp_port"] == 465


def test_post_settings_rejects_file_upload_field(client):
    resp = client.post(
        "/settings/email",
        data={"smtp_port": "465", "smtp_user": "user2", "email_from": "from2@x.test", "email_to": "to2@x.test"},
        files={"smtp_host": ("evil.txt", b"not a hostname")},
    )

    assert resp.status_code == 400
