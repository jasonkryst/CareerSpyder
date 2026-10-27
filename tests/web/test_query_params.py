from starlette.requests import Request

from app.web.query_params import (
    query_url,
    remove_filter_url,
    remove_filter_value_url,
    sort_url,
)


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


# --- remove_filter_url / remove_filter_value_url (active-filter chips, issue #254) ---

def test_remove_filter_url_drops_the_given_key():
    req = _request("company=Acme&search=engineer")
    result = remove_filter_url(req, "/jobs", "company")
    assert "company=" not in result
    assert "search=engineer" in result


def test_remove_filter_url_preserves_other_multi_valued_params():
    """Removing one filter must not collapse an unrelated multi-select
    filter to its last value -- this is the bug query_url's dict(query_params)
    would cause if reused here."""
    req = _request("company=Acme&state=IL&state=NY")
    result = remove_filter_url(req, "/jobs", "company")
    assert result.count("state=IL") == 1
    assert result.count("state=NY") == 1


def test_remove_filter_url_drops_all_values_for_a_multi_valued_key():
    req = _request("state=IL&state=NY")
    result = remove_filter_url(req, "/jobs", "state")
    assert result == "/jobs"


def test_remove_filter_url_can_drop_multiple_keys_at_once():
    req = _request("zip=60148&radius=50&company=Acme")
    result = remove_filter_url(req, "/jobs", "zip", "radius")
    assert "zip=" not in result
    assert "radius=" not in result
    assert "company=Acme" in result


def test_remove_filter_url_drops_page():
    req = _request("page=3&company=Acme")
    result = remove_filter_url(req, "/jobs", "company")
    assert "page=" not in result


def test_remove_filter_url_with_no_matching_key_returns_bare_path():
    req = _request("")
    assert remove_filter_url(req, "/jobs", "company") == "/jobs"


def test_remove_filter_value_url_removes_only_the_given_value():
    req = _request("state=IL&state=NY&state=CA")
    result = remove_filter_value_url(req, "/jobs", "state", "NY")
    assert result.count("state=IL") == 1
    assert result.count("state=CA") == 1
    assert "state=NY" not in result


def test_remove_filter_value_url_drops_page():
    req = _request("page=2&state=IL&state=NY")
    result = remove_filter_value_url(req, "/jobs", "state", "NY")
    assert "page=" not in result
