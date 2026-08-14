from importlib.metadata import version


def test_footer_shows_app_name_and_version(client):
    resp = client.get("/")

    assert resp.status_code == 200
    assert "CareerSpyder" in resp.text
    assert f"v{version('careerspyder')}" in resp.text


def test_base_layout_has_viewport_lang_and_skip_link(client):
    resp = client.get("/")

    assert '<html lang="en">' in resp.text
    assert 'name="viewport"' in resp.text
    assert 'class="skip-link"' in resp.text


def test_nav_marks_current_page_with_aria_current(client):
    resp = client.get("/history")

    assert 'href="/history" aria-current="page"' in resp.text
    assert 'href="/" aria-current="page"' not in resp.text


def test_theme_toggle_button_present(client):
    resp = client.get("/")

    assert 'id="theme-toggle"' in resp.text
    assert 'aria-pressed="false"' in resp.text


def test_style_css_defines_modernized_tokens(client):
    resp = client.get("/static/style.css")

    assert resp.status_code == 200
    assert "--accent: #b3101f" in resp.text
    assert "--radius" in resp.text
    assert "--space-4" in resp.text
    assert ".card {" in resp.text
    assert ".btn-primary {" in resp.text
    assert ".brand" in resp.text


def test_static_assets_are_served(client):
    css = client.get("/static/style.css")
    js = client.get("/static/theme.js")

    assert css.status_code == 200
    assert "prefers-color-scheme" in css.text
    assert js.status_code == 200
    assert "localStorage" in js.text
