def test_post_without_origin_or_sec_fetch_site_headers_is_allowed(client):
    resp = client.post("/sources/test-preview", data={"type": "greenhouse", "name": "Acme", "board_token": ""})
    assert resp.status_code == 200


def test_post_with_matching_origin_is_allowed(client):
    resp = client.post(
        "/sources/test-preview",
        data={"type": "greenhouse", "name": "Acme", "board_token": ""},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200


def test_post_with_mismatched_origin_is_blocked(client):
    resp = client.post(
        "/sources/test-preview",
        data={"type": "greenhouse", "name": "Acme", "board_token": ""},
        headers={"Origin": "https://attacker.test"},
    )
    assert resp.status_code == 403


def test_post_with_sec_fetch_site_cross_site_is_blocked(client):
    resp = client.post(
        "/sources/test-preview",
        data={"type": "greenhouse", "name": "Acme", "board_token": ""},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert resp.status_code == 403


def test_post_with_sec_fetch_site_same_origin_is_allowed(client):
    resp = client.post(
        "/sources/test-preview",
        data={"type": "greenhouse", "name": "Acme", "board_token": ""},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert resp.status_code == 200


def test_sec_fetch_site_takes_precedence_over_a_mismatched_origin(client):
    """Real browsers send both headers together and consistently; Sec-Fetch-Site
    is the more precise signal, so the middleware trusts it first when present."""
    resp = client.post(
        "/sources/test-preview",
        data={"type": "greenhouse", "name": "Acme", "board_token": ""},
        headers={"Sec-Fetch-Site": "same-origin", "Origin": "https://attacker.test"},
    )
    assert resp.status_code == 200


def test_get_request_is_never_blocked_regardless_of_origin(client):
    resp = client.get("/", headers={"Origin": "https://attacker.test"})
    assert resp.status_code == 200


def test_cross_origin_blocked_response_has_no_security_header_regression(client):
    resp = client.post(
        "/sources/test-preview",
        data={"type": "greenhouse", "name": "Acme", "board_token": ""},
        headers={"Origin": "https://attacker.test"},
    )
    assert resp.status_code == 403
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
