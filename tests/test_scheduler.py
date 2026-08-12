from unittest.mock import patch

from app import db, scheduler
from app.digest import Digest


def test_run_and_notify_sends_email_when_digest_present(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    db.save_settings(conn, "smtp.example.com", 587, "user", "from@x.test", "to@x.test")
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"]})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary) as mock_run_once, \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")) as mock_digest, \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_run_once.assert_called_once()
    mock_digest.assert_called_once_with([], ["Bad Co"])
    mock_send.assert_called_once_with(
        "smtp.example.com", 587, "user", "secret", "from@x.test", "to@x.test", "Subj", "<p>Body</p>",
    )


def test_run_and_notify_skips_email_when_digest_is_none(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    db.save_settings(conn, "smtp.example.com", 587, "user", "from@x.test", "to@x.test")
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
    db.save_settings(conn, "smtp.example.com", 587, "user", "from@x.test", "to@x.test")
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
    db.save_settings(conn, "smtp.example.com", 587, "user", "from@x.test", "to@x.test")
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"]})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_send.assert_called_once()
    assert mock_send.call_args[0][3] == ""


def test_run_and_notify_skips_email_when_no_settings_configured(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    # No db.save_settings call, so db.get_settings(conn) returns None.
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"], "run_id": 1})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)  # must not raise

    mock_send.assert_not_called()


def test_create_scheduler_registers_daily_cron_job(tmp_db_path, tmp_path):
    conn = db.init_db(tmp_db_path)
    sources_path = str(tmp_path / "sources.json")

    sched = scheduler.create_scheduler(conn, sources_path, run_hour=8, tz="UTC")
    try:
        jobs = sched.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == "daily_run"
    finally:
        sched.shutdown()
