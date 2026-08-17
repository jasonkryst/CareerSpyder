from datetime import UTC, datetime, timedelta

import pytest

from app import db
from app.models import Job


def make_job(key="k1", title="Engineer", source_id="s1", summary=None):
    return Job(key=key, title=title, url="https://x.test/1", company="Acme",
               location="Remote", posted_date=None, source_name="Acme Board",
               source_id=source_id, summary=summary)


def test_new_job_then_seen_on_second_run(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    job = make_job()

    assert db.get_new_jobs(conn, [job]) == [job]
    run_id = db.start_run(conn)
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])

    assert db.get_new_jobs(conn, [job]) == []


def test_clear_jobs_empties_the_table(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    job = make_job()
    run_id = db.start_run(conn)
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])
    assert db.get_new_jobs(conn, [job]) == []

    db.clear_jobs(conn)

    assert db.get_new_jobs(conn, [job]) == [job]


def test_clear_jobs_on_empty_table_does_not_raise(tmp_db_path):
    conn = db.init_db(tmp_db_path)

    db.clear_jobs(conn)  # should not raise

    assert db.get_new_jobs(conn, [make_job()]) == [make_job()]


def test_list_runs_returns_most_recent_first(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    run1 = db.start_run(conn)
    db.finish_run(conn, run1, new_job_count=0, failed_sources=["Bad Co"])
    run2 = db.start_run(conn)
    db.finish_run(conn, run2, new_job_count=2, failed_sources=[])

    runs = db.list_runs(conn)

    assert [r["id"] for r in runs] == [run2, run1]
    assert runs[1]["failed_sources"] == ["Bad Co"]


def test_list_runs_respects_offset(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    ids = [db.start_run(conn) for _ in range(3)]
    for run_id in ids:
        db.finish_run(conn, run_id, new_job_count=0, failed_sources=[])

    page2 = db.list_runs(conn, limit=2, offset=2)

    assert [r["id"] for r in page2] == [ids[0]]


def test_count_runs_returns_total(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.start_run(conn)
    db.start_run(conn)

    assert db.count_runs(conn) == 2


def test_list_runs_sorts_by_new_job_count_ascending(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=5, failed_sources=[])
    r2 = db.start_run(conn)
    db.finish_run(conn, r2, new_job_count=1, failed_sources=[])

    rows = db.list_runs(conn, sort="new_job_count", direction="asc")

    assert [r["new_job_count"] for r in rows] == [1, 5]


def test_list_runs_sorts_by_started_at_descending(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    r1 = db.start_run(conn)
    r2 = db.start_run(conn)

    rows = db.list_runs(conn, sort="started_at", direction="desc")

    assert [r["id"] for r in rows] == [r2, r1]


def test_list_runs_default_ordering_unchanged_with_no_new_kwargs(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=1, failed_sources=[])
    r2 = db.start_run(conn)
    db.finish_run(conn, r2, new_job_count=2, failed_sources=[])

    rows = db.list_runs(conn)

    assert [r["id"] for r in rows] == [r2, r1]


def test_list_runs_unrecognized_sort_falls_back_to_default(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.start_run(conn)

    rows = db.list_runs(conn, sort="garbage")

    assert len(rows) == 1


def test_list_runs_filters_only_failures(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=0, failed_sources=["Bad Co"])
    r2 = db.start_run(conn)
    db.finish_run(conn, r2, new_job_count=0, failed_sources=[])

    only = db.list_runs(conn, failures="only")
    clean = db.list_runs(conn, failures="clean")

    assert [r["id"] for r in only] == [r1]
    assert [r["id"] for r in clean] == [r2]


def test_list_runs_invalid_failures_value_returns_all(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.start_run(conn)
    db.start_run(conn)

    rows = db.list_runs(conn, failures="nonsense")

    assert len(rows) == 2


def test_count_runs_respects_failures_filter(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=0, failed_sources=["Bad Co"])

    assert db.count_runs(conn, failures="only") == 1
    assert db.count_runs(conn, failures="clean") == 0


def test_settings_seed_only_when_empty(tmp_db_path):
    conn = db.init_db(tmp_db_path)

    db.seed_settings_if_empty(conn, "smtp.example.com", 587, "user", "from@x.test", "to@x.test")
    db.seed_settings_if_empty(conn, "ignored.example.com", 25, "ignored", "i@x.test", "i2@x.test")

    settings = db.get_settings(conn)
    assert settings["smtp_host"] == "smtp.example.com"


def test_save_settings_overwrites(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_settings(conn, "a.example.com", 587, "u1", "f@x.test")
    db.save_settings(conn, "b.example.com", 465, "u2", "f2@x.test")

    settings = db.get_settings(conn)
    assert settings["smtp_host"] == "b.example.com"
    assert settings["smtp_port"] == 465
    assert settings["smtp_user"] == "u2"
    assert settings["email_from"] == "f2@x.test"


def test_save_settings_does_not_touch_preference_columns(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_preferences(conn, "mon,wed,fri", True, "a@x.test,b@x.test")

    db.save_settings(conn, "a.example.com", 587, "u1", "f@x.test")

    settings = db.get_settings(conn)
    assert settings["email_days"] == "mon,wed,fri"
    assert settings["resend_jobs"] is True
    assert settings["email_to"] == "a@x.test,b@x.test"


def test_save_preferences_overwrites(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_preferences(conn, "mon,tue,wed,thu,fri,sat,sun", False, "a@x.test")
    db.save_preferences(conn, "mon,wed,fri", True, "a@x.test,b@x.test")

    settings = db.get_settings(conn)
    assert settings["email_days"] == "mon,wed,fri"
    assert settings["resend_jobs"] is True
    assert settings["email_to"] == "a@x.test,b@x.test"


def test_save_preferences_does_not_touch_smtp_columns(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_settings(conn, "a.example.com", 587, "u1", "f@x.test")

    db.save_preferences(conn, "mon", False, "a@x.test")

    settings = db.get_settings(conn)
    assert settings["smtp_host"] == "a.example.com"
    assert settings["smtp_port"] == 587
    assert settings["smtp_user"] == "u1"
    assert settings["email_from"] == "f@x.test"


def test_get_settings_defaults_days_and_resend_after_seeding(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.seed_settings_if_empty(conn, "smtp.example.com", 587, "user", "from@x.test", "to@x.test")

    settings = db.get_settings(conn)
    assert settings["email_days"] == "mon,tue,wed,thu,fri,sat,sun"
    assert settings["resend_jobs"] is False
    assert settings["email_to"] == "to@x.test"


def test_init_db_adds_new_columns_to_a_pre_existing_database(tmp_db_path):
    import sqlite3

    conn = sqlite3.connect(tmp_db_path)
    conn.execute(
        "CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK (id = 1), "
        "smtp_host TEXT, smtp_port INTEGER, smtp_user TEXT, email_from TEXT, email_to TEXT)"
    )
    conn.execute(
        "INSERT INTO settings (id, smtp_host, smtp_port, smtp_user, email_from, email_to) "
        "VALUES (1, 'old.example.com', 587, 'olduser', 'old@x.test', 'oldto@x.test')"
    )
    conn.commit()
    conn.close()

    conn = db.init_db(tmp_db_path)

    settings = db.get_settings(conn)
    assert settings["smtp_host"] == "old.example.com"
    assert settings["email_to"] == "oldto@x.test"
    assert settings["email_days"] == "mon,tue,wed,thu,fri,sat,sun"
    assert settings["resend_jobs"] is False


def test_init_db_is_idempotent_on_an_already_migrated_database(tmp_db_path):
    db.init_db(tmp_db_path)

    conn = db.init_db(tmp_db_path)  # must not raise on the second call

    assert db.get_settings(conn) is None


def test_init_db_adds_new_columns_to_an_existing_jobs_table(tmp_db_path):
    import sqlite3

    old_conn = sqlite3.connect(tmp_db_path)
    old_conn.execute("""
        CREATE TABLE jobs (
            key TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT,
            location TEXT,
            url TEXT NOT NULL,
            posted_date TEXT,
            source_name TEXT NOT NULL,
            first_seen_run_id INTEGER,
            first_seen_at TEXT NOT NULL
        )
    """)
    old_conn.execute(
        "INSERT INTO jobs (key, title, url, source_name, first_seen_at) VALUES (?,?,?,?,?)",
        ("legacy:1", "Legacy Job", "https://x.test/1", "Legacy Source", "2026-01-01T00:00:00+00:00"),
    )
    old_conn.commit()
    old_conn.close()

    conn = db.init_db(tmp_db_path)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert {"source_id", "summary", "removed_at", "emailed_at"} <= columns
    row = conn.execute("SELECT key, source_id, removed_at FROM jobs WHERE key = 'legacy:1'").fetchone()
    assert row == ("legacy:1", None, None)


def test_save_jobs_persists_source_id_and_summary(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    job = make_job(source_id="src-1", summary="A great role.")
    run_id = db.start_run(conn)

    db.save_jobs(conn, [job], run_id)

    rows = db.list_jobs(conn)
    assert rows[0]["source_id"] == "src-1"
    assert rows[0]["summary"] == "A great role."
    assert rows[0]["removed_at"] is None
    assert rows[0]["emailed_at"] is None


def test_list_jobs_orders_newest_first(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.save_jobs(conn, [make_job(key="k2")], db.start_run(conn))

    rows = db.list_jobs(conn)

    assert [r["key"] for r in rows] == ["k2", "k1"]


def test_list_jobs_respects_limit_and_offset(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    for i in range(3):
        db.save_jobs(conn, [make_job(key=f"k{i}")], db.start_run(conn))

    page = db.list_jobs(conn, limit=1, offset=1)

    assert len(page) == 1


def test_count_jobs_returns_total(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1"), make_job(key="k2")], db.start_run(conn))

    assert db.count_jobs(conn) == 2


def test_mark_emailed_sets_timestamp_for_given_keys_only(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1"), make_job(key="k2")], db.start_run(conn))

    db.mark_emailed(conn, ["k1"])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["emailed_at"] is not None
    assert rows["k2"]["emailed_at"] is None


def test_mark_emailed_with_empty_list_does_not_raise(tmp_db_path):
    conn = db.init_db(tmp_db_path)

    db.mark_emailed(conn, [])  # should not raise


def test_reconcile_jobs_marks_missing_job_removed_when_its_source_succeeded(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1", source_id="s1")], db.start_run(conn))

    db.reconcile_jobs(conn, configured_source_ids={"s1"}, succeeded_source_ids={"s1"}, found_jobs=[])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["removed_at"] is not None


def test_reconcile_jobs_leaves_job_untouched_when_still_found(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    job = make_job(key="k1", source_id="s1")
    db.save_jobs(conn, [job], db.start_run(conn))

    db.reconcile_jobs(conn, configured_source_ids={"s1"}, succeeded_source_ids={"s1"}, found_jobs=[job])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["removed_at"] is None


def test_reconcile_jobs_reactivates_a_removed_job_that_reappears(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    job = make_job(key="k1", source_id="s1")
    db.save_jobs(conn, [job], db.start_run(conn))
    db.reconcile_jobs(conn, configured_source_ids={"s1"}, succeeded_source_ids={"s1"}, found_jobs=[])
    assert db.list_jobs(conn)[0]["removed_at"] is not None

    db.reconcile_jobs(conn, configured_source_ids={"s1"}, succeeded_source_ids={"s1"}, found_jobs=[job])

    assert db.list_jobs(conn)[0]["removed_at"] is None


def test_reconcile_jobs_ignores_jobs_from_a_source_that_merely_failed_this_run(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1", source_id="s1")], db.start_run(conn))

    # s1 is still configured but did not succeed this run (e.g. it raised) -- must not be touched.
    db.reconcile_jobs(conn, configured_source_ids={"s1"}, succeeded_source_ids=set(), found_jobs=[])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["removed_at"] is None


def test_reconcile_jobs_marks_removed_when_its_source_is_deleted_from_config(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1", source_id="s1")], db.start_run(conn))

    # s1 no longer appears in configured_source_ids at all -- deleted from sources.json.
    db.reconcile_jobs(conn, configured_source_ids=set(), succeeded_source_ids=set(), found_jobs=[])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["removed_at"] is not None


def test_reconcile_jobs_leaves_legacy_rows_with_no_source_id_untouched(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1", source_id=None)], db.start_run(conn))

    db.reconcile_jobs(conn, configured_source_ids=set(), succeeded_source_ids=set(), found_jobs=[])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["removed_at"] is None


def _job(key, company="Acme", title="Engineer", source_name="Acme Board", source_id="s1"):
    return Job(key=key, title=title, url="https://x.test/1", company=company,
               location="Remote", posted_date=None, source_name=source_name,
               source_id=source_id, summary=None)


def test_list_jobs_sorts_by_company_ascending(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("a", company="Zeta")], run_id)
    db.save_jobs(conn, [_job("b", company="Acme")], run_id)

    rows = db.list_jobs(conn, sort="company", direction="asc")

    assert [r["company"] for r in rows] == ["Acme", "Zeta"]


def test_list_jobs_sorts_by_company_descending(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("a", company="Zeta")], run_id)
    db.save_jobs(conn, [_job("b", company="Acme")], run_id)

    rows = db.list_jobs(conn, sort="company", direction="desc")

    assert [r["company"] for r in rows] == ["Zeta", "Acme"]


def test_list_jobs_sorts_by_age_days(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("young")], run_id)
    db.save_jobs(conn, [_job("old")], run_id)
    conn.execute(
        "UPDATE jobs SET first_seen_at = ? WHERE key = 'old'",
        ((datetime.now(UTC) - timedelta(days=30)).isoformat(),),
    )
    conn.commit()

    rows = db.list_jobs(conn, sort="age_days", direction="desc")

    assert [r["key"] for r in rows] == ["old", "young"]


def test_list_jobs_default_ordering_unchanged_with_no_new_kwargs(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [_job("a")], db.start_run(conn))
    db.save_jobs(conn, [_job("b")], db.start_run(conn))

    rows = db.list_jobs(conn)

    assert [r["key"] for r in rows] == ["b", "a"]


def test_list_jobs_unrecognized_sort_falls_back_to_default(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [_job("a")], db.start_run(conn))

    rows = db.list_jobs(conn, sort="'; DROP TABLE jobs; --")

    assert len(rows) == 1


def test_list_jobs_filters_by_company_substring_case_insensitive(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("a", company="Acme Corp")], run_id)
    db.save_jobs(conn, [_job("b", company="Zenith")], run_id)

    rows = db.list_jobs(conn, company="acme")

    assert [r["key"] for r in rows] == ["a"]


def test_list_jobs_filters_by_source_name(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("a", source_name="Acme Board")], run_id)
    db.save_jobs(conn, [_job("b", source_name="Zeta Board")], run_id)

    rows = db.list_jobs(conn, source_name="Zeta Board")

    assert [r["key"] for r in rows] == ["b"]


def test_list_jobs_filters_by_removed_status(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("a", source_id="src")], run_id)
    db.reconcile_jobs(conn, configured_source_ids=set(), succeeded_source_ids={"src"}, found_jobs=[])

    active = db.list_jobs(conn, removed="active")
    removed = db.list_jobs(conn, removed="removed")

    assert active == []
    assert len(removed) == 1


def test_list_jobs_filters_by_emailed_status(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [_job("a")], db.start_run(conn))
    db.mark_emailed(conn, ["a"])

    assert len(db.list_jobs(conn, emailed="sent")) == 1
    assert db.list_jobs(conn, emailed="not_sent") == []


def test_list_jobs_combines_filters(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("a", company="Acme", source_name="Acme Board")], run_id)
    db.save_jobs(conn, [_job("b", company="Acme", source_name="Zeta Board")], run_id)

    rows = db.list_jobs(conn, company="acme", source_name="Zeta Board")

    assert [r["key"] for r in rows] == ["b"]


def test_count_jobs_respects_filters(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [_job("a", company="Acme")], db.start_run(conn))

    assert db.count_jobs(conn, company="acme") == 1
    assert db.count_jobs(conn, company="nope") == 0


def test_list_job_source_names_returns_distinct_sorted_names(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("a", source_name="Zeta Board")], run_id)
    db.save_jobs(conn, [_job("b", source_name="Acme Board")], run_id)
    db.save_jobs(conn, [_job("c", source_name="Acme Board")], run_id)

    assert db.list_job_source_names(conn) == ["Acme Board", "Zeta Board"]


def test_list_job_source_names_empty_when_no_jobs(tmp_db_path):
    conn = db.init_db(tmp_db_path)

    assert db.list_job_source_names(conn) == []


def test_init_db_creates_job_status_history_table(tmp_db_path):
    conn = db.init_db(tmp_db_path)

    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "job_status_history" in tables


def test_set_job_status_updates_current_status(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    db.set_job_status(conn, "k1", "applied")

    row = conn.execute("SELECT status FROM jobs WHERE key = 'k1'").fetchone()
    assert row[0] == "applied"


def test_set_job_status_records_a_history_entry(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    db.set_job_status(conn, "k1", "applied")

    history = db.get_job_status_history(conn, ["k1"])
    assert len(history["k1"]) == 1
    assert history["k1"][0]["status"] == "applied"
    assert history["k1"][0]["changed_at"] is not None


def test_set_job_status_appends_rather_than_replacing_history(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    db.set_job_status(conn, "k1", "applied")
    db.set_job_status(conn, "k1", "rejected")

    history = db.get_job_status_history(conn, ["k1"])
    assert [h["status"] for h in history["k1"]] == ["rejected", "applied"]
    row = conn.execute("SELECT status FROM jobs WHERE key = 'k1'").fetchone()
    assert row[0] == "rejected"


def test_set_job_status_to_none_clears_current_status_and_is_recorded(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.set_job_status(conn, "k1", "applied")

    db.set_job_status(conn, "k1", None)

    row = conn.execute("SELECT status FROM jobs WHERE key = 'k1'").fetchone()
    assert row[0] is None
    history = db.get_job_status_history(conn, ["k1"])
    assert [h["status"] for h in history["k1"]] == [None, "applied"]


def test_set_job_status_on_unknown_key_raises_key_error(tmp_db_path):
    conn = db.init_db(tmp_db_path)

    with pytest.raises(KeyError):
        db.set_job_status(conn, "does-not-exist", "applied")


def test_get_job_status_history_omits_key_with_no_changes(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    history = db.get_job_status_history(conn, ["k1"])

    assert history.get("k1", []) == []


def test_get_job_status_history_with_empty_keys_list_returns_empty_dict(tmp_db_path):
    conn = db.init_db(tmp_db_path)

    assert db.get_job_status_history(conn, []) == {}


def test_get_job_status_history_groups_by_key_for_a_batch(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job(key="k1"), make_job(key="k2")], db.start_run(conn))
    db.set_job_status(conn, "k1", "applied")
    db.set_job_status(conn, "k2", "ignored")

    history = db.get_job_status_history(conn, ["k1", "k2"])

    assert set(history.keys()) == {"k1", "k2"}
    assert history["k1"][0]["status"] == "applied"
    assert history["k2"][0]["status"] == "ignored"
