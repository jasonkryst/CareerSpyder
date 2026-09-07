def test_csp_allows_openstreetmap_tile_images(client):
    resp = client.get("/")
    assert "https://*.tile.openstreetmap.org" in resp.headers["Content-Security-Policy"]


def test_html_response_carries_baseline_security_headers(client):
    resp = client.get("/")

    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "same-origin"
    assert "default-src 'self'" in resp.headers["Content-Security-Policy"]


def test_static_asset_response_carries_baseline_security_headers(client):
    resp = client.get("/static/style.css")

    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"


def test_json_response_carries_baseline_security_headers(client):
    resp = client.post("/sources/test-preview", data={"type": "greenhouse", "name": "Acme", "board_token": ""})

    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"


def test_error_response_carries_baseline_security_headers(client):
    resp = client.get("/sources/does-not-exist/edit")

    assert resp.status_code == 404
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"


def test_csp_excludes_google_domains_when_ga_unset(client):
    resp = client.get("/")

    csp = resp.headers["Content-Security-Policy"]
    assert "googletagmanager.com" not in csp
    assert "google-analytics.com" not in csp


def test_csp_allows_google_analytics_domains_when_ga_set(client, monkeypatch):
    monkeypatch.setenv("GA_MEASUREMENT_ID", "G-TEST12345")

    resp = client.get("/")

    csp = resp.headers["Content-Security-Policy"]
    assert "script-src 'self' 'unsafe-inline' https://www.googletagmanager.com" in csp
    assert "connect-src 'self' https://*.google-analytics.com https://*.analytics.google.com" in csp
