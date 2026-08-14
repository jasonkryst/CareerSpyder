from app import db
from app.models import Job


def make_job(key="k1", title="Engineer"):
    return Job(key=key, title=title, url="https://x.test/1", company="Acme",
               location="Remote", posted_date=None, source_name="Acme Board")


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
    db.save_settings(conn, "a.example.com", 587, "u1", "f@x.test", "t@x.test")
    db.save_settings(conn, "b.example.com", 465, "u2", "f2@x.test", "t2@x.test")

    settings = db.get_settings(conn)
    assert settings == {
        "smtp_host": "b.example.com", "smtp_port": 465, "smtp_user": "u2",
        "email_from": "f2@x.test", "email_to": "t2@x.test",
    }
