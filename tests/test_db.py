from datetime import UTC, datetime, timedelta

import pytest

from app import db
from app.models import FailedSource, Job
from app.web.auth import hash_password as _hash_password


def _make_user(conn, username="u1"):
    return db.create_user(conn, username, f"{username}@x.test", _hash_password("pw"))["id"]


def make_job(key="k1", title="Engineer", source_id="s1", summary=None):
    return Job(key=key, title=title, url="https://x.test/1", company="Acme",
               location="Remote", posted_date=None, source_name="Acme Board",
               source_id=source_id, summary=summary)


def test_schema_has_geocoded_locations_table_and_jobs_fk(pg_conn):
    conn = pg_conn
    # Verify table exists
    row = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'geocoded_locations'"
    ).fetchone()
    assert row is not None

    # Verify FK from jobs.location → geocoded_locations.location
    row = conn.execute(
        "SELECT COUNT(*) FROM information_schema.referential_constraints rc "
        "JOIN information_schema.key_column_usage kcu "
        "ON rc.constraint_name = kcu.constraint_name "
        "WHERE kcu.table_name = 'jobs' AND kcu.column_name = 'location'"
    ).fetchone()
    assert row[0] >= 1


def test_fk_enforcement_rejects_a_job_location_with_no_geocoded_locations_row(pg_conn):
    import psycopg.errors
    conn = pg_conn
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "INSERT INTO jobs (key, title, url, source_name, first_seen_at, location) "
            "VALUES ('k1', 'Engineer', 'https://x.test/1', 'Acme Board', "
            "'2026-01-01T00:00:00+00:00', 'Nowhere, XX')"
        )


def test_save_jobs_creates_a_pending_geocoded_locations_stub_for_a_new_location(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)

    db.save_jobs(conn, [Job(key="k1", title="Engineer", url="https://x.test/1",
                             source_name="Acme Board", location="Chicago, IL")], run_id)

    row = conn.execute(
        "SELECT status FROM geocoded_locations WHERE location = 'Chicago, IL'"
    ).fetchone()
    assert row == ("pending",)


def test_save_jobs_reuses_an_existing_geocoded_locations_row_for_a_repeated_location(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [Job(key="k1", title="Engineer", url="https://x.test/1",
                             source_name="Acme Board", location="Chicago, IL")], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', lat = 41.8, lng = -87.6 "
        "WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    db.save_jobs(conn, [Job(key="k2", title="Sales", url="https://x.test/2",
                             source_name="Acme Board", location="Chicago, IL")], run_id)

    row = conn.execute(
        "SELECT status, lat FROM geocoded_locations WHERE location = 'Chicago, IL'"
    ).fetchone()
    assert row == ("resolved", 41.8)


def test_save_jobs_with_no_location_does_not_touch_geocoded_locations(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)

    db.save_jobs(conn, [Job(key="k1", title="Engineer", url="https://x.test/1",
                             source_name="Acme Board")], run_id)

    count = conn.execute("SELECT COUNT(*) FROM geocoded_locations").fetchone()[0]
    assert count == 0


def test_new_job_then_seen_on_second_run(pg_conn):
    conn = pg_conn
    job = make_job()

    assert db.get_new_jobs(conn, [job]) == [job]
    run_id = db.start_run(conn)
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])

    assert db.get_new_jobs(conn, [job]) == []


def test_clear_jobs_empties_the_table(pg_conn):
    conn = pg_conn
    job = make_job()
    run_id = db.start_run(conn)
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])
    assert db.get_new_jobs(conn, [job]) == []

    db.clear_jobs(conn)

    assert db.get_new_jobs(conn, [job]) == [job]


def test_clear_jobs_on_empty_table_does_not_raise(pg_conn):
    conn = pg_conn

    db.clear_jobs(conn)  # should not raise

    assert db.get_new_jobs(conn, [make_job()]) == [make_job()]


def test_list_runs_returns_most_recent_first(pg_conn):
    conn = pg_conn
    run1 = db.start_run(conn)
    db.finish_run(conn, run1, new_job_count=0, failed_sources=[FailedSource("Bad Co", url="https://jobs.bad.test")])
    run2 = db.start_run(conn)
    db.finish_run(conn, run2, new_job_count=2, failed_sources=[])

    runs = db.list_runs(conn)

    assert [r["id"] for r in runs] == [run2, run1]
    assert runs[1]["failed_sources"] == [{"name": "Bad Co", "url": "https://jobs.bad.test"}]


def test_list_runs_respects_offset(pg_conn):
    conn = pg_conn
    ids = [db.start_run(conn) for _ in range(3)]
    for run_id in ids:
        db.finish_run(conn, run_id, new_job_count=0, failed_sources=[])

    page2 = db.list_runs(conn, limit=2, offset=2)

    assert [r["id"] for r in page2] == [ids[0]]


def test_count_runs_returns_total(pg_conn):
    conn = pg_conn
    db.start_run(conn)
    db.start_run(conn)

    assert db.count_runs(conn) == 2


def test_list_runs_sorts_by_new_job_count_ascending(pg_conn):
    conn = pg_conn
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=5, failed_sources=[])
    r2 = db.start_run(conn)
    db.finish_run(conn, r2, new_job_count=1, failed_sources=[])

    rows = db.list_runs(conn, sort="new_job_count", direction="asc")

    assert [r["new_job_count"] for r in rows] == [1, 5]


def test_list_runs_sorts_by_started_at_descending(pg_conn):
    conn = pg_conn
    r1 = db.start_run(conn)
    r2 = db.start_run(conn)

    rows = db.list_runs(conn, sort="started_at", direction="desc")

    assert [r["id"] for r in rows] == [r2, r1]


def test_list_runs_default_ordering_unchanged_with_no_new_kwargs(pg_conn):
    conn = pg_conn
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=1, failed_sources=[])
    r2 = db.start_run(conn)
    db.finish_run(conn, r2, new_job_count=2, failed_sources=[])

    rows = db.list_runs(conn)

    assert [r["id"] for r in rows] == [r2, r1]


def test_list_runs_unrecognized_sort_falls_back_to_default(pg_conn):
    conn = pg_conn
    db.start_run(conn)

    rows = db.list_runs(conn, sort="garbage")

    assert len(rows) == 1


def test_list_runs_filters_only_failures(pg_conn):
    conn = pg_conn
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=0, failed_sources=[FailedSource("Bad Co", url="https://jobs.bad.test")])
    r2 = db.start_run(conn)
    db.finish_run(conn, r2, new_job_count=0, failed_sources=[])

    only = db.list_runs(conn, failures="only")
    clean = db.list_runs(conn, failures="clean")

    assert [r["id"] for r in only] == [r1]
    assert [r["id"] for r in clean] == [r2]


def test_list_runs_invalid_failures_value_returns_all(pg_conn):
    conn = pg_conn
    db.start_run(conn)
    db.start_run(conn)

    rows = db.list_runs(conn, failures="nonsense")

    assert len(rows) == 2


def test_count_runs_respects_failures_filter(pg_conn):
    conn = pg_conn
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=0, failed_sources=[FailedSource("Bad Co", url="https://jobs.bad.test")])

    assert db.count_runs(conn, failures="only") == 1
    assert db.count_runs(conn, failures="clean") == 0


def test_settings_seed_updates_smtp_fields_on_restart(pg_conn):
    conn = pg_conn
    user_id = _make_user(conn)
    db._seed_settings(conn, user_id, "smtp.example.com", 587, "user", "from@x.test", "to@x.test")
    # second call (e.g. after adding SMTP_HOST to Portainer env and restarting) updates SMTP fields
    db._seed_settings(conn, user_id, "new.example.com", 465, "newuser", "new@x.test", "i2@x.test")

    settings = db.get_settings(conn, user_id)
    assert settings["smtp_host"] == "new.example.com"
    assert settings["smtp_port"] == 465
    assert settings["smtp_user"] == "newuser"
    assert settings["email_from"] == "new@x.test"


def test_settings_seed_preserves_preference_columns_on_restart(pg_conn):
    conn = pg_conn
    user_id = _make_user(conn)
    db._seed_settings(conn, user_id, "smtp.example.com", 587, "user", "from@x.test", "original@x.test")
    db.save_preferences(conn, user_id, "mon,fri", True, "pref@x.test")
    # restart with different env vars — preferences must survive
    db._seed_settings(conn, user_id, "new.example.com", 465, "newuser", "new@x.test", "ignored@x.test")

    settings = db.get_settings(conn, user_id)
    assert settings["email_to"] == "pref@x.test"
    assert settings["email_days"] == "mon,fri"
    assert settings["resend_jobs"] is True


def test_save_settings_overwrites(pg_conn):
    conn = pg_conn
    user_id = _make_user(conn)
    db.save_settings(conn, user_id, "a.example.com", 587, "u1", "f@x.test")
    db.save_settings(conn, user_id, "b.example.com", 465, "u2", "f2@x.test")

    settings = db.get_settings(conn, user_id)
    assert settings["smtp_host"] == "b.example.com"
    assert settings["smtp_port"] == 465
    assert settings["smtp_user"] == "u2"
    assert settings["email_from"] == "f2@x.test"


def test_save_settings_does_not_touch_preference_columns(pg_conn):
    conn = pg_conn
    user_id = _make_user(conn)
    db.save_preferences(conn, user_id, "mon,wed,fri", True, "a@x.test,b@x.test")

    db.save_settings(conn, user_id, "a.example.com", 587, "u1", "f@x.test")

    settings = db.get_settings(conn, user_id)
    assert settings["email_days"] == "mon,wed,fri"
    assert settings["resend_jobs"] is True
    assert settings["email_to"] == "a@x.test,b@x.test"


def test_save_preferences_overwrites(pg_conn):
    conn = pg_conn
    user_id = _make_user(conn)
    db.save_preferences(conn, user_id, "mon,tue,wed,thu,fri,sat,sun", False, "a@x.test")
    db.save_preferences(conn, user_id, "mon,wed,fri", True, "a@x.test,b@x.test")

    settings = db.get_settings(conn, user_id)
    assert settings["email_days"] == "mon,wed,fri"
    assert settings["resend_jobs"] is True
    assert settings["email_to"] == "a@x.test,b@x.test"


def test_save_preferences_does_not_touch_smtp_columns(pg_conn):
    conn = pg_conn
    user_id = _make_user(conn)
    db.save_settings(conn, user_id, "a.example.com", 587, "u1", "f@x.test")

    db.save_preferences(conn, user_id, "mon", False, "a@x.test")

    settings = db.get_settings(conn, user_id)
    assert settings["smtp_host"] == "a.example.com"
    assert settings["smtp_port"] == 587
    assert settings["smtp_user"] == "u1"
    assert settings["email_from"] == "f@x.test"


def test_get_settings_defaults_days_and_resend_after_seeding(pg_conn):
    conn = pg_conn
    user_id = _make_user(conn)
    db._seed_settings(conn, user_id, "smtp.example.com", 587, "user", "from@x.test", "to@x.test")

    settings = db.get_settings(conn, user_id)
    assert settings["email_days"] == "mon,tue,wed,thu,fri,sat,sun"
    assert settings["resend_jobs"] is False
    assert settings["email_to"] == "to@x.test"
    assert settings["hide_not_interested_on_map"] is True


def test_save_preferences_defaults_hide_not_interested_on_map_to_true(pg_conn):
    conn = pg_conn
    user_id = _make_user(conn)
    db.save_preferences(conn, user_id, "mon", False, "a@x.test")

    settings = db.get_settings(conn, user_id)
    assert settings["hide_not_interested_on_map"] is True


def test_save_preferences_can_turn_off_hide_not_interested_on_map(pg_conn):
    conn = pg_conn
    user_id = _make_user(conn)
    db.save_preferences(conn, user_id, "mon", False, "a@x.test", hide_not_interested_on_map=False)

    settings = db.get_settings(conn, user_id)
    assert settings["hide_not_interested_on_map"] is False


def test_save_preferences_stores_digest_max_per_company(pg_conn):
    conn = pg_conn
    user_id = _make_user(conn)
    db.save_preferences(conn, user_id, "mon", False, "a@x.test", digest_max_per_company=10)

    settings = db.get_settings(conn, user_id)
    assert settings["digest_max_per_company"] == 10


def test_save_preferences_defaults_digest_max_per_company_to_zero(pg_conn):
    conn = pg_conn
    user_id = _make_user(conn)
    db.save_preferences(conn, user_id, "mon", False, "a@x.test")

    settings = db.get_settings(conn, user_id)
    assert settings["digest_max_per_company"] == 0


def test_save_preferences_stores_digest_exclude_statuses(pg_conn):
    conn = pg_conn
    user_id = _make_user(conn)
    db.save_preferences(conn, user_id, "mon", False, "a@x.test", digest_exclude_statuses="not_interested,rejected")

    settings = db.get_settings(conn, user_id)
    assert settings["digest_exclude_statuses"] == "not_interested,rejected"


def test_save_preferences_defaults_digest_exclude_statuses_to_empty(pg_conn):
    conn = pg_conn
    user_id = _make_user(conn)
    db.save_preferences(conn, user_id, "mon", False, "a@x.test")

    settings = db.get_settings(conn, user_id)
    assert settings["digest_exclude_statuses"] == ""


def test_schema_is_idempotent_with_fresh_connection(pg_conn):
    # Alembic upgrade head is idempotent; pg_conn IS the already-migrated connection
    conn = pg_conn
    user_id = _make_user(conn)
    assert db.get_settings(conn, user_id) is None

def test_save_jobs_persists_source_id_and_summary(pg_conn):
    conn = pg_conn
    job = make_job(source_id="src-1", summary="A great role.")
    run_id = db.start_run(conn)

    db.save_jobs(conn, [job], run_id)

    rows = db.list_jobs(conn)
    assert rows[0]["source_id"] == "src-1"
    assert rows[0]["summary"] == "A great role."
    assert rows[0]["removed_at"] is None
    assert rows[0]["emailed_at"] is None


def test_list_jobs_orders_newest_first(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.save_jobs(conn, [make_job(key="k2")], db.start_run(conn))

    rows = db.list_jobs(conn)

    assert [r["key"] for r in rows] == ["k2", "k1"]


def test_list_jobs_respects_limit_and_offset(pg_conn):
    conn = pg_conn
    for i in range(3):
        db.save_jobs(conn, [make_job(key=f"k{i}")], db.start_run(conn))

    page = db.list_jobs(conn, limit=1, offset=1)

    assert len(page) == 1


def test_count_jobs_returns_total(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1"), make_job(key="k2")], db.start_run(conn))

    assert db.count_jobs(conn) == 2


def test_mark_emailed_sets_timestamp_for_given_keys_only(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1"), make_job(key="k2")], db.start_run(conn))

    db.mark_emailed(conn, ["k1"])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["emailed_at"] is not None
    assert rows["k2"]["emailed_at"] is None


def test_mark_emailed_with_empty_list_does_not_raise(pg_conn):
    conn = pg_conn

    db.mark_emailed(conn, [])  # should not raise


def test_reconcile_jobs_marks_missing_job_removed_when_its_source_succeeded(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1", source_id="s1")], db.start_run(conn))

    db.reconcile_jobs(conn, configured_source_ids={"s1"}, succeeded_source_ids={"s1"}, found_jobs=[])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["removed_at"] is not None


def test_reconcile_jobs_leaves_job_untouched_when_still_found(pg_conn):
    conn = pg_conn
    job = make_job(key="k1", source_id="s1")
    db.save_jobs(conn, [job], db.start_run(conn))

    db.reconcile_jobs(conn, configured_source_ids={"s1"}, succeeded_source_ids={"s1"}, found_jobs=[job])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["removed_at"] is None


def test_reconcile_jobs_reactivates_a_removed_job_that_reappears(pg_conn):
    conn = pg_conn
    job = make_job(key="k1", source_id="s1")
    db.save_jobs(conn, [job], db.start_run(conn))
    db.reconcile_jobs(conn, configured_source_ids={"s1"}, succeeded_source_ids={"s1"}, found_jobs=[])
    assert db.list_jobs(conn)[0]["removed_at"] is not None

    db.reconcile_jobs(conn, configured_source_ids={"s1"}, succeeded_source_ids={"s1"}, found_jobs=[job])

    assert db.list_jobs(conn)[0]["removed_at"] is None


def test_reconcile_jobs_ignores_jobs_from_a_source_that_merely_failed_this_run(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1", source_id="s1")], db.start_run(conn))

    # s1 is still configured but did not succeed this run (e.g. it raised) -- must not be touched.
    db.reconcile_jobs(conn, configured_source_ids={"s1"}, succeeded_source_ids=set(), found_jobs=[])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["removed_at"] is None


def test_reconcile_jobs_marks_removed_when_its_source_is_deleted_from_config(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1", source_id="s1")], db.start_run(conn))

    # s1 no longer appears in configured_source_ids at all -- deleted from sources.json.
    db.reconcile_jobs(conn, configured_source_ids=set(), succeeded_source_ids=set(), found_jobs=[])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["removed_at"] is not None


def test_reconcile_jobs_leaves_legacy_rows_with_no_source_id_untouched(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1", source_id=None)], db.start_run(conn))

    db.reconcile_jobs(conn, configured_source_ids=set(), succeeded_source_ids=set(), found_jobs=[])

    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["removed_at"] is None


def test_mark_job_removed_sets_removed_at(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    db.mark_job_removed(conn, "k1")

    assert db.list_jobs(conn)[0]["removed_at"] is not None


def test_mark_job_removed_is_idempotent_on_already_removed_job(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.mark_job_removed(conn, "k1")
    first_removed_at = db.list_jobs(conn)[0]["removed_at"]

    db.mark_job_removed(conn, "k1")

    assert db.list_jobs(conn)[0]["removed_at"] == first_removed_at


def test_mark_job_removed_raises_key_error_for_unknown_key(pg_conn):
    conn = pg_conn

    with pytest.raises(KeyError):
        db.mark_job_removed(conn, "no-such-key")


def _job(key, company="Acme", title="Engineer", source_name="Acme Board", source_id="s1"):
    return Job(key=key, title=title, url="https://x.test/1", company=company,
               location="Remote", posted_date=None, source_name=source_name,
               source_id=source_id, summary=None)


def test_list_jobs_sorts_by_company_ascending(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("a", company="Zeta")], run_id)
    db.save_jobs(conn, [_job("b", company="Acme")], run_id)

    rows = db.list_jobs(conn, sort="company", direction="asc")

    assert [r["company"] for r in rows] == ["Acme", "Zeta"]


def test_list_jobs_sorts_by_company_descending(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("a", company="Zeta")], run_id)
    db.save_jobs(conn, [_job("b", company="Acme")], run_id)

    rows = db.list_jobs(conn, sort="company", direction="desc")

    assert [r["company"] for r in rows] == ["Zeta", "Acme"]


def test_list_jobs_sorts_by_age_days(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("young")], run_id)
    db.save_jobs(conn, [_job("old")], run_id)
    conn.execute(
        "UPDATE jobs SET first_seen_at = %s WHERE key = 'old'",
        ((datetime.now(UTC) - timedelta(days=30)).isoformat(),),
    )
    conn.commit()

    rows = db.list_jobs(conn, sort="age_days", direction="desc")

    assert [r["key"] for r in rows] == ["old", "young"]


def test_list_jobs_default_ordering_unchanged_with_no_new_kwargs(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [_job("a")], db.start_run(conn))
    db.save_jobs(conn, [_job("b")], db.start_run(conn))

    rows = db.list_jobs(conn)

    assert [r["key"] for r in rows] == ["b", "a"]


def test_list_jobs_unrecognized_sort_falls_back_to_default(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [_job("a")], db.start_run(conn))

    rows = db.list_jobs(conn, sort="'; DROP TABLE jobs; --")

    assert len(rows) == 1


def test_list_jobs_filters_by_company_substring_case_insensitive(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("a", company="Acme Corp")], run_id)
    db.save_jobs(conn, [_job("b", company="Zenith")], run_id)

    rows = db.list_jobs(conn, company="acme")

    assert [r["key"] for r in rows] == ["a"]


def test_list_jobs_filters_by_source_name(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("a", source_name="Acme Board")], run_id)
    db.save_jobs(conn, [_job("b", source_name="Zeta Board")], run_id)

    rows = db.list_jobs(conn, source_name=["Zeta Board"])

    assert [r["key"] for r in rows] == ["b"]


def test_list_jobs_multi_source_name_returns_union(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("a", source_name="Acme Board")], run_id)
    db.save_jobs(conn, [_job("b", source_name="Zeta Board")], run_id)
    db.save_jobs(conn, [_job("c", source_name="Other Board")], run_id)

    rows = db.list_jobs(conn, source_name=["Acme Board", "Zeta Board"])

    assert {r["key"] for r in rows} == {"a", "b"}


def test_list_jobs_filters_by_removed_status(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("a", source_id="src")], run_id)
    db.reconcile_jobs(conn, configured_source_ids=set(), succeeded_source_ids={"src"}, found_jobs=[])

    active = db.list_jobs(conn, removed="active")
    removed = db.list_jobs(conn, removed="removed")

    assert active == []
    assert len(removed) == 1


def test_list_jobs_filters_by_emailed_status(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [_job("a")], db.start_run(conn))
    db.mark_emailed(conn, ["a"])

    assert len(db.list_jobs(conn, emailed="sent")) == 1
    assert db.list_jobs(conn, emailed="not_sent") == []


def test_list_jobs_combines_filters(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("a", company="Acme", source_name="Acme Board")], run_id)
    db.save_jobs(conn, [_job("b", company="Acme", source_name="Zeta Board")], run_id)

    rows = db.list_jobs(conn, company="acme", source_name=["Zeta Board"])

    assert [r["key"] for r in rows] == ["b"]


def test_count_jobs_respects_filters(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [_job("a", company="Acme")], db.start_run(conn))

    assert db.count_jobs(conn, company="acme") == 1
    assert db.count_jobs(conn, company="nope") == 0


def test_list_job_source_names_returns_distinct_sorted_names(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [_job("a", source_name="Zeta Board")], run_id)
    db.save_jobs(conn, [_job("b", source_name="Acme Board")], run_id)
    db.save_jobs(conn, [_job("c", source_name="Acme Board")], run_id)

    assert db.list_job_source_names(conn) == ["Acme Board", "Zeta Board"]


def test_list_job_source_names_empty_when_no_jobs(pg_conn):
    conn = pg_conn

    assert db.list_job_source_names(conn) == []


def test_schema_has_job_status_history_table(pg_conn):
    conn = pg_conn
    row = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'job_status_history'"
    ).fetchone()
    assert row is not None


def test_set_job_status_updates_current_status(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    db.set_job_status(conn, "k1", "applied")

    row = conn.execute("SELECT status FROM jobs WHERE key = 'k1'").fetchone()
    assert row[0] == "applied"


def test_set_job_status_records_a_history_entry(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    db.set_job_status(conn, "k1", "applied")

    history = db.get_job_status_history(conn, ["k1"])
    assert len(history["k1"]) == 1
    assert history["k1"][0]["status"] == "applied"
    assert history["k1"][0]["changed_at"] is not None


def test_set_job_status_appends_rather_than_replacing_history(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    db.set_job_status(conn, "k1", "applied")
    db.set_job_status(conn, "k1", "rejected")

    history = db.get_job_status_history(conn, ["k1"])
    assert [h["status"] for h in history["k1"]] == ["rejected", "applied"]
    row = conn.execute("SELECT status FROM jobs WHERE key = 'k1'").fetchone()
    assert row[0] == "rejected"


def test_set_job_status_to_none_clears_current_status_and_is_recorded(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.set_job_status(conn, "k1", "applied")

    db.set_job_status(conn, "k1", None)

    row = conn.execute("SELECT status FROM jobs WHERE key = 'k1'").fetchone()
    assert row[0] is None
    history = db.get_job_status_history(conn, ["k1"])
    assert [h["status"] for h in history["k1"]] == [None, "applied"]


def test_set_job_status_on_unknown_key_raises_key_error(pg_conn):
    conn = pg_conn

    with pytest.raises(KeyError):
        db.set_job_status(conn, "does-not-exist", "applied")


def test_get_job_status_history_omits_key_with_no_changes(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    history = db.get_job_status_history(conn, ["k1"])

    assert history.get("k1", []) == []


def test_get_job_status_history_with_empty_keys_list_returns_empty_dict(pg_conn):
    conn = pg_conn

    assert db.get_job_status_history(conn, []) == {}


def test_get_job_status_history_groups_by_key_for_a_batch(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1"), make_job(key="k2")], db.start_run(conn))
    db.set_job_status(conn, "k1", "applied")
    db.set_job_status(conn, "k2", "ignored")

    history = db.get_job_status_history(conn, ["k1", "k2"])

    assert set(history.keys()) == {"k1", "k2"}
    assert history["k1"][0]["status"] == "applied"
    assert history["k2"][0]["status"] == "ignored"


def test_get_job_statuses_returns_current_status_per_key(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1"), make_job(key="k2")], db.start_run(conn))
    db.set_job_status(conn, "k1", "not_interested")

    statuses = db.get_job_statuses(conn, ["k1", "k2"])

    assert statuses == {"k1": "not_interested", "k2": None}


def test_get_job_statuses_with_empty_keys_list_returns_empty_dict(pg_conn):
    conn = pg_conn

    assert db.get_job_statuses(conn, []) == {}


def test_get_emailed_keys_returns_only_keys_with_emailed_at_set(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1"), make_job(key="k2")], db.start_run(conn))
    db.mark_emailed(conn, ["k1"])

    result = db.get_emailed_keys(conn, ["k1", "k2"])

    assert result == {"k1"}


def test_get_emailed_keys_returns_empty_set_when_none_emailed(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    assert db.get_emailed_keys(conn, ["k1"]) == set()


def test_get_emailed_keys_with_empty_list_returns_empty_set(pg_conn):
    conn = pg_conn

    assert db.get_emailed_keys(conn, []) == set()


def test_list_jobs_filters_by_status(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [_job("a"), _job("b")], db.start_run(conn))
    db.set_job_status(conn, "a", "applied")

    applied = db.list_jobs(conn, status=["applied"])
    none_status = db.list_jobs(conn, status=["none"])

    assert [r["key"] for r in applied] == ["a"]
    assert [r["key"] for r in none_status] == ["b"]


def test_list_jobs_multi_status_returns_union(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [_job("a"), _job("b"), _job("c")], db.start_run(conn))
    db.set_job_status(conn, "a", "applied")
    db.set_job_status(conn, "b", "rejected")

    rows = db.list_jobs(conn, status=["applied", "rejected"])

    assert {r["key"] for r in rows} == {"a", "b"}


def test_list_jobs_multi_status_with_none_returns_union_including_no_status(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [_job("a"), _job("b"), _job("c")], db.start_run(conn))
    db.set_job_status(conn, "a", "applied")

    rows = db.list_jobs(conn, status=["applied", "none"])

    assert {r["key"] for r in rows} == {"a", "b", "c"}


def test_count_jobs_respects_status_filter(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [_job("a")], db.start_run(conn))
    db.set_job_status(conn, "a", "rejected")

    assert db.count_jobs(conn, status=["rejected"]) == 1
    assert db.count_jobs(conn, status=["applied"]) == 0


def test_list_jobs_returns_status_field_defaulting_to_none(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [_job("a")], db.start_run(conn))

    rows = db.list_jobs(conn)

    assert rows[0]["status"] is None


def test_list_job_locations_returns_distinct_resolved_display_names(pg_conn):
    conn = pg_conn
    conn.execute(
        "INSERT INTO geocoded_locations (location, display_name, status) VALUES "
        "('Chicago, IL', 'Chicago, IL', 'resolved'), "
        "('Chicago, Illinois', 'Chicago, IL', 'resolved'), "
        "('Nowhere', NULL, 'failed')"
    )
    conn.commit()

    assert db.list_job_locations(conn) == ["Chicago, IL"]


def test_list_jobs_location_filter_matches_by_resolved_display_name(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        Job(key="a", title="A", url="https://x.test/a", source_name="Src", location="Chicago, IL"),
        Job(key="b", title="B", url="https://x.test/b", source_name="Src", location="Austin, TX"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL' "
        "WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    rows = db.list_jobs(conn, location="Chicago, IL")

    assert [r["key"] for r in rows] == ["a"]
    assert rows[0]["location"] == "Chicago, IL"


def test_list_jobs_unresolved_location_sentinel_matches_pending_and_failed(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        Job(key="a", title="A", url="https://x.test/a", source_name="Src", location="Chicago, IL"),
        Job(key="b", title="B", url="https://x.test/b", source_name="Src", location="Remote"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL' "
        "WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    rows = db.list_jobs(conn, location="__unresolved__")

    assert [r["key"] for r in rows] == ["b"]
    assert rows[0]["location"] == "Remote"


def test_count_jobs_location_filter_matches_list_jobs(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        Job(key="a", title="A", url="https://x.test/a", source_name="Src", location="Chicago, IL"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL' "
        "WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    assert db.count_jobs(conn, location="Chicago, IL") == 1
    assert db.count_jobs(conn, location="Austin, TX") == 0


def test_list_mappable_jobs_returns_only_resolved_locations(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        Job(key="a", title="A", url="https://x.test/a", company="Acme", source_name="Src", location="Chicago, IL"),
        Job(key="b", title="B", url="https://x.test/b", company="Acme", source_name="Src", location="Remote"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL', "
        "lat = 41.8, lng = -87.6 WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    rows = db.list_mappable_jobs(conn)

    assert [r["key"] for r in rows] == ["a"]
    assert rows[0] == {
        "key": "a", "title": "A", "company": "Acme", "url": "https://x.test/a",
        "is_overridden": False,
        "display_name": "Chicago, IL", "lat": 41.8, "lng": -87.6,
    }


def test_list_mappable_jobs_applies_the_same_filters_as_list_jobs(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        Job(key="a", title="A", url="https://x.test/a", company="Acme", source_name="Src", location="Chicago, IL"),
        Job(key="b", title="B", url="https://x.test/b", company="Zeta", source_name="Src", location="Chicago, IL"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL', "
        "lat = 41.8, lng = -87.6 WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    rows = db.list_mappable_jobs(conn, company="Acme")

    assert [r["key"] for r in rows] == ["a"]


def test_list_mappable_jobs_exclude_status_omits_matching_jobs(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        Job(key="a", title="A", url="https://x.test/a", company="Acme", source_name="Src", location="Chicago, IL"),
        Job(key="b", title="B", url="https://x.test/b", company="Acme", source_name="Src", location="Chicago, IL"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL', "
        "lat = 41.8, lng = -87.6 WHERE location = 'Chicago, IL'"
    )
    conn.commit()
    db.set_job_status(conn, "b", "not_interested")

    rows = db.list_mappable_jobs(conn, exclude_status="not_interested")

    assert [r["key"] for r in rows] == ["a"]


def test_list_mappable_jobs_without_exclude_status_includes_everything(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        Job(key="a", title="A", url="https://x.test/a", company="Acme", source_name="Src", location="Chicago, IL"),
        Job(key="b", title="B", url="https://x.test/b", company="Acme", source_name="Src", location="Chicago, IL"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'Chicago, IL', "
        "lat = 41.8, lng = -87.6 WHERE location = 'Chicago, IL'"
    )
    conn.commit()
    db.set_job_status(conn, "b", "not_interested")

    rows = db.list_mappable_jobs(conn)

    assert {r["key"] for r in rows} == {"a", "b"}


# --- Location override tests (issue #84) ---

def _make_chicago_job(conn, key="job1"):
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        Job(key=key, title="Engineer", url="https://x.test/1", company="Acme",
            location="Remote", source_name="Src", source_id="s1"),
    ], run_id)
    return key

def test_set_location_override_stores_geocoded_entry_and_links_job(pg_conn):
    conn = pg_conn
    _make_chicago_job(conn)

    db.set_location_override(
        conn, "job1", "Chicago, IL",
        display_name="Chicago, Cook County, Illinois, United States",
        city="Chicago", region="Illinois", country="United States",
        lat=41.8781, lng=-87.6298, provider="nominatim",
    )

    row = conn.execute(
        "SELECT location_override FROM jobs WHERE key = 'job1'"
    ).fetchone()
    assert row == ("Chicago, IL",)

    geo = conn.execute(
        "SELECT status, display_name, lat, lng, provider FROM geocoded_locations WHERE location = 'Chicago, IL'"
    ).fetchone()
    assert geo[0] == "manual"
    assert geo[1] == "Chicago, Cook County, Illinois, United States"
    assert geo[2] == 41.8781
    assert geo[3] == -87.6298
    assert geo[4] == "nominatim"


def test_set_location_override_raises_for_unknown_job(pg_conn):
    conn = pg_conn
    with pytest.raises(KeyError):
        db.set_location_override(
            conn, "no-such-key", "Chicago, IL",
            display_name="Chicago", city="Chicago", region="IL", country="US",
            lat=41.8, lng=-87.6, provider="nominatim",
        )


def test_set_location_override_upserts_existing_geocoded_entry(pg_conn):
    conn = pg_conn
    _make_chicago_job(conn)
    db.set_location_override(
        conn, "job1", "Chicago, IL",
        display_name="Old Name", city="Chicago", region="IL", country="US",
        lat=41.0, lng=-87.0, provider="nominatim",
    )

    db.set_location_override(
        conn, "job1", "Chicago, IL",
        display_name="Chicago, Illinois, USA", city="Chicago", region="Illinois", country="USA",
        lat=41.8781, lng=-87.6298, provider="nominatim",
    )

    geo = conn.execute(
        "SELECT display_name, lat FROM geocoded_locations WHERE location = 'Chicago, IL'"
    ).fetchone()
    assert geo == ("Chicago, Illinois, USA", 41.8781)


def test_clear_location_override_removes_override(pg_conn):
    conn = pg_conn
    _make_chicago_job(conn)
    db.set_location_override(
        conn, "job1", "Chicago, IL",
        display_name="Chicago", city="Chicago", region="IL", country="US",
        lat=41.8, lng=-87.6, provider="nominatim",
    )

    db.clear_location_override(conn, "job1")

    row = conn.execute("SELECT location_override FROM jobs WHERE key = 'job1'").fetchone()
    assert row == (None,)


def test_clear_location_override_raises_for_unknown_job(pg_conn):
    conn = pg_conn
    with pytest.raises(KeyError):
        db.clear_location_override(conn, "no-such-key")


def test_list_jobs_includes_is_overridden_false_when_no_override(pg_conn):
    conn = pg_conn
    _make_chicago_job(conn)

    rows = db.list_jobs(conn)

    assert rows[0]["is_overridden"] is False
    assert rows[0]["location_override"] is None


def test_list_jobs_includes_is_overridden_true_and_shows_override_display_name(pg_conn):
    conn = pg_conn
    _make_chicago_job(conn)
    db.set_location_override(
        conn, "job1", "Chicago, IL",
        display_name="Chicago, Illinois, USA", city="Chicago", region="IL", country="US",
        lat=41.8781, lng=-87.6298, provider="nominatim",
    )

    rows = db.list_jobs(conn)

    assert rows[0]["is_overridden"] is True
    assert rows[0]["location_override"] == "Chicago, IL"
    assert rows[0]["location"] == "Chicago, Illinois, USA"


def test_list_mappable_jobs_uses_override_location_for_map(pg_conn):
    conn = pg_conn
    _make_chicago_job(conn)
    db.set_location_override(
        conn, "job1", "Chicago, IL",
        display_name="Chicago, Illinois, USA", city="Chicago", region="IL", country="US",
        lat=41.8781, lng=-87.6298, provider="nominatim",
    )

    rows = db.list_mappable_jobs(conn)

    assert len(rows) == 1
    assert rows[0]["is_overridden"] is True
    assert rows[0]["lat"] == 41.8781
    assert rows[0]["display_name"] == "Chicago, Illinois, USA"


def test_list_mappable_jobs_original_location_not_on_map_after_override(pg_conn):
    """Original 'Remote' location had no geocoded coords; after override the job appears on map."""
    conn = pg_conn
    _make_chicago_job(conn)

    rows_before = db.list_mappable_jobs(conn)
    assert rows_before == []

    db.set_location_override(
        conn, "job1", "Austin, TX",
        display_name="Austin, TX, USA", city="Austin", region="Texas", country="USA",
        lat=30.2672, lng=-97.7431, provider="nominatim",
    )

    rows_after = db.list_mappable_jobs(conn)
    assert len(rows_after) == 1
    assert rows_after[0]["lat"] == 30.2672


# ── Duplicate flag ─────────────────────────────────────────────────────────────

def test_set_job_duplicate_marks_job_and_stores_reference(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    db.set_job_duplicate(conn, "k1", duplicate_of="Acme — Engineer (Greenhouse)")

    rows = db.list_jobs(conn, duplicates="include")
    assert rows[0]["is_duplicate"] is True
    assert rows[0]["duplicate_of"] == "Acme — Engineer (Greenhouse)"


def test_set_job_duplicate_without_reference(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    db.set_job_duplicate(conn, "k1")

    rows = db.list_jobs(conn, duplicates="include")
    assert rows[0]["is_duplicate"] is True
    assert rows[0]["duplicate_of"] is None


def test_clear_job_duplicate_removes_flag(pg_conn):
    conn = pg_conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.set_job_duplicate(conn, "k1", duplicate_of="Some Job")

    db.clear_job_duplicate(conn, "k1")

    rows = db.list_jobs(conn)
    assert rows[0]["is_duplicate"] is False
    assert rows[0]["duplicate_of"] is None


def test_set_job_duplicate_raises_for_unknown_key(pg_conn):
    conn = pg_conn

    with pytest.raises(KeyError):
        db.set_job_duplicate(conn, "no-such-key")


def test_clear_job_duplicate_raises_for_unknown_key(pg_conn):
    conn = pg_conn

    with pytest.raises(KeyError):
        db.clear_job_duplicate(conn, "no-such-key")


def test_list_jobs_hides_duplicates_by_default(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="k1"), make_job(key="k2")], run_id)
    db.set_job_duplicate(conn, "k2")

    rows = db.list_jobs(conn)

    assert len(rows) == 1
    assert rows[0]["key"] == "k1"


def test_list_jobs_includes_duplicates_when_requested(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="k1"), make_job(key="k2")], run_id)
    db.set_job_duplicate(conn, "k2")

    rows = db.list_jobs(conn, duplicates="include")

    assert len(rows) == 2


def test_list_jobs_returns_only_duplicates(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="k1"), make_job(key="k2")], run_id)
    db.set_job_duplicate(conn, "k2")

    rows = db.list_jobs(conn, duplicates="only")

    assert len(rows) == 1
    assert rows[0]["key"] == "k2"


def test_count_jobs_excludes_duplicates_by_default(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="k1"), make_job(key="k2")], run_id)
    db.set_job_duplicate(conn, "k2")

    assert db.count_jobs(conn) == 1
    assert db.count_jobs(conn, duplicates="include") == 2


def test_list_mappable_jobs_excludes_duplicates_by_default(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        Job(key="k1", title="Engineer", url="https://x.test/1", company="Acme",
            location="Chicago, IL", source_name="Board", source_id="s1"),
        Job(key="k2", title="Engineer 2", url="https://x.test/2", company="Acme",
            location="Chicago, IL", source_name="Indeed", source_id="s2"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status='resolved', lat=41.8, lng=-87.6 WHERE location='Chicago, IL'"
    )
    conn.commit()
    db.set_job_duplicate(conn, "k2")

    rows = db.list_mappable_jobs(conn)

    assert len(rows) == 1
    assert rows[0]["key"] == "k1"


# --- Failed source serialization tests (issue #93) ---

def test_finish_run_serializes_failed_source_with_url(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)

    db.finish_run(conn, run_id, new_job_count=0,
                  failed_sources=[FailedSource("Acme Jobs", url="https://acme.test/careers")])

    runs = db.list_runs(conn)
    assert runs[0]["failed_sources"] == [{"name": "Acme Jobs", "url": "https://acme.test/careers"}]


def test_finish_run_serializes_failed_source_without_url(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)

    db.finish_run(conn, run_id, new_job_count=0,
                  failed_sources=[FailedSource("Greenhouse Co", url=None)])

    runs = db.list_runs(conn)
    assert runs[0]["failed_sources"] == [{"name": "Greenhouse Co", "url": None}]


def test_finish_run_serializes_multiple_failed_sources(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)

    db.finish_run(conn, run_id, new_job_count=0, failed_sources=[
        FailedSource("Source A", url="https://a.test"),
        FailedSource("Source B", url=None),
    ])

    runs = db.list_runs(conn)
    assert runs[0]["failed_sources"] == [
        {"name": "Source A", "url": "https://a.test"},
        {"name": "Source B", "url": None},
    ]


def test_list_runs_deserializes_legacy_string_format(pg_conn):

    conn = pg_conn
    run_id = db.start_run(conn)
    conn.execute(
        "UPDATE runs SET finished_at = '2026-01-01T00:00:00+00:00', new_job_count = 0, "
        "failed_sources = %s WHERE id = %s",
        ('["Old Source"]', run_id),
    )
    conn.commit()

    runs = db.list_runs(conn)

    assert runs[0]["failed_sources"] == [{"name": "Old Source", "url": None}]


def test_list_runs_deserializes_new_dict_format(pg_conn):
    import json

    conn = pg_conn
    run_id = db.start_run(conn)
    conn.execute(
        "UPDATE runs SET finished_at = '2026-01-01T00:00:00+00:00', new_job_count = 0, "
        "failed_sources = %s WHERE id = %s",
        (json.dumps([{"name": "New Source", "url": "https://new.test"}]), run_id),
    )
    conn.commit()

    runs = db.list_runs(conn)

    assert runs[0]["failed_sources"] == [{"name": "New Source", "url": "https://new.test"}]


# ── haversine function (SQL) ─────────────────────────────────────────────────

def test_haversine_registered_on_db_connection(pg_conn):
    # Verify haversine_miles SQL function is available in PostgreSQL
    conn = pg_conn
    result = conn.execute(
        "SELECT haversine_miles(41.8781, -87.6298, 43.0389, -87.9065)"
    ).fetchone()[0]
    assert 78 < result < 85


# ── list_job_states ──────────────────────────────────────────────────────────

def test_list_job_states_returns_distinct_geocoded_regions(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    from app.models import Job
    db.save_jobs(conn, [
        Job(key="k1", title="A", url="https://x.test/1", source_name="Board", location="Chicago, IL"),
        Job(key="k2", title="B", url="https://x.test/2", source_name="Board", location="Milwaukee, WI"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', region = 'Illinois' "
        "WHERE location = 'Chicago, IL'"
    )
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', region = 'Wisconsin' "
        "WHERE location = 'Milwaukee, WI'"
    )
    conn.commit()

    states = db.list_job_states(conn)

    assert states == ["Illinois", "Wisconsin"]


def test_list_job_states_excludes_pending_locations(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    from app.models import Job
    db.save_jobs(conn, [
        Job(key="k1", title="A", url="https://x.test/1", source_name="Board", location="Chicago, IL"),
    ], run_id)
    # location stays 'pending', no region set

    states = db.list_job_states(conn)

    assert states == []


def test_list_job_states_deduplicates_same_region(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    from app.models import Job
    db.save_jobs(conn, [
        Job(key="k1", title="A", url="https://x.test/1", source_name="Board", location="Chicago, IL"),
        Job(key="k2", title="B", url="https://x.test/2", source_name="Board", location="Naperville, IL"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', region = 'Illinois' "
        "WHERE location IN ('Chicago, IL', 'Naperville, IL')"
    )
    conn.commit()

    states = db.list_job_states(conn)

    assert states == ["Illinois"]


# ── state filter ─────────────────────────────────────────────────────────────

def _make_geocoded_job(conn, key, title, location, region, lat=None, lng=None):
    """Helper: save a job and set its geocoded_locations row."""
    from app.models import Job
    run_id = db.start_run(conn)
    db.save_jobs(conn, [Job(key=key, title=title, url=f"https://x.test/{key}",
                             source_name="Board", location=location)], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', region = %s WHERE location = %s",
        [region, location],
    )
    if lat is not None:
        conn.execute(
            "UPDATE geocoded_locations SET lat = %s, lng = %s WHERE location = %s",
            [lat, lng, location],
        )
    conn.commit()


def test_state_filter_narrows_to_matching_region(pg_conn):
    conn = pg_conn
    _make_geocoded_job(conn, "k1", "IL Job", "Chicago, IL", "Illinois")
    _make_geocoded_job(conn, "k2", "WI Job", "Milwaukee, WI", "Wisconsin")

    rows = db.list_jobs(conn, state=["Illinois"])

    assert len(rows) == 1
    assert rows[0]["title"] == "IL Job"


def test_state_filter_multi_returns_union(pg_conn):
    conn = pg_conn
    _make_geocoded_job(conn, "k1", "IL Job", "Chicago, IL", "Illinois")
    _make_geocoded_job(conn, "k2", "WI Job", "Milwaukee, WI", "Wisconsin")
    _make_geocoded_job(conn, "k3", "TX Job", "Dallas, TX", "Texas")

    rows = db.list_jobs(conn, state=["Illinois", "Wisconsin"])

    assert {r["key"] for r in rows} == {"k1", "k2"}


def test_state_filter_with_no_match_returns_empty(pg_conn):
    conn = pg_conn
    _make_geocoded_job(conn, "k1", "IL Job", "Chicago, IL", "Illinois")

    rows = db.list_jobs(conn, state=["Texas"])

    assert rows == []


def test_count_jobs_with_state_filter(pg_conn):
    conn = pg_conn
    _make_geocoded_job(conn, "k1", "IL Job", "Chicago, IL", "Illinois")
    _make_geocoded_job(conn, "k2", "WI Job", "Milwaukee, WI", "Wisconsin")

    assert db.count_jobs(conn, state=["Illinois"]) == 1
    assert db.count_jobs(conn, state=["Wisconsin"]) == 1
    assert db.count_jobs(conn) == 2


def test_list_mappable_jobs_with_state_filter(pg_conn):
    conn = pg_conn
    _make_geocoded_job(conn, "k1", "IL Job", "Chicago, IL", "Illinois", lat=41.8, lng=-87.6)
    _make_geocoded_job(conn, "k2", "WI Job", "Milwaukee, WI", "Wisconsin", lat=43.0, lng=-87.9)

    rows = db.list_mappable_jobs(conn, state=["Illinois"])

    assert len(rows) == 1
    assert rows[0]["key"] == "k1"


# ── zip/radius filter ─────────────────────────────────────────────────────────

def test_haversine_filter_includes_job_within_radius(pg_conn):
    conn = pg_conn
    # Chicago job at ~0 miles from search center (Chicago)
    _make_geocoded_job(conn, "k1", "Chicago Job", "Chicago, IL", "Illinois",
                       lat=41.8781, lng=-87.6298)

    rows = db.list_jobs(conn, zip_lat=41.8781, zip_lng=-87.6298, radius_miles=50.0)

    assert len(rows) == 1
    assert rows[0]["title"] == "Chicago Job"


def test_haversine_filter_excludes_job_outside_radius(pg_conn):
    conn = pg_conn
    # LA is ~1750 miles from Chicago
    _make_geocoded_job(conn, "k1", "LA Job", "Los Angeles, CA", "California",
                       lat=34.0522, lng=-118.2437)

    rows = db.list_jobs(conn, zip_lat=41.8781, zip_lng=-87.6298, radius_miles=50.0)

    assert rows == []


def test_haversine_filter_excludes_job_with_null_coordinates(pg_conn):
    conn = pg_conn
    # Save job but leave lat/lng null (pending geocode)
    from app.models import Job
    run_id = db.start_run(conn)
    db.save_jobs(conn, [Job(key="k1", title="No Coords", url="https://x.test/1",
                             source_name="Board", location="Remote")], run_id)
    # geocoded_locations row exists but lat/lng are null

    rows = db.list_jobs(conn, zip_lat=41.8781, zip_lng=-87.6298, radius_miles=50.0)

    assert rows == []


def test_haversine_filter_boundary_distance_included_and_excluded(pg_conn):
    conn = pg_conn
    # Milwaukee is ~81 miles from Chicago (great-circle) — inside 100 mi, outside 50 mi
    _make_geocoded_job(conn, "k1", "Milwaukee Job", "Milwaukee, WI", "Wisconsin",
                       lat=43.0389, lng=-87.9065)

    inside = db.list_jobs(conn, zip_lat=41.8781, zip_lng=-87.6298, radius_miles=100.0)
    outside = db.list_jobs(conn, zip_lat=41.8781, zip_lng=-87.6298, radius_miles=50.0)

    assert len(inside) == 1
    assert outside == []


def test_count_jobs_with_radius_filter(pg_conn):
    conn = pg_conn
    _make_geocoded_job(conn, "k1", "Chicago Job", "Chicago, IL", "Illinois",
                       lat=41.8781, lng=-87.6298)
    _make_geocoded_job(conn, "k2", "LA Job", "Los Angeles, CA", "California",
                       lat=34.0522, lng=-118.2437)

    assert db.count_jobs(conn, zip_lat=41.8781, zip_lng=-87.6298, radius_miles=50.0) == 1


# --- WAL mode / busy_timeout (issue #132) ---

# --- geocoded_locations cache lookup (issue #133) ---

def test_get_geocoded_location_returns_none_when_absent(pg_conn):
    conn = pg_conn
    assert db.get_geocoded_location(conn, "Nowhere, XX") is None


def test_get_geocoded_location_returns_a_resolved_row(pg_conn):
    conn = pg_conn
    conn.execute(
        "INSERT INTO geocoded_locations (location, display_name, city, region, country, lat, lng, "
        "status, provider) VALUES ('Chicago, IL', 'Chicago, IL, USA', 'Chicago', 'Illinois', 'USA', "
        "41.8, -87.6, 'resolved', 'nominatim')"
    )
    conn.commit()

    result = db.get_geocoded_location(conn, "Chicago, IL")

    assert result == {
        "display_name": "Chicago, IL, USA", "city": "Chicago", "region": "Illinois",
        "country": "USA", "lat": 41.8, "lng": -87.6, "provider": "nominatim",
    }


def test_get_geocoded_location_ignores_a_pending_or_failed_row(pg_conn):
    conn = pg_conn
    conn.execute("INSERT INTO geocoded_locations (location, status) VALUES ('Remote', 'pending')")
    conn.commit()

    assert db.get_geocoded_location(conn, "Remote") is None


# ── issue #158: reactivated jobs reset emailed_at ─────────────────────────────

def test_reconcile_jobs_clears_emailed_at_when_reactivating(pg_conn):
    conn = pg_conn
    job = make_job(key="k1", source_id="s1")
    db.save_jobs(conn, [job], db.start_run(conn))
    db.mark_emailed(conn, ["k1"])
    assert db.list_jobs(conn)[0]["emailed_at"] is not None

    db.reconcile_jobs(conn, configured_source_ids={"s1"}, succeeded_source_ids={"s1"}, found_jobs=[])
    assert db.list_jobs(conn)[0]["removed_at"] is not None

    db.reconcile_jobs(conn, configured_source_ids={"s1"}, succeeded_source_ids={"s1"}, found_jobs=[job])

    row = db.list_jobs(conn)[0]
    assert row["removed_at"] is None
    assert row["emailed_at"] is None


# ── issue #157: get_unemailed_jobs ───────────────────────────────────────────

def test_get_unemailed_jobs_returns_active_unemailed_jobs(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    j1 = make_job(key="k1")
    j2 = make_job(key="k2")
    db.save_jobs(conn, [j1, j2], run_id)
    db.mark_emailed(conn, ["k2"])

    result = db.get_unemailed_jobs(conn)

    keys = {j.key for j in result}
    assert keys == {"k1"}


def test_get_unemailed_jobs_excludes_removed_jobs(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    job = make_job(key="k1", source_id="s1")
    db.save_jobs(conn, [job], run_id)
    db.reconcile_jobs(conn, configured_source_ids={"s1"}, succeeded_source_ids={"s1"}, found_jobs=[])
    assert db.list_jobs(conn)[0]["removed_at"] is not None

    result = db.get_unemailed_jobs(conn)

    assert result == []


def test_get_unemailed_jobs_returns_empty_when_all_emailed(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    job = make_job(key="k1")
    db.save_jobs(conn, [job], run_id)
    db.mark_emailed(conn, ["k1"])

    assert db.get_unemailed_jobs(conn) == []


# ── PostgreSQL-specific tests ─────────────────────────────────────────────


def test_save_jobs_duplicate_key_is_silently_ignored(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    job = make_job(key="dup-key-1")
    db.save_jobs(conn, [job], run_id)
    db.save_jobs(conn, [job], run_id)  # must not raise
    conn.commit()
    assert db.count_jobs(conn) == 1


def test_start_run_returns_integer_id(pg_conn):
    conn = pg_conn
    run_id = db.start_run(conn)
    assert isinstance(run_id, int)
    assert run_id >= 1


def test_fk_violation_raises_psycopg_error(pg_conn):
    import psycopg.errors
    conn = pg_conn
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "INSERT INTO jobs (key, title, url, source_name, first_seen_at, location) "
            "VALUES ('fk-test-1', 'Engineer', 'https://x.test/2', 'Board', "
            "'2026-01-01T00:00:00+00:00', 'no-such-location')"
        )
