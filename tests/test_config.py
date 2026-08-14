import json

import pytest
from pydantic import ValidationError

from app import config


def write_sources(path, sources_list):
    path.write_text(json.dumps({"sources": sources_list}))


def test_load_sources_parses_each_type(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [
        {"id": "s1", "name": "Acme (Greenhouse)", "type": "greenhouse", "board_token": "acme"},
        {"id": "s2", "name": "Beta (Lever)", "type": "lever", "board_token": "beta"},
        {
            "id": "s3", "name": "Custom Co", "type": "generic_html",
            "url": "https://customco.test/careers",
            "selectors": {"job_card": ".job", "title": ".t", "link": "a"},
        },
        {"id": "s4", "name": "LinkedIn", "type": "linkedin", "url": "https://linkedin.test/jobs"},
        {"id": "s5", "name": "Indeed", "type": "indeed", "url": "https://indeed.test/jobs"},
        {"id": "s6", "name": "Rush (Infor)", "type": "infor", "url": "https://rush.test/careers", "max_pages": 5},
        {"id": "s7", "name": "Rush Copley (HealthcareSource)", "type": "healthcaresource", "site_id": "rcmc"},
        {"id": "s8", "name": "NM (TalentBrew)", "type": "talentbrew", "base_url": "https://jobs.nm.org", "max_pages": 10},
        {
            "id": "s9", "name": "Duly (Workday)", "type": "workday",
            "career_site_url": "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly", "max_pages": 20,
        },
        {
            "id": "s10", "name": "Ascension (PhenomPeople)", "type": "phenompeople",
            "career_site_url": "https://jobs.ascension.org", "state": "Illinois",
        },
        {
            "id": "s11", "name": "Advocate Health (Findly)", "type": "findly",
            "org_id": "2297", "career_site_url": "https://careers.aah.org", "max_pages": 10,
        },
    ])

    sources = config.load_sources(str(path))

    assert [s.type for s in sources] == [
        "greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor",
        "healthcaresource", "talentbrew", "workday", "phenompeople", "findly",
    ]
    assert sources[0].board_token == "acme"
    assert sources[2].selectors.job_card == ".job"
    assert sources[5].max_pages == 5
    assert sources[6].site_id == "rcmc"
    assert sources[7].base_url == "https://jobs.nm.org"
    assert sources[7].max_pages == 10
    assert sources[8].career_site_url == "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly"
    assert sources[8].max_pages == 20
    assert sources[9].career_site_url == "https://jobs.ascension.org"
    assert sources[9].state == "Illinois"
    assert sources[10].org_id == "2297"
    assert sources[10].career_site_url == "https://careers.aah.org"
    assert sources[10].max_pages == 10


def test_add_update_delete_round_trip(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [])

    new_source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.add_source(str(path), new_source)
    assert [s.id for s in config.load_sources(str(path))] == ["s1"]

    updated = config.GreenhouseSource(id="s1", name="Acme Renamed", type="greenhouse", board_token="acme")
    config.update_source(str(path), "s1", updated)
    assert config.get_source(str(path), "s1").name == "Acme Renamed"

    config.delete_source(str(path), "s1")
    assert config.load_sources(str(path)) == []


def test_update_missing_source_raises(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [])
    updated = config.GreenhouseSource(id="missing", name="X", type="greenhouse", board_token="x")

    with pytest.raises(KeyError):
        config.update_source(str(path), "missing", updated)


def test_source_id_defaults_when_omitted():
    source = config.GreenhouseSource(name="Acme", type="greenhouse", board_token="acme")
    assert source.id


def test_load_sources_returns_empty_list_when_file_missing(tmp_path):
    path = tmp_path / "does-not-exist.json"
    assert config.load_sources(str(path)) == []


def test_save_sources_creates_parent_dirs_and_file(tmp_path):
    path = tmp_path / "nested" / "sources.json"
    config.save_sources(str(path), [])
    assert path.exists()
    assert config.load_sources(str(path)) == []


def test_save_sources_is_atomic_and_leaves_no_tmp_file(tmp_path):
    path = tmp_path / "sources.json"
    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.save_sources(str(path), [source])
    assert not (tmp_path / "sources.json.tmp").exists()
    assert [s.id for s in config.load_sources(str(path))] == ["s1"]


def test_export_sources_json_round_trips_saved_sources(tmp_path):
    path = tmp_path / "sources.json"
    source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.save_sources(str(path), [source])

    exported = json.loads(config.export_sources_json(str(path)))

    assert exported == {"sources": [source.model_dump()]}


def test_export_sources_json_on_missing_file_returns_empty_list(tmp_path):
    path = tmp_path / "does-not-exist.json"

    exported = json.loads(config.export_sources_json(str(path)))

    assert exported == {"sources": []}


def test_import_sources_json_replaces_existing_sources(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [{"id": "old", "name": "Old", "type": "greenhouse", "board_token": "old"}])
    payload = json.dumps({
        "sources": [{"id": "new", "name": "New", "type": "lever", "board_token": "new"}],
    }).encode()

    result = config.import_sources_json(str(path), payload)

    assert [s.id for s in result] == ["new"]
    assert [s.id for s in config.load_sources(str(path))] == ["new"]


def test_import_sources_json_rejects_invalid_json(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [{"id": "old", "name": "Old", "type": "greenhouse", "board_token": "old"}])

    with pytest.raises(json.JSONDecodeError):
        config.import_sources_json(str(path), b"not json")

    assert [s.id for s in config.load_sources(str(path))] == ["old"]


def test_import_sources_json_rejects_payload_missing_sources_key(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [{"id": "old", "name": "Old", "type": "greenhouse", "board_token": "old"}])

    with pytest.raises(ValidationError):
        config.import_sources_json(str(path), b'{"nope": []}')

    assert [s.id for s in config.load_sources(str(path))] == ["old"]


def test_import_sources_json_rejects_unknown_source_type(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [{"id": "old", "name": "Old", "type": "greenhouse", "board_token": "old"}])
    payload = json.dumps({"sources": [{"id": "x", "name": "X", "type": "carrier_pigeon"}]}).encode()

    with pytest.raises(ValidationError):
        config.import_sources_json(str(path), payload)

    assert [s.id for s in config.load_sources(str(path))] == ["old"]


def test_import_sources_json_rejects_blank_required_field(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [{"id": "old", "name": "Old", "type": "greenhouse", "board_token": "old"}])
    payload = json.dumps({"sources": [{"id": "x", "name": "X", "type": "greenhouse", "board_token": ""}]}).encode()

    with pytest.raises(ValidationError):
        config.import_sources_json(str(path), payload)

    assert [s.id for s in config.load_sources(str(path))] == ["old"]


def test_greenhouse_rejects_empty_board_token():
    with pytest.raises(ValidationError):
        config.GreenhouseSource(name="Acme", type="greenhouse", board_token="")


def test_generic_html_rejects_empty_url():
    with pytest.raises(ValidationError):
        config.GenericHtmlSource(
            name="Custom Co", type="generic_html", url="",
            selectors=config.Selectors(job_card=".job", title=".t", link="a"),
        )


def test_selectors_reject_empty_job_card():
    with pytest.raises(ValidationError):
        config.Selectors(job_card="", title=".t", link="a")


def test_infor_rejects_empty_url():
    with pytest.raises(ValidationError):
        config.InforSource(name="Rush", type="infor", url="")


def test_infor_max_pages_defaults_to_three():
    source = config.InforSource(name="Rush", type="infor", url="https://rush.test/careers")
    assert source.max_pages == 3


def test_healthcaresource_rejects_empty_site_id():
    with pytest.raises(ValidationError):
        config.HealthcareSource(name="Rush Copley", type="healthcaresource", site_id="")


def test_talentbrew_rejects_empty_base_url():
    with pytest.raises(ValidationError):
        config.TalentBrewSource(name="Northwestern Medicine", type="talentbrew", base_url="")


def test_talentbrew_max_pages_defaults_to_sixty():
    source = config.TalentBrewSource(name="Northwestern Medicine", type="talentbrew", base_url="https://jobs.nm.org")
    assert source.max_pages == 60


def test_workday_rejects_empty_career_site_url():
    with pytest.raises(ValidationError):
        config.WorkdaySource(name="Duly", type="workday", career_site_url="")


def test_workday_max_pages_defaults_to_sixty():
    source = config.WorkdaySource(
        name="Duly", type="workday",
        career_site_url="https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly",
    )
    assert source.max_pages == 60


def test_phenompeople_rejects_empty_career_site_url():
    with pytest.raises(ValidationError):
        config.PhenomPeopleSource(name="Ascension", type="phenompeople", career_site_url="")


def test_phenompeople_state_defaults_to_none():
    source = config.PhenomPeopleSource(
        name="Ascension", type="phenompeople", career_site_url="https://jobs.ascension.org",
    )
    assert source.state is None


def test_findly_rejects_empty_org_id():
    with pytest.raises(ValidationError):
        config.FindlySource(
            name="Advocate Health", type="findly", org_id="",
            career_site_url="https://careers.aah.org",
        )


def test_findly_rejects_empty_career_site_url():
    with pytest.raises(ValidationError):
        config.FindlySource(name="Advocate Health", type="findly", org_id="2297", career_site_url="")


def test_findly_max_pages_defaults_to_twenty():
    source = config.FindlySource(
        name="Advocate Health", type="findly", org_id="2297",
        career_site_url="https://careers.aah.org",
    )
    assert source.max_pages == 20
