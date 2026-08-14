import pytest

ALL_SOURCE_TYPES = [
    "greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor",
    "healthcaresource", "talentbrew", "workday", "phenompeople", "findly",
]


def test_guide_page_returns_200(client):
    resp = client.get("/guide")

    assert resp.status_code == 200
    assert "Usage Guide" in resp.text


def test_guide_nav_link_marks_current_page(client):
    resp = client.get("/guide")

    assert 'href="/guide" aria-current="page"' in resp.text
    assert 'href="/" aria-current="page"' not in resp.text


@pytest.mark.parametrize("source_type", ALL_SOURCE_TYPES)
def test_guide_has_anchor_for_every_source_type(client, source_type):
    resp = client.get("/guide")

    assert f'id="type-{source_type}"' in resp.text


def test_guide_has_getting_started_and_web_ui_tour_sections(client):
    resp = client.get("/guide")

    assert "Getting started" in resp.text
    assert "Web UI tour" in resp.text
    assert "Source types" in resp.text


def test_guide_shows_example_values(client):
    resp = client.get("/guide")

    assert 'board_token: "acme"' in resp.text
    assert 'career_site_url: "https://jobs.ascension.org"' in resp.text
