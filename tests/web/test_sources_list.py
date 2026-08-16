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


def test_sources_table_has_no_legacy_inline_attributes(client):
    resp = client.get("/sources")

    assert 'border="1"' not in resp.text
    assert 'cellpadding="4"' not in resp.text


def test_sources_table_has_scoped_headers_and_scroll_wrapper(client):
    resp = client.get("/sources")

    assert 'scope="col"' in resp.text
    assert 'class="table-scroll"' in resp.text


def test_sources_list_second_page_shows_remaining_sources(client):
    sources_path = client.app.state.sources_path
    sources = [
        {"id": f"s{i}", "name": f"Source {i}", "type": "greenhouse", "board_token": f"tok{i}"}
        for i in range(30)
    ]
    with open(sources_path, "w") as f:
        json.dump({"sources": sources}, f)

    page1 = client.get("/sources?page=1")
    page2 = client.get("/sources?page=2")

    assert "Page 1 of 2" in page1.text
    assert "Source 0" in page1.text
    assert "Source 0" not in page2.text
    assert "Page 2 of 2" in page2.text


def test_sources_list_invalid_page_param_clamps_instead_of_erroring(client):
    resp = client.get("/sources?page=abc")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_sources_table_cells_have_data_labels(client):
    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme (Greenhouse)", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.get("/sources")

    for label in ("Name", "Type", "Company", "Edit", "Delete"):
        assert f'data-label="{label}"' in resp.text
