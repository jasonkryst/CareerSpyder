from app import checker, db
from app.models import Job


def make_job(key="k1", url="https://example.com/jobs/1", source_id="s1"):
    return Job(key=key, title="Engineer", url=url, company="Acme",
               location="Remote", source_name="Acme Board", source_id=source_id)


class FakeHead:
    def __init__(self, status_code: int):
        self.status_code = status_code


def _head_returning(status_code: int):
    def _head(url, *, timeout, allow_redirects):
        return FakeHead(status_code)
    return _head


def _head_raising(exc):
    def _head(url, *, timeout, allow_redirects):
        raise exc
    return _head


# ── positive cases ──────────────────────────────────────────────────────────

def test_check_job_urls_marks_removed_on_404(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job()], db.start_run(conn))

    count = checker.check_job_urls(conn, http_head=_head_returning(404))

    assert count == 1
    assert db.list_jobs(conn)[0]["removed_at"] is not None


def test_check_job_urls_marks_removed_on_410(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job()], db.start_run(conn))

    count = checker.check_job_urls(conn, http_head=_head_returning(410))

    assert count == 1
    assert db.list_jobs(conn)[0]["removed_at"] is not None


def test_check_job_urls_returns_count_of_removed(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job("k1"), make_job("k2"), make_job("k3")], db.start_run(conn))

    count = checker.check_job_urls(conn, http_head=_head_returning(404))

    assert count == 3


# ── negative cases ───────────────────────────────────────────────────────────

def test_check_job_urls_leaves_active_job_untouched_on_200(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job()], db.start_run(conn))

    count = checker.check_job_urls(conn, http_head=_head_returning(200))

    assert count == 0
    assert db.list_jobs(conn)[0]["removed_at"] is None


def test_check_job_urls_leaves_active_job_untouched_on_301(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job()], db.start_run(conn))

    count = checker.check_job_urls(conn, http_head=_head_returning(301))

    assert count == 0
    assert db.list_jobs(conn)[0]["removed_at"] is None


def test_check_job_urls_leaves_active_job_untouched_on_500(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job()], db.start_run(conn))

    count = checker.check_job_urls(conn, http_head=_head_returning(500))

    assert count == 0
    assert db.list_jobs(conn)[0]["removed_at"] is None


def test_check_job_urls_leaves_active_job_untouched_when_request_raises(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job()], db.start_run(conn))

    import requests
    count = checker.check_job_urls(conn, http_head=_head_raising(requests.ConnectionError("timeout")))

    assert count == 0
    assert db.list_jobs(conn)[0]["removed_at"] is None


def test_check_job_urls_skips_already_removed_jobs(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_jobs(conn, [make_job()], db.start_run(conn))
    db.reconcile_jobs(conn, configured_source_ids=set(), succeeded_source_ids={"s1"}, found_jobs=[])
    assert db.list_jobs(conn)[0]["removed_at"] is not None

    calls = []
    def _head(url, *, timeout, allow_redirects):
        calls.append(url)
        return FakeHead(200)

    checker.check_job_urls(conn, http_head=_head)

    assert calls == []  # already-removed job is not queried


def test_check_job_urls_with_no_active_jobs_returns_zero(tmp_db_path):
    conn = db.init_db(tmp_db_path)

    count = checker.check_job_urls(conn, http_head=_head_returning(404))

    assert count == 0


def test_check_job_urls_only_removes_jobs_that_return_404_or_410(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    jobs = [
        make_job("gone-404", url="https://example.com/1"),
        make_job("gone-410", url="https://example.com/2"),
        make_job("still-live", url="https://example.com/3"),
    ]
    db.save_jobs(conn, jobs, db.start_run(conn))

    status_by_url = {
        "https://example.com/1": 404,
        "https://example.com/2": 410,
        "https://example.com/3": 200,
    }

    def _head(url, *, timeout, allow_redirects):
        return FakeHead(status_by_url[url])

    count = checker.check_job_urls(conn, http_head=_head)

    assert count == 2
    rows = {r["key"]: r for r in db.list_jobs(conn, removed=None)}
    assert rows["gone-404"]["removed_at"] is not None
    assert rows["gone-410"]["removed_at"] is not None
    assert rows["still-live"]["removed_at"] is None
