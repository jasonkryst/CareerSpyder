import json


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
    assert resp.headers["location"] == "/sources"
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["name"] == "Acme"
    assert saved[0]["board_token"] == "acme"


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


def test_post_new_source_with_empty_board_token_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "greenhouse", "name": "Acme", "company": "Acme Corp", "board_token": "",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    assert "Add source" in resp.text
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
