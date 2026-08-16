from starlette.requests import Request

from app.web.query_params import query_url, sort_url


def _request(query_string: str = "") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/jobs",
        "query_string": query_string.encode(),
        "headers": [],
    }
    return Request(scope)


def test_query_url_with_no_overrides_and_no_existing_params():
    assert query_url(_request(), "/jobs") == "/jobs"


def test_query_url_adds_and_preserves_params():
    req = _request("company=Acme")
    assert query_url(req, "/jobs", page=2) in (
        "/jobs?company=Acme&page=2", "/jobs?page=2&company=Acme",
    )


def test_query_url_none_or_empty_override_removes_key():
    req = _request("page=2&company=Acme")
    result = query_url(req, "/jobs", page=None)
    assert "page=" not in result
    assert "company=Acme" in result


def test_sort_url_defaults_new_field_to_ascending():
    req = _request("")
    assert sort_url(req, "/jobs", "company") == "/jobs?sort=company&dir=asc"


def test_sort_url_toggles_active_ascending_field_to_descending():
    req = _request("sort=company&dir=asc")
    assert sort_url(req, "/jobs", "company") == "/jobs?sort=company&dir=desc"


def test_sort_url_toggles_active_descending_field_back_to_ascending():
    req = _request("sort=company&dir=desc")
    assert sort_url(req, "/jobs", "company") == "/jobs?sort=company&dir=asc"


def test_sort_url_switching_field_resets_to_ascending():
    req = _request("sort=company&dir=desc")
    assert sort_url(req, "/jobs", "title") == "/jobs?sort=title&dir=asc"


def test_sort_url_drops_page():
    req = _request("page=3&sort=company&dir=asc")
    assert "page=" not in sort_url(req, "/jobs", "title")
