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
