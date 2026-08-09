import json

import pytest

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
    ])

    sources = config.load_sources(str(path))

    assert [s.type for s in sources] == ["greenhouse", "lever", "generic_html", "linkedin", "indeed"]
    assert sources[0].board_token == "acme"
    assert sources[2].selectors.job_card == ".job"


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
