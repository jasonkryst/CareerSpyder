import pytest
from pydantic import ValidationError

from app.web.source_form import source_from_form


def test_parses_greenhouse_fields():
    form = {
        "type": "greenhouse", "name": "Acme", "company": "Acme Corp",
        "board_token": "acme", "include_keywords": "engineer, backend", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.type == "greenhouse"
    assert source.board_token == "acme"
    assert source.include_keywords == ["engineer", "backend"]


def test_parses_generic_html_fields_with_selectors():
    form = {
        "type": "generic_html", "name": "Custom Co", "company": "Custom Co",
        "url": "https://customco.test/careers", "render_js": "on",
        "selector_job_card": ".job", "selector_title": ".t", "selector_link": "a",
        "selector_location": ".loc", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.type == "generic_html"
    assert source.render_js is True
    assert source.selectors.job_card == ".job"


def test_raises_on_missing_required_field():
    form = {"type": "greenhouse", "name": "Acme", "include_keywords": "", "exclude_keywords": ""}
    with pytest.raises(ValidationError):
        source_from_form(form)


def test_preserves_existing_id_when_provided():
    form = {
        "id": "s1", "type": "lever", "name": "Beta", "board_token": "beta",
        "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.id == "s1"
