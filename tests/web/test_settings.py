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


def test_post_settings_redirect_carries_saved_flash_message(client):
    from urllib.parse import parse_qs, urlparse

    resp = client.post("/settings/email", data={
        "smtp_host": "smtp2.example.com", "smtp_port": "465",
        "smtp_user": "user2", "email_from": "from2@x.test",
    }, follow_redirects=False)

    location = urlparse(resp.headers["location"])
    assert location.path == "/settings/email"
    assert parse_qs(location.query)["flash"] == ["Email settings saved."]


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


def test_settings_preferences_page_shows_all_day_checkboxes(client):
    resp = client.get("/settings/preferences")

    assert resp.status_code == 200
    for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        assert f'name="email_days" value="{day}"' in resp.text


def test_settings_preferences_page_prechecks_stored_days(client):
    from app import db
    db.save_preferences(client.app.state.conn, "mon,wed,fri", False, "to@x.test")

    resp = client.get("/settings/preferences")

    assert 'value="mon" checked' in resp.text
    assert 'value="wed" checked' in resp.text
    assert 'value="tue" checked' not in resp.text


def test_settings_preferences_page_shows_resend_checkbox(client):
    resp = client.get("/settings/preferences")

    assert 'name="resend_jobs"' in resp.text


def test_settings_preferences_page_shows_hide_not_interested_checkbox_checked_by_default(client):
    resp = client.get("/settings/preferences")

    assert 'name="hide_not_interested_on_map" checked' in resp.text


def test_settings_preferences_page_unchecks_hide_not_interested_when_turned_off(client):
    from app import db
    db.save_preferences(
        client.app.state.conn, "mon,tue,wed,thu,fri,sat,sun", False, "to@x.test",
        hide_not_interested_on_map=False,
    )

    resp = client.get("/settings/preferences")

    assert 'name="hide_not_interested_on_map" checked' not in resp.text


def test_settings_preferences_page_shows_stored_recipients(client):
    from app import db
    db.save_preferences(client.app.state.conn, "mon,tue,wed,thu,fri,sat,sun", False, "a@x.test,b@x.test")

    resp = client.get("/settings/preferences")

    assert 'value="a@x.test"' in resp.text
    assert 'value="b@x.test"' in resp.text


def test_settings_preferences_page_shows_a_blank_recipient_row_when_none_stored(client):
    resp = client.get("/settings/preferences")

    assert 'placeholder="name@example.com"' in resp.text
    assert 'value="a@x.test"' not in resp.text


def test_settings_preferences_page_wraps_sections_in_cards(client):
    resp = client.get("/settings/preferences")

    assert resp.text.count('class="card"') == 5


def test_post_preferences_saves_days_resend_and_recipients(client):
    resp = client.post("/settings/preferences", data={
        "email_days": ["mon", "wed", "fri"],
        "resend_jobs": "on",
        "email_to": ["a@x.test", "b@x.test"],
    }, follow_redirects=False)

    assert resp.status_code == 303

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_days"] == "mon,wed,fri"
    assert settings["resend_jobs"] is True
    assert settings["email_to"] == "a@x.test,b@x.test"


def test_post_preferences_redirect_carries_saved_flash_message(client):
    from urllib.parse import parse_qs, urlparse

    resp = client.post("/settings/preferences", data={
        "email_days": ["mon", "wed", "fri"],
        "resend_jobs": "on",
        "email_to": ["a@x.test", "b@x.test"],
    }, follow_redirects=False)

    location = urlparse(resp.headers["location"])
    assert location.path == "/settings/preferences"
    assert parse_qs(location.query)["flash"] == ["Preferences saved."]


def test_post_preferences_unchecked_resend_is_stored_as_false(client):
    client.post("/settings/preferences", data={"email_days": ["mon"], "email_to": ["a@x.test"]})

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["resend_jobs"] is False


def test_post_preferences_saves_hide_not_interested_on_map_when_checked(client):
    resp = client.post("/settings/preferences", data={
        "email_days": ["mon"],
        "email_to": ["a@x.test"],
        "hide_not_interested_on_map": "on",
    }, follow_redirects=False)

    assert resp.status_code == 303
    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["hide_not_interested_on_map"] is True


def test_post_preferences_unchecked_hide_not_interested_is_stored_as_false(client):
    client.post("/settings/preferences", data={"email_days": ["mon"], "email_to": ["a@x.test"]})

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["hide_not_interested_on_map"] is False


def test_post_preferences_drops_blank_recipient_rows(client):
    client.post("/settings/preferences", data={"email_days": ["mon"], "email_to": ["a@x.test", "", "  "]})

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_to"] == "a@x.test"


def test_post_preferences_rejects_file_upload_field(client):
    resp = client.post(
        "/settings/preferences",
        data={"email_days": ["mon"]},
        files={"email_to": ("evil.txt", b"not an email")},
    )

    assert resp.status_code == 400


def test_preferences_js_is_served(client):
    resp = client.get("/static/preferences.js")

    assert resp.status_code == 200


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
    assert 'href="/settings/data/export"' in resp.text
    assert 'action="/settings/data/import"' in resp.text
    assert 'name="file"' in resp.text


def test_post_clear_cache_empties_jobs_and_redirects(client):
    from urllib.parse import parse_qs, urlparse

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
    location = urlparse(resp.headers["location"])
    assert location.path == "/settings/data"
    assert parse_qs(location.query)["flash"] == [
        "Job cache cleared. The next run will re-report every currently known job as new."
    ]
    assert db.get_new_jobs(conn, [job]) == [job]


def test_post_clear_cache_shows_toast_after_redirect(client):
    resp = client.post("/settings/data/clear-cache")

    assert resp.status_code == 200
    assert 'class="toast" role="status"' in resp.text
    assert "Job cache cleared" in resp.text


def test_get_export_settings_returns_sources_and_preferences_as_download(client):
    import json

    from app import config

    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.add_source(client.app.state.sources_path, source)

    resp = client.get("/settings/data/export")

    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert "settings.json" in resp.headers["content-disposition"]
    body = json.loads(resp.text)
    assert body["sources"] == [source.model_dump()]
    assert body["preferences"] == {
        "email_days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "resend_jobs": False,
        "email_to": ["to@x.test"],
        "hide_not_interested_on_map": True,
    }


def test_post_import_settings_replaces_sources_and_redirects(client):
    import json
    from urllib.parse import parse_qs, urlparse

    from app import config

    payload = json.dumps({
        "sources": [{"id": "new", "name": "New", "type": "lever", "board_token": "new"}],
    }).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    location = urlparse(resp.headers["location"])
    assert location.path == "/settings/data"
    assert parse_qs(location.query)["flash"] == ["Imported 1 source(s)."]
    assert [s.id for s in config.load_sources(client.app.state.sources_path)] == ["new"]


def test_post_import_settings_with_preferences_overwrites_stored_preferences(client):
    import json
    from urllib.parse import parse_qs, urlparse

    from app import db

    db.save_preferences(client.app.state.conn, "mon", True, "old@x.test")
    payload = json.dumps({
        "sources": [],
        "preferences": {
            "email_days": ["tue", "thu"],
            "resend_jobs": False,
            "email_to": ["new@x.test"],
        },
    }).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    location = urlparse(resp.headers["location"])
    assert location.path == "/settings/data"
    assert parse_qs(location.query)["flash"] == ["Imported 0 source(s) and preferences."]
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_days"] == "tue,thu"
    assert settings["resend_jobs"] is False
    assert settings["email_to"] == "new@x.test"


def test_post_import_settings_with_preferences_imports_hide_not_interested_on_map(client):
    import json
    from urllib.parse import urlparse

    from app import db

    db.save_preferences(
        client.app.state.conn, "mon", True, "old@x.test", hide_not_interested_on_map=True,
    )
    payload = json.dumps({
        "sources": [],
        "preferences": {
            "email_days": ["tue"], "resend_jobs": False, "email_to": ["new@x.test"],
            "hide_not_interested_on_map": False,
        },
    }).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert urlparse(resp.headers["location"]).path == "/settings/data"
    settings = db.get_settings(client.app.state.conn)
    assert settings["hide_not_interested_on_map"] is False


def test_post_import_settings_with_malformed_hide_not_interested_falls_back_to_true(client):
    import json

    from app import db

    db.save_preferences(
        client.app.state.conn, "mon", True, "old@x.test", hide_not_interested_on_map=False,
    )
    payload = json.dumps({
        "sources": [],
        "preferences": {
            "email_days": ["tue"], "resend_jobs": False, "email_to": ["new@x.test"],
            "hide_not_interested_on_map": "yes",
        },
    }).encode()

    client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
        follow_redirects=False,
    )

    settings = db.get_settings(client.app.state.conn)
    assert settings["hide_not_interested_on_map"] is True


def test_post_import_settings_without_preferences_key_leaves_stored_preferences_untouched(client):
    import json
    from urllib.parse import parse_qs, urlparse

    from app import db

    db.save_preferences(client.app.state.conn, "mon", True, "old@x.test")
    payload = json.dumps({"sources": []}).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    location = urlparse(resp.headers["location"])
    assert location.path == "/settings/data"
    assert parse_qs(location.query)["flash"] == ["Imported 0 source(s)."]
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_days"] == "mon"
    assert settings["resend_jobs"] is True
    assert settings["email_to"] == "old@x.test"


def test_post_import_settings_with_malformed_preferences_falls_back_to_defaults(client):
    import json

    from app import db

    db.save_preferences(client.app.state.conn, "mon", True, "old@x.test")
    payload = json.dumps({
        "sources": [],
        "preferences": {"email_days": "mon", "resend_jobs": "yes", "email_to": "not-a-list@x.test"},
    }).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_days"] == ""
    assert settings["resend_jobs"] is False
    assert settings["email_to"] == ""


def test_post_import_settings_with_preferences_shows_toast_after_redirect(client):
    import json

    payload = json.dumps({
        "sources": [{"id": "s1", "name": "A", "type": "greenhouse", "board_token": "a"},
                    {"id": "s2", "name": "B", "type": "greenhouse", "board_token": "b"},
                    {"id": "s3", "name": "C", "type": "greenhouse", "board_token": "c"}],
        "preferences": {"email_days": ["mon"], "resend_jobs": False, "email_to": ["a@x.test"]},
    }).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
    )

    assert resp.status_code == 200
    assert "Imported 3 source(s) and preferences." in resp.text


def test_post_import_settings_without_preferences_shows_toast_after_redirect(client):
    import json

    payload = json.dumps({
        "sources": [{"id": "s1", "name": "A", "type": "greenhouse", "board_token": "a"},
                    {"id": "s2", "name": "B", "type": "greenhouse", "board_token": "b"},
                    {"id": "s3", "name": "C", "type": "greenhouse", "board_token": "c"}],
    }).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
    )

    assert resp.status_code == 200
    assert "Imported 3 source(s)." in resp.text
    assert "and preferences" not in resp.text


def test_post_import_settings_with_no_file_returns_400(client):
    resp = client.post("/settings/data/import", data={})

    assert resp.status_code == 400
    assert "Choose a file" in resp.text


def test_post_import_settings_with_invalid_json_returns_400_and_leaves_sources(client):
    from app import config

    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.add_source(client.app.state.sources_path, source)

    resp = client.post(
        "/settings/data/import",
        files={"file": ("bad.json", b"not json", "application/json")},
    )

    assert resp.status_code == 400
    assert 'class="toast" role="status"' not in resp.text
    assert [s.id for s in config.load_sources(client.app.state.sources_path)] == ["s1"]


def test_settings_data_import_form_has_confirm_guard(client):
    resp = client.get("/settings/data")

    assert 'id="import-form"' in resp.text
    assert 'data-confirm-message="Importing will replace your entire source list. Continue?"' in resp.text
    assert "confirm(" not in resp.text


def test_post_preferences_rejects_malformed_email_and_does_not_save(client):
    resp = client.post("/settings/preferences", data={
        "email_days": ["mon"], "email_to": ["not-an-email"],
    })

    assert resp.status_code == 400
    assert "Invalid email address" in resp.text
    assert 'class="toast" role="status"' not in resp.text

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings is None or settings["email_to"] != "not-an-email"


def test_post_preferences_accepts_well_formed_emails(client):
    resp = client.post("/settings/preferences", data={
        "email_days": ["mon"], "email_to": ["good@x.test"],
    }, follow_redirects=False)

    assert resp.status_code == 303

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_to"] == "good@x.test"


def test_post_preferences_invalid_email_preserves_submitted_days_and_addresses(client):
    resp = client.post("/settings/preferences", data={
        "email_days": ["mon", "wed"], "email_to": ["good@x.test", "not-an-email"],
    })

    assert resp.status_code == 400
    assert 'value="good@x.test"' in resp.text
    assert 'value="mon" checked' in resp.text
    assert 'value="wed" checked' in resp.text


def test_settings_preferences_recipient_inputs_are_required(client):
    resp = client.get("/settings/preferences")

    assert resp.text.count(" required") >= 2


def test_post_import_settings_with_malformed_email_drops_it_but_keeps_others(client):
    import json

    payload = json.dumps({
        "sources": [],
        "preferences": {
            "email_days": ["mon"],
            "resend_jobs": False,
            "email_to": ["good@x.test", "not-an-email"],
        },
    }).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("settings.json", payload, "application/json")},
        follow_redirects=False,
    )

    assert resp.status_code == 303

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_to"] == "good@x.test"


def test_post_import_settings_with_unknown_source_type_returns_400_and_leaves_sources(client):
    import json

    from app import config

    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.add_source(client.app.state.sources_path, source)
    payload = json.dumps({"sources": [{"id": "x", "name": "X", "type": "carrier_pigeon"}]}).encode()

    resp = client.post(
        "/settings/data/import",
        files={"file": ("bad.json", payload, "application/json")},
    )

    assert resp.status_code == 400
    assert [s.id for s in config.load_sources(client.app.state.sources_path)] == ["s1"]
