def test_guide_page_returns_200(client):
    resp = client.get("/guide")

    assert resp.status_code == 200
    assert "Usage Guide" in resp.text


def test_guide_nav_link_marks_current_page(client):
    resp = client.get("/guide")

    assert 'href="/guide" aria-current="page"' in resp.text
    assert 'href="/" aria-current="page"' not in resp.text
