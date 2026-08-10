def test_settings_page_shows_current_values(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert 'value="smtp.example.com"' in resp.text


def test_settings_page_does_not_expose_password_field(client):
    resp = client.get("/settings")
    assert 'name="smtp_password"' not in resp.text
    assert 'name="password"' not in resp.text


def test_post_settings_saves_new_values(client):
    resp = client.post("/settings", data={
        "smtp_host": "smtp2.example.com", "smtp_port": "465",
        "smtp_user": "user2", "email_from": "from2@x.test", "email_to": "to2@x.test",
    }, follow_redirects=False)

    assert resp.status_code == 303

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["smtp_host"] == "smtp2.example.com"
    assert settings["smtp_port"] == 465
