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


def test_delete_source_redirect_carries_deleted_flash_message(client):
    from urllib.parse import parse_qs, urlparse

    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme (Greenhouse)", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.post("/sources/s1/delete", follow_redirects=False)

    location = urlparse(resp.headers["location"])
    assert location.path == "/sources"
    assert parse_qs(location.query)["flash"] == ["Source deleted."]


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


def test_delete_form_has_confirm_guard(client):
    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme (Greenhouse)", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.get("/sources")

    assert 'data-confirm-title="Delete source"' in resp.text
    assert "Delete &quot;Acme (Greenhouse)&quot;? This can't be undone." in resp.text


def test_sources_list_sorts_by_name_ascending(client):
    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Zeta", "type": "greenhouse", "board_token": "z"},
            {"id": "s2", "name": "Acme", "type": "greenhouse", "board_token": "a"},
        ]}, f)

    resp = client.get("/sources?sort=name&dir=asc")

    assert resp.text.index("Acme") < resp.text.index("Zeta")


def test_sources_list_sorts_by_name_descending(client):
    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme", "type": "greenhouse", "board_token": "a"},
            {"id": "s2", "name": "Zeta", "type": "greenhouse", "board_token": "z"},
        ]}, f)

    resp = client.get("/sources?sort=name&dir=desc")

    assert resp.text.index("Zeta") < resp.text.index("Acme")


def test_sources_list_filters_by_type(client):
    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "A Source", "type": "greenhouse", "board_token": "a"},
            {"id": "s2", "name": "B Source", "type": "lever", "board_token": "b"},
        ]}, f)

    resp = client.get("/sources?type=lever")

    assert 'data-label="Name">B Source' in resp.text
    assert 'data-label="Name">A Source' not in resp.text


def test_sources_list_type_filter_options_only_include_present_types(client):
    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "A", "type": "greenhouse", "board_token": "a"},
        ]}, f)

    resp = client.get("/sources")

    assert '<option value="greenhouse"' in resp.text
    assert '<option value="lever"' not in resp.text


def test_sources_list_invalid_sort_does_not_error(client):
    resp = client.get("/sources?sort=nonsense")
    assert resp.status_code == 200


def test_sources_list_second_page_still_shows_remaining_sources_unsorted(client):
    sources_path = client.app.state.sources_path
    sources = [
        {"id": f"s{i}", "name": f"Source {i}", "type": "greenhouse", "board_token": f"tok{i}"}
        for i in range(30)
    ]
    with open(sources_path, "w") as f:
        json.dump({"sources": sources}, f)

    page1 = client.get("/sources?page=1")

    assert "Source 0" in page1.text


def test_sources_list_sort_headers_have_aria_sort_when_active(client):
    resp = client.get("/sources?sort=name&dir=asc")
    assert 'aria-sort="ascending"' in resp.text


def test_sources_list_clear_filters_link_shown_when_filter_active(client):
    resp = client.get("/sources?type=greenhouse")
    assert 'href="/sources"' in resp.text
    assert "Clear filters" in resp.text


def test_sources_list_clear_filters_link_hidden_when_no_filter_active(client):
    resp = client.get("/sources")
    assert "Clear filters" not in resp.text
