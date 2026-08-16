from urllib.parse import parse_qs, urlparse

from fastapi.responses import RedirectResponse

from app.web.flash import flash_redirect


def test_flash_redirect_returns_a_redirect_response():
    resp = flash_redirect("/sources", "Source added.")
    assert isinstance(resp, RedirectResponse)


def test_flash_redirect_defaults_to_303():
    resp = flash_redirect("/sources", "Source added.")
    assert resp.status_code == 303


def test_flash_redirect_appends_message_as_flash_query_param():
    resp = flash_redirect("/sources", "Source added.")
    location = urlparse(resp.headers["location"])
    assert location.path == "/sources"
    assert parse_qs(location.query)["flash"] == ["Source added."]


def test_flash_redirect_url_encodes_special_characters():
    resp = flash_redirect("/jobs", "50% done & more")
    location = urlparse(resp.headers["location"])
    assert parse_qs(location.query)["flash"] == ["50% done & more"]


def test_flash_redirect_accepts_a_custom_status_code():
    resp = flash_redirect("/sources", "Source added.", status_code=302)
    assert resp.status_code == 302
