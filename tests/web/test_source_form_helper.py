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


def test_parses_infor_fields():
    form = {
        "type": "infor", "name": "Rush (Infor)", "company": "Rush University Medical Center",
        "infor_url": "https://rush.test/careers", "max_pages": "5",
        "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.type == "infor"
    assert source.url == "https://rush.test/careers"
    assert source.max_pages == 5


def test_infor_max_pages_defaults_when_field_blank():
    form = {
        "type": "infor", "name": "Rush (Infor)", "infor_url": "https://rush.test/careers",
        "max_pages": "", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.max_pages == 3


def test_parses_healthcaresource_fields():
    form = {
        "type": "healthcaresource", "name": "Rush Copley (HealthcareSource)",
        "site_id": "rcmc", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.type == "healthcaresource"
    assert source.site_id == "rcmc"


def test_parses_talentbrew_fields():
    form = {
        "type": "talentbrew", "name": "NM (TalentBrew)", "base_url": "https://jobs.nm.org",
        "max_pages": "10", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.type == "talentbrew"
    assert source.base_url == "https://jobs.nm.org"
    assert source.max_pages == 10


def test_talentbrew_max_pages_defaults_when_field_blank():
    form = {
        "type": "talentbrew", "name": "NM (TalentBrew)", "base_url": "https://jobs.nm.org",
        "max_pages": "", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.max_pages == 60


def test_parses_workday_fields():
    form = {
        "type": "workday", "name": "Duly (Workday)",
        "career_site_url": "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly",
        "max_pages": "20", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.type == "workday"
    assert source.career_site_url == "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly"
    assert source.max_pages == 20


def test_workday_max_pages_defaults_when_field_blank():
    form = {
        "type": "workday", "name": "Duly (Workday)",
        "career_site_url": "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly",
        "max_pages": "", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.max_pages == 60
