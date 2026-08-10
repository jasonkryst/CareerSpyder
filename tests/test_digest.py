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
