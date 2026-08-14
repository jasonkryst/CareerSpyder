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
        "smtp_user": "user2", "email_from": "from2@x.test",
    }, follow_redirects=False)

    assert resp.status_code == 303

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["smtp_host"] == "smtp2.example.com"
    assert settings["smtp_port"] == 465


def test_post_settings_rejects_file_upload_field(client):
    resp = client.post(
        "/settings/email",
        data={"smtp_port": "465", "smtp_user": "user2", "email_from": "from2@x.test"},
        files={"smtp_host": ("evil.txt", b"not a hostname")},
    )

    assert resp.status_code == 400


def test_settings_email_page_has_no_recipient_field(client):
    resp = client.get("/settings/email")

    assert 'name="email_to"' not in resp.text


def test_settings_preferences_page_shows_theme_radios(client):
    resp = client.get("/settings/preferences")

    assert resp.status_code == 200
    assert 'name="theme" value="light"' in resp.text
    assert 'name="theme" value="dark"' in resp.text
    assert 'name="theme" value="system"' in resp.text


def test_settings_tabs_include_preferences_link(client):
    resp = client.get("/settings/preferences")

    assert 'href="/settings/preferences" aria-current="page"' in resp.text
    assert 'href="/settings/email"' in resp.text
    assert 'href="/settings/data"' in resp.text


def test_settings_email_save_button_is_primary(client):
    resp = client.get("/settings/email")

    assert 'class="btn-primary"' in resp.text


def test_settings_email_form_wrapped_in_card(client):
    resp = client.get("/settings/email")

    assert 'class="card"' in resp.text


def test_settings_email_has_no_br_tags(client):
    resp = client.get("/settings/email")

    assert "<br>" not in resp.text


def test_settings_data_page_wraps_sections_in_cards(client):
    resp = client.get("/settings/data")

    assert resp.text.count('class="card"') == 2


def test_settings_data_has_no_br_tags(client):
    resp = client.get("/settings/data")

    assert "<br>" not in resp.text


def test_settings_data_page_shows_data_tab_controls(client):
    resp = client.get("/settings/data")

    assert resp.status_code == 200
    assert 'action="/settings/data/clear-cache"' in resp.text
    assert 'href="/settings/data/sources/export"' in resp.text
    assert 'action="/settings/data/sources/import"' in resp.text
    assert 'name="file"' in resp.text


def test_post_clear_cache_empties_jobs_and_redirects(client):
    from app import db
    from app.models import Job

    conn = client.app.state.conn
    job = Job(key="k1", title="Engineer", url="https://x.test/1", source_name="Acme")
    run_id = db.start_run(conn)
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])
    assert db.get_new_jobs(conn, [job]) == []

    resp = client.post("/settings/data/clear-cache", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings/data?cleared=1"
    assert db.get_new_jobs(conn, [job]) == [job]


def test_settings_data_page_shows_success_banner_after_clear(client):
    resp = client.get("/settings/data?cleared=1")

    assert resp.status_code == 200
    assert "Job cache cleared" in resp.text


def test_get_export_sources_returns_current_sources_as_download(client):
    import json

    from app import config

    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.add_source(client.app.state.sources_path, source)

    resp = client.get("/settings/data/sources/export")

    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert "sources.json" in resp.headers["content-disposition"]
    assert json.loads(resp.text) == {"sources": [source.model_dump()]}


def test_post_import_sources_replaces_list_and_redirects(client):
    import json

    from app import config

    payload = json.dumps({
        "sources": [{"id": "new", "name": "New", "type": "lever", "board_token": "new"}],
    }).encode()

    resp = client.post(
        "/settings/data/sources/import",
        files={"file": ("sources.json", payload, "application/json")},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings/data?imported=1"
    assert [s.id for s in config.load_sources(client.app.state.sources_path)] == ["new"]


def test_settings_data_page_shows_success_banner_after_import(client):
    resp = client.get("/settings/data?imported=3")

    assert resp.status_code == 200
    assert "Imported 3 source(s)" in resp.text


def test_post_import_sources_with_no_file_returns_400(client):
    resp = client.post("/settings/data/sources/import", data={})

    assert resp.status_code == 400
    assert "Choose a file" in resp.text


def test_post_import_sources_with_invalid_json_returns_400_and_leaves_sources(client):
    from app import config

    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.add_source(client.app.state.sources_path, source)

    resp = client.post(
        "/settings/data/sources/import",
        files={"file": ("bad.json", b"not json", "application/json")},
    )

    assert resp.status_code == 400
    assert [s.id for s in config.load_sources(client.app.state.sources_path)] == ["s1"]


def test_post_import_sources_with_unknown_type_returns_400_and_leaves_sources(client):
    import json

    from app import config

    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.add_source(client.app.state.sources_path, source)
    payload = json.dumps({"sources": [{"id": "x", "name": "X", "type": "carrier_pigeon"}]}).encode()

    resp = client.post(
        "/settings/data/sources/import",
        files={"file": ("bad.json", payload, "application/json")},
    )

    assert resp.status_code == 400
    assert [s.id for s in config.load_sources(client.app.state.sources_path)] == ["s1"]
