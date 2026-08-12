import json
import os


def test_sources_list_renders_empty_when_sources_file_missing(client):
    sources_path = client.app.state.sources_path
    os.remove(sources_path)

    resp = client.get("/sources")

    assert resp.status_code == 200


def test_delete_unknown_source_returns_404(client):
    resp = client.post("/sources/does-not-exist/delete")
    assert resp.status_code == 404


def test_sources_list_shows_configured_sources(client):
    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme (Greenhouse)", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.get("/sources")

    assert resp.status_code == 200
    assert "Acme (Greenhouse)" in resp.text


def test_delete_source_removes_it(client):
    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme (Greenhouse)", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.post("/sources/s1/delete", follow_redirects=False)

    assert resp.status_code == 303
    with open(sources_path) as f:
        assert json.load(f)["sources"] == []
