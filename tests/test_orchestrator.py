import threading
import time
from unittest.mock import patch

from app import db, orchestrator
from app.config import GreenhouseSource, LeverSource
from app.geocoding.base import GeocodeResult
from app.models import Job


class _FakeGeocoder:
    name = "fake"
    min_interval_seconds = 0.0

    def geocode(self, location):
        return GeocodeResult(display_name="Chicago, IL, USA", city="Chicago",
                              region="Illinois", country="USA", lat=41.8, lng=-87.6)


def test_infor_adapter_is_registered():
    from app.adapters import ADAPTERS
    assert "infor" in ADAPTERS


def test_healthcaresource_adapter_is_registered():
    from app.adapters import ADAPTERS
    assert "healthcaresource" in ADAPTERS


def test_talentbrew_adapter_is_registered():
    from app.adapters import ADAPTERS
    assert "talentbrew" in ADAPTERS


def test_workday_adapter_is_registered():
    from app.adapters import ADAPTERS
    assert "workday" in ADAPTERS


def test_phenompeople_adapter_is_registered():
    from app.adapters import ADAPTERS
    assert "phenompeople" in ADAPTERS


def test_findly_adapter_is_registered():
    from app.adapters import ADAPTERS
    assert "findly" in ADAPTERS


def test_run_once_geocodes_pending_locations_via_an_injected_geocoder(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good")

    def fake_fetch(source):
        return [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1",
                     source_name=source.name, location="Chicago, IL")]

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch}):
        orchestrator.run_once(conn, [source], geocoder=_FakeGeocoder())

    row = conn.execute(
        "SELECT status, display_name FROM geocoded_locations WHERE location = 'Chicago, IL'"
    ).fetchone()
    assert row == ("resolved", "Chicago, IL, USA")


def test_run_once_does_not_abort_when_the_geocoding_step_raises(tmp_db_path, monkeypatch):
    conn = db.init_db(tmp_db_path)
    source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good")

    def fake_fetch(source):
        return [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1", source_name=source.name)]

    def boom(conn, geocoder):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(orchestrator, "geocode_pending", boom)

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch}):
        summary = orchestrator.run_once(conn, [source])

    assert [j.key for j in summary.new_jobs] == ["gh:1"]
    runs = db.list_runs(conn)
    assert runs[0]["finished_at"] is not None


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


def test_run_once_dedupes_jobs_with_same_key_across_sources(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    source_a = GreenhouseSource(id="s1", name="Source A", type="greenhouse", board_token="a")
    source_b = LeverSource(id="s2", name="Source B", type="lever", board_token="b")

    def fake_fetch(source):
        return [Job(key="dup:1", title="Backend Engineer", url="https://x.test/1", source_name=source.name)]

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch, "lever": fake_fetch}):
        summary = orchestrator.run_once(conn, [source_a, source_b])

    assert len(summary.new_jobs) == 1


def test_run_once_handles_unknown_source_type_without_aborting_run(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    good_source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good")
    bad_source = LeverSource(id="s2", name="Bad Co", type="lever", board_token="bad")

    def fake_fetch(source):
        return [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1", source_name=source.name)]

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch}, clear=True):
        summary = orchestrator.run_once(conn, [good_source, bad_source])

    assert [j.key for j in summary.new_jobs] == ["gh:1"]
    assert summary.failed_sources == ["Bad Co"]
    runs = db.list_runs(conn)
    assert runs[0]["finished_at"] is not None


def test_run_once_found_jobs_includes_already_known_jobs(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good")

    def fake_fetch(source):
        return [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1", source_name=source.name)]

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch}):
        first = orchestrator.run_once(conn, [source])
        second = orchestrator.run_once(conn, [source])

    assert [j.key for j in first.found_jobs] == ["gh:1"]
    assert [j.key for j in second.found_jobs] == ["gh:1"]
    assert [j.key for j in second.new_jobs] == []


def test_run_once_sets_source_id_on_saved_jobs(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good")

    def fake_fetch(source):
        return [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1",
                     source_name=source.name, source_id=source.id)]

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch}):
        orchestrator.run_once(conn, [source])

    rows = db.list_jobs(conn)
    assert rows[0]["source_id"] == "s1"


def test_run_once_marks_a_job_removed_when_it_stops_appearing(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good")
    calls = []

    def fake_fetch(source):
        calls.append(1)
        if len(calls) == 1:
            return [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1",
                         source_name=source.name, source_id=source.id)]
        return []

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch}):
        orchestrator.run_once(conn, [source])
        orchestrator.run_once(conn, [source])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["gh:1"]["removed_at"] is not None


def test_run_once_reactivates_a_removed_job_that_reappears(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good")
    responses = [
        [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1",
             source_name=source.name, source_id=source.id)],
        [],
        [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1",
             source_name=source.name, source_id=source.id)],
    ]

    def fake_fetch(source):
        return responses.pop(0)

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch}):
        orchestrator.run_once(conn, [source])
        orchestrator.run_once(conn, [source])
        orchestrator.run_once(conn, [source])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["gh:1"]["removed_at"] is None


def test_run_once_does_not_mark_jobs_removed_for_a_source_that_failed_this_run(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good")
    calls = []

    def fake_fetch(source):
        calls.append(1)
        if len(calls) == 1:
            return [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1",
                         source_name=source.name, source_id=source.id)]
        raise RuntimeError("site is down")

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch}):
        orchestrator.run_once(conn, [source])
        orchestrator.run_once(conn, [source])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["gh:1"]["removed_at"] is None


def test_run_once_marks_jobs_removed_when_their_source_is_deleted_between_runs(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good")

    def fake_fetch(source):
        return [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1",
                     source_name=source.name, source_id=source.id)]

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch}):
        orchestrator.run_once(conn, [source])
        orchestrator.run_once(conn, [])  # source deleted from sources.json

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["gh:1"]["removed_at"] is not None


def test_run_once_does_not_mark_a_job_removed_when_only_keyword_filters_exclude_it(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good",
                               include_keywords=["engineer"])

    def fake_fetch(source):
        # Still present on the site every run -- only the keyword filter excludes it from the digest.
        return [Job(key="gh:1", title="Sales Rep", url="https://x.test/1",
                     source_name=source.name, source_id=source.id)]

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch}):
        run_id = db.start_run(conn)
        db.save_jobs(conn, [Job(key="gh:1", title="Sales Rep", url="https://x.test/1",
                                 source_name=source.name, source_id="s1")], run_id)
        db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])

        orchestrator.run_once(conn, [source])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["gh:1"]["removed_at"] is None


def test_run_once_serializes_concurrent_runs_so_new_jobs_are_not_double_reported(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good")

    def slow_fetch(source):
        time.sleep(0.05)
        return [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1", source_name=source.name)]

    results = []

    def worker():
        results.append(orchestrator.run_once(conn, [source]))

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": slow_fetch}):
        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    total_new = sum(len(r.new_jobs) for r in results)
    assert total_new == 1
