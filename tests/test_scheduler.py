from unittest.mock import patch

from app import db, scheduler
from app.digest import Digest
from app.models import Job


def _configure(conn, email_days="mon,tue,wed,thu,fri,sat,sun", resend_jobs=False, email_to="to@x.test"):
    db.save_settings(conn, "smtp.example.com", 587, "user", "from@x.test")
    db.save_preferences(conn, email_days, resend_jobs, email_to)


def test_run_and_notify_sends_email_when_digest_present(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn)
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"], "run_id": 1})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary) as mock_run_once, \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")) as mock_digest, \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_run_once.assert_called_once()
    mock_digest.assert_called_once_with([], ["Bad Co"], "new job")
    mock_send.assert_called_once_with(
        "smtp.example.com", 587, "user", "secret", "from@x.test", ["to@x.test"], "Subj", "<p>Body</p>",
    )


def test_run_and_notify_skips_email_when_digest_is_none(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn)
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": []})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=None), \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_send.assert_not_called()


def test_run_and_notify_swallows_email_send_failures(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn)
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"], "run_id": 1})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email", side_effect=RuntimeError("smtp exploded")):
        scheduler.run_and_notify(conn, sources_path)  # must not raise


def test_run_and_notify_does_not_crash_when_smtp_password_unset(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    conn = db.init_db(tmp_db_path)
    _configure(conn)
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"], "run_id": 1})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_send.assert_called_once()
    assert mock_send.call_args[0][3] == ""


def test_run_and_notify_scans_and_skips_only_email_when_no_settings_configured(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    # No db.save_settings/save_preferences call, so db.get_settings(conn) returns None.
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"], "run_id": 1})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary) as mock_run_once, \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)  # must not raise

    mock_run_once.assert_called_once()  # scan still happens, matching today's behavior
    mock_send.assert_not_called()


def test_run_and_notify_skips_entire_run_when_no_days_selected(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn, email_days="")
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    with patch("app.scheduler.orchestrator.run_once") as mock_run_once, \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_run_once.assert_not_called()
    mock_send.assert_not_called()


def test_run_and_notify_skips_email_when_no_recipients_configured(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn, email_to="")
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": ["job-a"], "failed_sources": [], "run_id": 1})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_send.assert_not_called()


def test_run_and_notify_splits_comma_separated_recipients(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn, email_to="a@x.test, b@x.test")
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": ["job-a"], "failed_sources": [], "run_id": 1})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    assert mock_send.call_args[0][5] == ["a@x.test", "b@x.test"]


def test_run_and_notify_uses_found_jobs_and_generic_label_when_resend_enabled(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn, resend_jobs=True)
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {
        "new_jobs": [], "found_jobs": ["job-a"], "failed_sources": [], "run_id": 1,
    })()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")) as mock_digest, \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_digest.assert_called_once_with(["job-a"], [], "job")
    mock_send.assert_called_once()


def test_run_and_notify_marks_new_jobs_emailed_after_a_successful_send(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn)
    run_id = db.start_run(conn)
    job = Job(key="k1", title="Engineer", url="https://x.test/1", source_name="s")
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [job], "failed_sources": [], "run_id": run_id})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email"):
        scheduler.run_and_notify(conn, sources_path)

    assert db.list_jobs(conn)[0]["emailed_at"] is not None


def test_run_and_notify_does_not_mark_emailed_when_send_fails(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn)
    run_id = db.start_run(conn)
    job = Job(key="k1", title="Engineer", url="https://x.test/1", source_name="s")
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [job], "failed_sources": [], "run_id": run_id})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email", side_effect=RuntimeError("smtp exploded")):
        scheduler.run_and_notify(conn, sources_path)  # must not raise

    assert db.list_jobs(conn)[0]["emailed_at"] is None


def test_run_and_notify_marks_resent_jobs_emailed_when_resend_enabled(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn, resend_jobs=True)
    run_id = db.start_run(conn)
    old_job = Job(key="k1", title="Engineer", url="https://x.test/1", source_name="s")
    db.save_jobs(conn, [old_job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    # No new jobs this run, but resend is on -- the digest sends found_jobs, so
    # mark_emailed must key off that, not summary.new_jobs (which is empty).
    fake_summary = type("S", (), {
        "new_jobs": [], "found_jobs": [old_job], "failed_sources": [], "run_id": run_id,
    })()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email"):
        scheduler.run_and_notify(conn, sources_path)

    assert db.list_jobs(conn)[0]["emailed_at"] is not None


def test_create_scheduler_registers_daily_cron_job(tmp_db_path, tmp_path):
    conn = db.init_db(tmp_db_path)
    sources_path = str(tmp_path / "sources.json")

    sched = scheduler.create_scheduler(conn, sources_path, run_hour=8, tz="UTC")
    try:
        jobs = sched.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == "daily_run"
        assert jobs[0].args == (conn, sources_path, "UTC")
    finally:
        sched.shutdown()
