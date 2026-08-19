from datetime import UTC, datetime

from app.digest import build_digest
from app.models import Job


def test_returns_none_when_nothing_new_and_no_failures():
    assert build_digest([], []) is None


def test_groups_new_jobs_by_company():
    jobs = [
        Job(key="1", title="Backend Engineer", url="https://x.test/1", company="Acme", source_name="s"),
        Job(key="2", title="Frontend Engineer", url="https://x.test/2", company="Beta", source_name="s"),
    ]

    result = build_digest(jobs, [])

    assert "2 new job" in result.subject
    assert "Acme" in result.html_body
    assert "Beta" in result.html_body
    assert "Backend Engineer" in result.html_body
    assert "https://x.test/1" in result.html_body


def test_includes_failed_sources_section():
    result = build_digest([], ["Bad Co"])

    assert result is not None
    assert "Bad Co" in result.html_body
    assert "failed" in result.subject.lower()


def test_scraped_fields_are_html_escaped():
    jobs = [
        Job(
            key="1",
            title='<script>alert(1)</script>',
            url="https://x.test/1",
            company='Acme" onmouseover="alert(2)',
            location="<b>Remote</b>",
            source_name="s",
        ),
    ]

    result = build_digest(jobs, ["<img src=x onerror=alert(3)>"])

    assert "<script>" not in result.html_body
    assert "&lt;script&gt;" in result.html_body
    assert 'onmouseover="alert' not in result.html_body
    assert "<b>Remote</b>" not in result.html_body
    assert "<img src=x onerror=alert(3)>" not in result.html_body


def test_job_label_can_be_overridden_for_resend_digests():
    jobs = [Job(key="1", title="Engineer", url="https://x.test/1", company="Acme", source_name="s")]

    result = build_digest(jobs, [], job_label="job")

    assert "1 job(s)" in result.subject
    assert "new job" not in result.subject


def test_javascript_url_is_neutralized():
    jobs = [
        Job(key="1", title="Engineer", url="javascript:alert(1)", company="Acme", source_name="s"),
    ]

    result = build_digest(jobs, [])

    assert 'href="javascript:alert(1)"' not in result.html_body
    assert 'href="#"' in result.html_body


def test_shows_source_name():
    jobs = [Job(key="1", title="Engineer", url="https://x.test/1", company="Acme", source_name="Acme Board")]

    result = build_digest(jobs, [])

    assert "Acme Board" in result.html_body


def test_shows_status_when_one_exists_for_the_job():
    jobs = [Job(key="1", title="Engineer", url="https://x.test/1", company="Acme", source_name="s")]

    result = build_digest(jobs, [], statuses={"1": "not_interested"})

    assert "Not Interested" in result.html_body


def test_omits_status_when_none_exists_for_the_job():
    jobs = [Job(key="1", title="Engineer", url="https://x.test/1", company="Acme", source_name="s")]

    result = build_digest(jobs, [], statuses={"2": "applied"})

    assert "Applied" not in result.html_body


def test_includes_searched_at_timestamp_when_given():
    jobs = [Job(key="1", title="Engineer", url="https://x.test/1", company="Acme", source_name="s")]

    result = build_digest(jobs, [], searched_at=datetime(2026, 8, 19, 14, 30, tzinfo=UTC))

    assert "Aug 19, 2026" in result.html_body


def test_includes_jobs_link_when_given():
    jobs = [Job(key="1", title="Engineer", url="https://x.test/1", company="Acme", source_name="s")]

    result = build_digest(jobs, [], jobs_url="https://careerspyder.example.com/jobs")

    assert 'href="https://careerspyder.example.com/jobs"' in result.html_body
    assert "View all jobs" in result.html_body


def test_omits_jobs_link_when_not_given():
    jobs = [Job(key="1", title="Engineer", url="https://x.test/1", company="Acme", source_name="s")]

    result = build_digest(jobs, [])

    assert "View all jobs" not in result.html_body
