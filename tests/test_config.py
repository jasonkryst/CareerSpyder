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
    ])

    sources = config.load_sources(str(path))

    assert [s.type for s in sources] == [
        "greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor",
    ]
    assert sources[0].board_token == "acme"
    assert sources[2].selectors.job_card == ".job"
    assert sources[5].max_pages == 5


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
