import json

from bs4 import BeautifulSoup


def test_new_source_form_renders(client):
    resp = client.get("/sources/new")
    assert resp.status_code == 200
    assert "Add source" in resp.text


def test_source_form_save_button_is_primary(client):
    resp = client.get("/sources/new")

    assert 'class="btn-primary"' in resp.text


def test_source_form_has_no_br_tags(client):
    resp = client.get("/sources/new")

    assert "<br>" not in resp.text


def test_post_new_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "greenhouse", "name": "Acme", "company": "Acme Corp", "board_token": "acme",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/sources?flash=")
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["name"] == "Acme"
    assert saved[0]["board_token"] == "acme"


def test_post_new_source_redirect_carries_added_flash_message(client):
    from urllib.parse import parse_qs, urlparse

    resp = client.post("/sources/new", data={
        "type": "greenhouse", "name": "Acme", "company": "Acme Corp", "board_token": "acme",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    location = urlparse(resp.headers["location"])
    assert location.path == "/sources"
    assert parse_qs(location.query)["flash"] == ["Source added."]


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


def test_post_new_healthcaresource_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "healthcaresource", "name": "Rush Copley (HealthcareSource)",
        "site_id": "rcmc", "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["type"] == "healthcaresource"
    assert saved[0]["site_id"] == "rcmc"


def test_post_new_healthcaresource_source_with_empty_site_id_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "healthcaresource", "name": "Rush Copley (HealthcareSource)", "site_id": "",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    with open(client.app.state.sources_path) as f:
        assert json.load(f)["sources"] == []


def test_post_new_talentbrew_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "talentbrew", "name": "NM (TalentBrew)", "base_url": "https://jobs.nm.org",
        "max_pages": "10", "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["type"] == "talentbrew"
    assert saved[0]["base_url"] == "https://jobs.nm.org"
    assert saved[0]["max_pages"] == 10


def test_post_new_talentbrew_source_with_empty_base_url_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "talentbrew", "name": "NM (TalentBrew)", "base_url": "",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    with open(client.app.state.sources_path) as f:
        assert json.load(f)["sources"] == []


def test_post_new_workday_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "workday", "name": "Duly (Workday)",
        "career_site_url": "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly",
        "max_pages": "20", "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["type"] == "workday"
    assert saved[0]["career_site_url"] == "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly"
    assert saved[0]["max_pages"] == 20


def test_post_new_workday_source_with_empty_career_site_url_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "workday", "name": "Duly (Workday)", "career_site_url": "",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    with open(client.app.state.sources_path) as f:
        assert json.load(f)["sources"] == []


def test_post_new_phenompeople_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "phenompeople", "name": "Ascension (PhenomPeople)",
        "phenompeople_career_site_url": "https://jobs.ascension.org", "state": "Illinois",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["type"] == "phenompeople"
    assert saved[0]["career_site_url"] == "https://jobs.ascension.org"
    assert saved[0]["state"] == "Illinois"


def test_post_new_phenompeople_source_with_empty_career_site_url_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "phenompeople", "name": "Ascension (PhenomPeople)", "phenompeople_career_site_url": "",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    with open(client.app.state.sources_path) as f:
        assert json.load(f)["sources"] == []


def test_post_new_findly_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "findly", "name": "Advocate Health (Findly)",
        "org_id": "2297", "findly_career_site_url": "https://careers.aah.org",
        "max_pages": "10", "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["type"] == "findly"
    assert saved[0]["org_id"] == "2297"
    assert saved[0]["career_site_url"] == "https://careers.aah.org"
    assert saved[0]["max_pages"] == 10


def test_post_new_findly_source_with_empty_org_id_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "findly", "name": "Advocate Health (Findly)", "org_id": "",
        "findly_career_site_url": "https://careers.aah.org",
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


def test_post_edit_redirect_carries_saved_flash_message(client):
    from urllib.parse import parse_qs, urlparse

    with open(client.app.state.sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.post("/sources/s1/edit", data={
        "id": "s1", "type": "greenhouse", "name": "Acme Renamed", "board_token": "acme",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    location = urlparse(resp.headers["location"])
    assert location.path == "/sources"
    assert parse_qs(location.query)["flash"] == ["Source saved."]


def test_post_new_source_with_empty_board_token_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "greenhouse", "name": "Acme", "company": "Acme Corp", "board_token": "",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    assert "Add source" in resp.text
    assert 'class="toast" role="status"' not in resp.text
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


def test_new_source_form_shows_hint_for_every_type(client):
    resp = client.get("/sources/new")

    assert 'board_token: "acme"' in resp.text
    assert 'board_token: "beta"' in resp.text
    assert 'selectors.job_card: ".job-listing"' in resp.text
    assert "linkedin.com/jobs/search" in resp.text
    assert "indeed.com/jobs" in resp.text
    assert 'max_pages: 3' in resp.text
    assert 'site_id: "rcmc"' in resp.text
    assert 'base_url: "https://jobs.nm.org"' in resp.text
    assert 'career_site_url: "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly"' in resp.text
    assert 'career_site_url: "https://jobs.ascension.org"' in resp.text
    assert 'org_id: "2297"' in resp.text


def test_source_form_hints_link_to_guide_anchors(client):
    resp = client.get("/sources/new")

    assert 'href="/guide#type-greenhouse"' in resp.text
    assert 'href="/guide#type-findly"' in resp.text


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


def test_post_new_linkedin_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "linkedin", "name": "Acme (LinkedIn)",
        "url": "https://www.linkedin.com/jobs/search/?keywords=backend+engineer",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["type"] == "linkedin"
    assert saved[0]["url"] == "https://www.linkedin.com/jobs/search/?keywords=backend+engineer"


def test_post_new_linkedin_source_with_empty_url_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "linkedin", "name": "Acme (LinkedIn)", "url": "",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    with open(client.app.state.sources_path) as f:
        assert json.load(f)["sources"] == []


def test_post_new_indeed_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "indeed", "name": "Acme (Indeed)",
        "url": "https://www.indeed.com/jobs?q=backend+engineer",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["type"] == "indeed"
    assert saved[0]["url"] == "https://www.indeed.com/jobs?q=backend+engineer"


def test_post_new_indeed_source_with_empty_url_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "indeed", "name": "Acme (Indeed)", "url": "",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    with open(client.app.state.sources_path) as f:
        assert json.load(f)["sources"] == []


def test_url_field_appears_exactly_once_in_source_form(client):
    resp = client.get("/sources/new")
    soup = BeautifulSoup(resp.text, "html.parser")

    assert len(soup.find_all("input", {"name": "url"})) == 1


def test_url_field_shown_for_generic_html_linkedin_and_indeed(client):
    """Regression for #35: the url input must live in a container that's
    revealed for generic_html, linkedin, AND indeed, not just generic_html
    — otherwise there is no way to enter a url when linkedin/indeed is
    selected."""
    resp = client.get("/sources/new")
    soup = BeautifulSoup(resp.text, "html.parser")

    url_input = soup.find("input", {"name": "url"})
    container = url_input.find_parent(attrs={"data-types": True})
    assert container is not None
    assert set(container["data-types"].split()) == {"generic_html", "linkedin", "indeed"}


def test_edit_form_prefills_url_for_linkedin_source(client):
    with open(client.app.state.sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme (LinkedIn)", "type": "linkedin",
             "url": "https://www.linkedin.com/jobs/search/?keywords=eng"},
        ]}, f)

    resp = client.get("/sources/s1/edit")
    soup = BeautifulSoup(resp.text, "html.parser")

    url_input = soup.find("input", {"name": "url"})
    assert url_input["value"] == "https://www.linkedin.com/jobs/search/?keywords=eng"


def test_edit_form_prefills_url_for_indeed_source(client):
    with open(client.app.state.sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme (Indeed)", "type": "indeed",
             "url": "https://www.indeed.com/jobs?q=eng"},
        ]}, f)

    resp = client.get("/sources/s1/edit")
    soup = BeautifulSoup(resp.text, "html.parser")

    url_input = soup.find("input", {"name": "url"})
    assert url_input["value"] == "https://www.indeed.com/jobs?q=eng"


def test_max_pages_field_appears_exactly_once_in_source_form(client):
    resp = client.get("/sources/new")
    soup = BeautifulSoup(resp.text, "html.parser")

    assert len(soup.find_all("input", {"name": "max_pages"})) == 1


def test_max_pages_field_shown_for_infor_talentbrew_workday_and_findly(client):
    resp = client.get("/sources/new")
    soup = BeautifulSoup(resp.text, "html.parser")

    max_pages_input = soup.find("input", {"name": "max_pages"})
    container = max_pages_input.find_parent(attrs={"data-types": True})
    assert container is not None
    assert set(container["data-types"].split()) == {"infor", "talentbrew", "workday", "findly"}


def test_edit_form_prefills_max_pages_for_workday_source(client):
    with open(client.app.state.sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Duly (Workday)", "type": "workday",
             "career_site_url": "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly",
             "max_pages": 45},
        ]}, f)

    resp = client.get("/sources/s1/edit")
    soup = BeautifulSoup(resp.text, "html.parser")

    max_pages_input = soup.find("input", {"name": "max_pages"})
    assert max_pages_input["value"] == "45"


def _rendered_form_fields(html: str) -> dict:
    """Extract name->value pairs the way a real browser's FormData would
    when submitting this form: every input regardless of CSS visibility,
    with unchecked checkboxes simply absent."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    fields: dict[str, str] = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        if inp.get("type") == "checkbox":
            if inp.has_attr("checked"):
                fields[name] = "on"
            continue
        fields[name] = inp.get("value", "")
    select = form.find("select", {"name": "type"})
    selected = select.find("option", selected=True) or select.find("option")
    fields["type"] = selected["value"]
    return fields


def test_post_edit_resubmitting_rendered_workday_form_preserves_max_pages(client):
    """Regression for #36: a browser submits every max_pages input in the
    DOM (even hidden ones); if more than one shares that name, the wrong
    (last-in-DOM) value silently overwrites the real one on save."""
    with open(client.app.state.sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Duly (Workday)", "type": "workday",
             "career_site_url": "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly",
             "max_pages": 77},
        ]}, f)

    edit_page = client.get("/sources/s1/edit")
    fields = _rendered_form_fields(edit_page.text)

    resp = client.post("/sources/s1/edit", data=fields, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["max_pages"] == 77


def test_post_edit_resubmitting_rendered_findly_form_preserves_max_pages(client):
    with open(client.app.state.sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Advocate Health (Findly)", "type": "findly",
             "org_id": "2297", "career_site_url": "https://careers.aah.org",
             "max_pages": 33},
        ]}, f)

    edit_page = client.get("/sources/s1/edit")
    fields = _rendered_form_fields(edit_page.text)

    resp = client.post("/sources/s1/edit", data=fields, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["max_pages"] == 33


def test_test_results_render_as_a_table_not_a_bullet_list(client):
    resp = client.get("/sources/new")
    soup = BeautifulSoup(resp.text, "html.parser")

    assert soup.find(id="test-results-body") is not None
    thead = soup.find(id="test-results-wrap").find("thead")
    headers = [th.get_text(strip=True) for th in thead.find_all("th")]
    assert headers == ["Title", "URL"]
    assert 'createElement("ul")' not in resp.text


def test_test_results_have_pagination_controls(client):
    resp = client.get("/sources/new")
    soup = BeautifulSoup(resp.text, "html.parser")

    pagination = soup.find(id="test-results-pagination")
    assert pagination is not None
    assert pagination.find(id="test-results-prev") is not None
    assert pagination.find(id="test-results-next") is not None
    assert pagination.find(id="test-results-page-info") is not None


def test_test_results_page_size_is_25(client):
    resp = client.get("/sources/new")

    assert "RESULTS_PAGE_SIZE = 25" in resp.text


# ── Secondary source flag (issue #82) ─────────────────────────────────────────

def test_source_form_has_secondary_checkbox(client):
    resp = client.get("/sources/new")
    assert 'name="secondary"' in resp.text


def test_secondary_checkbox_unchecked_by_default(client):
    resp = client.get("/sources/new")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    cb = soup.find("input", {"name": "secondary", "type": "checkbox"})
    assert cb is not None
    assert cb.get("checked") is None


def test_secondary_checkbox_checked_when_source_is_secondary(client):
    resp = client.post("/sources/new", data={
        "name": "Indeed Scrape", "type": "indeed",
        "url": "https://indeed.test/jobs", "secondary": "on",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)
    assert resp.status_code == 303

    sources_resp = client.get("/sources")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(sources_resp.text, "html.parser")
    edit_link = soup.find("a", href=lambda h: h and "/edit" in h)
    assert edit_link is not None
    edit_resp = client.get(edit_link["href"])
    assert 'name="secondary"' in edit_resp.text
    edit_soup = BeautifulSoup(edit_resp.text, "html.parser")
    cb = edit_soup.find("input", {"name": "secondary", "type": "checkbox"})
    assert cb is not None
    assert cb.get("checked") is not None


def test_secondary_false_persisted_when_checkbox_omitted(client):
    import json
    client.post("/sources/new", data={
        "name": "Greenhouse", "type": "greenhouse", "board_token": "acme",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)
    sources_path = client.app.state.sources_path
    with open(sources_path) as f:
        data = json.load(f)
    assert data["sources"][0]["secondary"] is False


def test_secondary_true_persisted_when_checkbox_checked(client):
    import json
    client.post("/sources/new", data={
        "name": "Indeed", "type": "indeed", "url": "https://indeed.test/jobs",
        "secondary": "on", "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)
    sources_path = client.app.state.sources_path
    with open(sources_path) as f:
        data = json.load(f)
    assert data["sources"][0]["secondary"] is True
