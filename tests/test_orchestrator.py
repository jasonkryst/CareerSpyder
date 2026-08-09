from unittest.mock import patch

from app import db, orchestrator
from app.config import GreenhouseSource, LeverSource
from app.models import Job


def test_run_once_collects_new_jobs_and_isolates_failures(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    good_source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good")
    bad_source = LeverSource(id="s2", name="Bad Co", type="lever", board_token="bad")

    def fake_greenhouse_fetch(source):
        return [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1", source_name=source.name)]

    def fake_lever_fetch(source):
        raise RuntimeError("site is down")

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_greenhouse_fetch, "lever": fake_lever_fetch}):
        summary = orchestrator.run_once(conn, [good_source, bad_source])

    assert [j.key for j in summary.new_jobs] == ["gh:1"]
    assert summary.failed_sources == ["Bad Co"]

    runs = db.list_runs(conn)
    assert runs[0]["id"] == summary.run_id
    assert runs[0]["new_job_count"] == 1
    assert runs[0]["failed_sources"] == ["Bad Co"]


def test_run_once_does_not_report_previously_seen_jobs_as_new(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good")

    def fake_fetch(source):
        return [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1", source_name=source.name)]

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch}):
        first = orchestrator.run_once(conn, [source])
        second = orchestrator.run_once(conn, [source])

    assert len(first.new_jobs) == 1
    assert len(second.new_jobs) == 0


def test_run_once_applies_keyword_filters(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good",
                               include_keywords=["engineer"])

    def fake_fetch(source):
        return [
            Job(key="gh:1", title="Backend Engineer", url="https://x.test/1", source_name=source.name),
            Job(key="gh:2", title="Sales Rep", url="https://x.test/2", source_name=source.name),
        ]

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch}):
        summary = orchestrator.run_once(conn, [source])

    assert [j.key for j in summary.new_jobs] == ["gh:1"]
