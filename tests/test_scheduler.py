from unittest.mock import patch

from app import db, orchestrator, scheduler
from app.digest import Digest
from app.models import Job
from app.web.auth import hash_password

# Reusable greenhouse source dict for E2E tests
_GH_SOURCE_DICT = {"id": "s1", "name": "Acme", "type": "greenhouse", "board_token": "acme"}


def _seed_user(conn, username="testuser"):
    """Create a test admin user and return their user_id string."""
    return db.create_user(conn, username, f"{username}@test.local", hash_password("pw"), role="admin")["id"]


def _configure(conn, user_id, email_days="mon,tue,wed,thu,fri,sat,sun", resend_jobs=False, email_to="to@x.test"):
    db.save_settings(conn, user_id, "smtp.example.com", 587, "user", "from@x.test")
    db.save_preferences(conn, user_id, email_days, resend_jobs, email_to)


def _seed_gh_source(conn, user_id):
    """Seed a single Greenhouse source for the given user."""
    from app.config import GreenhouseSource
    source = GreenhouseSource(id="s1", name="Acme", board_token="acme")
    db.add_source(conn, user_id, source)
    return source


def test_run_and_notify_sends_email_when_digest_present(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id)

        fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"], "run_id": 1})()

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary) as mock_run_once, \
             patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")) as mock_digest, \
             patch("app.scheduler.emailer.send_email") as mock_send:
            scheduler.run_and_notify(pool)

        mock_run_once.assert_called_once()
        mock_digest.assert_called_once()
        call_args, call_kwargs = mock_digest.call_args
        assert call_args == ([], ["Bad Co"], "new job")
        assert call_kwargs["statuses"] == {}
        assert call_kwargs["jobs_url"] is None
        assert "searched_at" in call_kwargs
        mock_send.assert_called_once_with(
            "smtp.example.com", 587, "user", "secret", "from@x.test", ["to@x.test"], "Subj", "<p>Body</p>",
        )
    finally:
        pool.close()


def test_run_and_notify_skips_email_when_digest_is_none(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id)

        fake_summary = type("S", (), {"new_jobs": [], "failed_sources": []})()

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
             patch("app.scheduler.digest.build_digest", return_value=None), \
             patch("app.scheduler.emailer.send_email") as mock_send:
            scheduler.run_and_notify(pool)

        mock_send.assert_not_called()
    finally:
        pool.close()


def test_run_and_notify_swallows_email_send_failures(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id)

        fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"], "run_id": 1})()

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
             patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
             patch("app.scheduler.emailer.send_email", side_effect=RuntimeError("smtp exploded")):
            scheduler.run_and_notify(pool)  # must not raise
    finally:
        pool.close()


def test_run_and_notify_does_not_crash_when_smtp_password_unset(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id)

        fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"], "run_id": 1})()

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
             patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
             patch("app.scheduler.emailer.send_email") as mock_send:
            scheduler.run_and_notify(pool)

        mock_send.assert_called_once()
        assert mock_send.call_args[0][3] == ""
    finally:
        pool.close()


def test_run_and_notify_scans_and_skips_only_email_when_no_settings_configured(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
        # No settings seeded → db.get_settings returns None

        fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"], "run_id": 1})()

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary) as mock_run_once, \
             patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
             patch("app.scheduler.emailer.send_email") as mock_send:
            scheduler.run_and_notify(pool)  # must not raise

        mock_run_once.assert_called_once()  # scan still happens, matching today's behavior
        mock_send.assert_not_called()
    finally:
        pool.close()


def test_run_and_notify_skips_entire_run_when_no_days_selected(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id, email_days="")

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once") as mock_run_once, \
             patch("app.scheduler.emailer.send_email") as mock_send:
            scheduler.run_and_notify(pool)

        mock_run_once.assert_not_called()
        mock_send.assert_not_called()
    finally:
        pool.close()


def test_run_and_notify_force_bypasses_day_gate(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id, email_days="")

        fake_summary = type("S", (), {"new_jobs": [], "failed_sources": []})()

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary) as mock_run_once, \
             patch("app.scheduler.digest.build_digest", return_value=None):
            scheduler.run_and_notify(pool, force=True)

        mock_run_once.assert_called_once()
    finally:
        pool.close()


def test_run_and_notify_skips_email_when_no_recipients_configured(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id, email_to="")

        fake_job = Job(key="job-a", title="A", url="https://x.test/a", source_name="s")
        fake_summary = type("S", (), {"new_jobs": [fake_job], "failed_sources": [], "run_id": 1})()

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
             patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
             patch("app.scheduler.emailer.send_email") as mock_send:
            scheduler.run_and_notify(pool)

        mock_send.assert_not_called()
    finally:
        pool.close()


def test_run_and_notify_splits_comma_separated_recipients(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id, email_to="a@x.test, b@x.test")

        fake_job = Job(key="job-a", title="A", url="https://x.test/a", source_name="s")
        fake_summary = type("S", (), {"new_jobs": [fake_job], "failed_sources": [], "run_id": 1})()

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
             patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
             patch("app.scheduler.emailer.send_email") as mock_send:
            scheduler.run_and_notify(pool)

        assert mock_send.call_args[0][5] == ["a@x.test", "b@x.test"]
    finally:
        pool.close()


def test_run_and_notify_uses_found_jobs_and_generic_label_when_resend_enabled(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id, resend_jobs=True)

        fake_job = Job(key="job-a", title="A", url="https://x.test/a", source_name="s")
        fake_summary = type("S", (), {
            "new_jobs": [], "found_jobs": [fake_job], "failed_sources": [], "run_id": 1,
        })()

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
             patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")) as mock_digest, \
             patch("app.scheduler.emailer.send_email") as mock_send:
            scheduler.run_and_notify(pool)

        call_args, call_kwargs = mock_digest.call_args
        assert call_args == ([fake_job], [], "job")
        assert call_kwargs["statuses"] == {}
        mock_send.assert_called_once()
    finally:
        pool.close()


def test_run_and_notify_passes_emailed_keys_to_digest_when_resend_enabled(pg_dsn, monkeypatch):
    """Regression: when resend=ON, build_digest must receive emailed_keys so it
    can split each company section into Newly/Already identified."""
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id, resend_jobs=True)

            # Save and mark job-a as previously emailed; job-b is new (never emailed).
            run_id = db.start_run(conn)
            old_job = Job(key="job-a", title="Old", url="https://x.test/a", source_name="s")
            new_job = Job(key="job-b", title="New", url="https://x.test/b", source_name="s")
            db.save_jobs(conn, [old_job, new_job], run_id)
            db.mark_emailed(conn, ["job-a"])

        fake_summary = type("S", (), {
            "new_jobs": [new_job],
            "found_jobs": [old_job, new_job],
            "failed_sources": [],
            "run_id": run_id,
        })()

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
             patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")) as mock_digest, \
             patch("app.scheduler.emailer.send_email"):
            scheduler.run_and_notify(pool)

        _, call_kwargs = mock_digest.call_args
        assert "emailed_keys" in call_kwargs
        assert call_kwargs["emailed_keys"] == {"job-a"}
    finally:
        pool.close()


def test_run_and_notify_passes_emailed_keys_none_when_resend_disabled(pg_dsn, monkeypatch):
    """When resend=OFF, emailed_keys must be None so the flat layout is used."""
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id, resend_jobs=False)

        job = Job(key="job-a", title="A", url="https://x.test/a", source_name="s")
        fake_summary = type("S", (), {
            "new_jobs": [job], "found_jobs": [job], "failed_sources": [], "run_id": 1,
        })()

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
             patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")) as mock_digest, \
             patch("app.scheduler.emailer.send_email"):
            scheduler.run_and_notify(pool)

        _, call_kwargs = mock_digest.call_args
        assert call_kwargs.get("emailed_keys") is None
    finally:
        pool.close()


def test_run_and_notify_marks_new_jobs_emailed_after_a_successful_send(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id)
            run_id = db.start_run(conn)
            job = Job(key="k1", title="Engineer", url="https://x.test/1", source_name="s")
            db.save_jobs(conn, [job], run_id)
            db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])

        fake_summary = type("S", (), {"new_jobs": [job], "failed_sources": [], "run_id": run_id})()

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
             patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
             patch("app.scheduler.emailer.send_email"):
            scheduler.run_and_notify(pool)

        with pool.connection() as conn:
            assert db.list_jobs(conn)[0]["emailed_at"] is not None
    finally:
        pool.close()


def test_run_and_notify_does_not_mark_emailed_when_send_fails(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id)
            run_id = db.start_run(conn)
            job = Job(key="k1", title="Engineer", url="https://x.test/1", source_name="s")
            db.save_jobs(conn, [job], run_id)
            db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])

        fake_summary = type("S", (), {"new_jobs": [job], "failed_sources": [], "run_id": run_id})()

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
             patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
             patch("app.scheduler.emailer.send_email", side_effect=RuntimeError("smtp exploded")):
            scheduler.run_and_notify(pool)  # must not raise

        with pool.connection() as conn:
            assert db.list_jobs(conn)[0]["emailed_at"] is None
    finally:
        pool.close()


def test_run_and_notify_marks_resent_jobs_emailed_when_resend_enabled(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id, resend_jobs=True)
            run_id = db.start_run(conn)
            old_job = Job(key="k1", title="Engineer", url="https://x.test/1", source_name="s")
            db.save_jobs(conn, [old_job], run_id)
            db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])

        fake_summary = type("S", (), {
            "new_jobs": [], "found_jobs": [old_job], "failed_sources": [], "run_id": run_id,
        })()

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
             patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
             patch("app.scheduler.emailer.send_email"):
            scheduler.run_and_notify(pool)

        with pool.connection() as conn:
            assert db.list_jobs(conn)[0]["emailed_at"] is not None
    finally:
        pool.close()


def test_run_and_notify_end_to_end_stays_silent_on_clean_run(pg_dsn, monkeypatch):
    # Real orchestrator + real digest builder, only the network boundary
    # (adapter fetch, email send) is faked. Covers the "no new jobs, no
    # failures -> no email" path with real objects, not the fully-mocked
    # wiring the other tests in this file use.
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setitem(orchestrator.ADAPTERS, "greenhouse", lambda source: [])
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id)
            _seed_gh_source(conn, user_id)

        with patch("app.scheduler.emailer.send_email") as mock_send:
            scheduler.run_and_notify(pool)

        mock_send.assert_not_called()
    finally:
        pool.close()


def test_run_and_notify_end_to_end_sends_real_digest_for_a_new_job(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    job = Job(key="gh:1", title="<Engineer>", url="https://acme.test/1", company="Acme", source_name="Acme")
    monkeypatch.setitem(orchestrator.ADAPTERS, "greenhouse", lambda source: [job])
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id)
            _seed_gh_source(conn, user_id)

        with patch("app.scheduler.emailer.send_email") as mock_send:
            scheduler.run_and_notify(pool)

        mock_send.assert_called_once()
        html_body = mock_send.call_args[0][7]
        assert "&lt;Engineer&gt;" in html_body  # real digest builder escapes it
        assert "<Engineer>" not in html_body
        with pool.connection() as conn:
            assert db.list_jobs(conn)[0]["emailed_at"] is not None
    finally:
        pool.close()


def test_run_and_notify_includes_source_and_existing_status_in_real_digest(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id, resend_jobs=True)
            _seed_gh_source(conn, user_id)
            run_id = db.start_run(conn)
            job = Job(key="k1", title="Engineer", url="https://x.test/1", company="Acme", source_name="Acme Board")
            db.save_jobs(conn, [job], run_id)
            db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])
            db.set_job_status(conn, "k1", "not_interested")
        monkeypatch.setitem(orchestrator.ADAPTERS, "greenhouse", lambda source: [job])

        with patch("app.scheduler.emailer.send_email") as mock_send:
            scheduler.run_and_notify(pool)

        mock_send.assert_called_once()
        html_body = mock_send.call_args[0][7]
        assert "Acme Board" in html_body
        assert "Not Interested" in html_body
    finally:
        pool.close()


def test_run_and_notify_includes_jobs_link_when_public_base_url_is_set(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://careerspyder.example.com")
    job = Job(key="gh:1", title="Engineer", url="https://acme.test/1", company="Acme", source_name="Acme")
    monkeypatch.setitem(orchestrator.ADAPTERS, "greenhouse", lambda source: [job])
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id)
            _seed_gh_source(conn, user_id)

        with patch("app.scheduler.emailer.send_email") as mock_send:
            scheduler.run_and_notify(pool)

        html_body = mock_send.call_args[0][7]
        assert 'href="https://careerspyder.example.com/jobs"' in html_body
    finally:
        pool.close()


def test_run_and_notify_omits_jobs_link_when_public_base_url_is_unset(pg_dsn, monkeypatch):
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    job = Job(key="gh:1", title="Engineer", url="https://acme.test/1", company="Acme", source_name="Acme")
    monkeypatch.setitem(orchestrator.ADAPTERS, "greenhouse", lambda source: [job])
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id)
            _seed_gh_source(conn, user_id)

        with patch("app.scheduler.emailer.send_email") as mock_send:
            scheduler.run_and_notify(pool)

        html_body = mock_send.call_args[0][7]
        assert "View all jobs" not in html_body
    finally:
        pool.close()


def test_run_and_notify_rescues_jobs_dropped_by_a_prior_crash(pg_dsn, monkeypatch):
    """Jobs saved in a prior run but never emailed (crash window) must be included
    in the next digest even though they are not new."""
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id)
            run_id = db.start_run(conn)
            stranded = Job(key="stranded-1", title="Old Job", url="https://x.test/s", source_name="s")
            db.save_jobs(conn, [stranded], run_id)
            db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])
            # Simulate crash: save_jobs committed, mark_emailed never ran.  emailed_at IS NULL.

        # This run finds no new jobs.
        fake_summary = type("S", (), {"new_jobs": [], "found_jobs": [], "failed_sources": [], "run_id": run_id})()

        captured: list = []
        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
             patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")) as mock_digest, \
             patch("app.scheduler.emailer.send_email"):
            scheduler.run_and_notify(pool)
            call_args, _ = mock_digest.call_args
            captured.extend(call_args[0])

        assert any(j.key == "stranded-1" for j in captured)
        # And it should now be marked emailed.
        with pool.connection() as conn:
            assert db.list_jobs(conn)[0]["emailed_at"] is not None
    finally:
        pool.close()


def test_run_and_notify_does_not_double_add_jobs_already_in_jobs_to_send(pg_dsn, monkeypatch):
    """New jobs from the current run should not appear twice even though
    get_unemailed_jobs also returns them."""
    from psycopg_pool import ConnectionPool
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pool.connection() as conn:
            user_id = _seed_user(conn)
            _configure(conn, user_id)
            run_id = db.start_run(conn)
            new_job = Job(key="new-1", title="New Job", url="https://x.test/n", source_name="s")
            db.save_jobs(conn, [new_job], run_id)

        fake_summary = type("S", (), {"new_jobs": [new_job], "found_jobs": [new_job], "failed_sources": [], "run_id": run_id})()

        with patch("app.scheduler.db.list_all_sources_by_user", return_value={user_id: []}), \
             patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
             patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")) as mock_digest, \
             patch("app.scheduler.emailer.send_email"):
            scheduler.run_and_notify(pool)
            call_args, _ = mock_digest.call_args

        sent_keys = [j.key for j in call_args[0]]
        assert sent_keys.count("new-1") == 1
    finally:
        pool.close()


def test_create_scheduler_registers_daily_cron_job(pg_dsn):
    from psycopg_pool import ConnectionPool
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        sched = scheduler.create_scheduler(pool, run_cron="0 8 * * *", tz="UTC")
        try:
            jobs = sched.get_jobs()
            assert len(jobs) == 1
            assert jobs[0].id == "daily_run"
            assert jobs[0].args == (pool, "UTC")
        finally:
            sched.shutdown()
    finally:
        pool.close()


def test_create_scheduler_raises_on_invalid_cron(pg_dsn):
    import pytest
    from psycopg_pool import ConnectionPool
    pool = ConnectionPool(pg_dsn, min_size=1, max_size=2, open=True)
    try:
        with pytest.raises(ValueError):
            scheduler.create_scheduler(pool, run_cron="not a cron", tz="UTC")
    finally:
        pool.close()
