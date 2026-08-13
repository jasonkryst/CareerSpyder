import json


def test_new_source_form_renders(client):
    resp = client.get("/sources/new")
    assert resp.status_code == 200
    assert "Add source" in resp.text


def test_post_new_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "greenhouse", "name": "Acme", "company": "Acme Corp", "board_token": "acme",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/sources"
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["name"] == "Acme"
    assert saved[0]["board_token"] == "acme"


def test_edit_form_prefills_existing_values(client):
    with open(client.app.state.sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.get("/sources/s1/edit")

    assert resp.status_code == 200
    assert 'value="Acme"' in resp.text


def test_post_new_infor_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "infor", "name": "Rush (Infor)", "company": "Rush University Medical Center",
        "infor_url": "https://rush.test/careers", "max_pages": "5",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["type"] == "infor"
    assert saved[0]["url"] == "https://rush.test/careers"
    assert saved[0]["max_pages"] == 5


def test_post_new_infor_source_with_empty_url_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "infor", "name": "Rush (Infor)", "infor_url": "",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    with open(client.app.state.sources_path) as f:
        assert json.load(f)["sources"] == []


def test_post_edit_updates_existing_source(client):
    with open(client.app.state.sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.post("/sources/s1/edit", data={
        "id": "s1", "type": "greenhouse", "name": "Acme Renamed", "board_token": "acme",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["name"] == "Acme Renamed"
    assert saved[0]["id"] == "s1"


def test_post_new_source_with_empty_board_token_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "greenhouse", "name": "Acme", "company": "Acme Corp", "board_token": "",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    assert "Add source" in resp.text
    with open(client.app.state.sources_path) as f:
        assert json.load(f)["sources"] == []


def test_post_new_source_with_empty_job_card_selector_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "generic_html", "name": "Custom Co", "url": "https://customco.test/careers",
        "selector_job_card": "", "selector_title": ".t", "selector_link": "a",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    with open(client.app.state.sources_path) as f:
        assert json.load(f)["sources"] == []


def test_edit_unknown_source_returns_404(client):
    resp = client.get("/sources/does-not-exist/edit")
    assert resp.status_code == 404


def test_post_edit_unknown_source_returns_404(client):
    resp = client.post("/sources/does-not-exist/edit", data={
        "type": "greenhouse", "name": "Acme", "board_token": "acme",
        "include_keywords": "", "exclude_keywords": "",
    })
    assert resp.status_code == 404


def test_edit_ignores_tampered_hidden_id_field(client):
    with open(client.app.state.sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme", "type": "greenhouse", "board_token": "acme"},
            {"id": "s2", "name": "Beta", "type": "greenhouse", "board_token": "beta"},
        ]}, f)

    resp = client.post("/sources/s1/edit", data={
        "id": "s2", "type": "greenhouse", "name": "Acme Renamed", "board_token": "acme",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    ids = {s["id"] for s in saved}
    assert ids == {"s1", "s2"}
    s1 = next(s for s in saved if s["id"] == "s1")
    assert s1["name"] == "Acme Renamed"
    s2 = next(s for s in saved if s["id"] == "s2")
    assert s2["name"] == "Beta"
