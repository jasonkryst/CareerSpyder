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
