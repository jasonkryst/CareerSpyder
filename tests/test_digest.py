from datetime import UTC, datetime

from app.digest import build_digest
from app.models import FailedSource, Job


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
    result = build_digest([], [FailedSource("Bad Co")])

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

    result = build_digest(jobs, [FailedSource("<img src=x onerror=alert(3)>")])

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


def test_secondary_source_label_appended_for_secondary_jobs():
    jobs = [Job(key="1", title="Engineer", url="https://x.test/1", company="Acme",
                source_name="Indeed", source_id="src-indeed")]

    result = build_digest(jobs, [], secondary_source_ids={"src-indeed"})

    assert "Indeed [Secondary]" in result.html_body


def test_non_secondary_source_has_no_secondary_label():
    jobs = [Job(key="1", title="Engineer", url="https://x.test/1", company="Acme",
                source_name="Greenhouse", source_id="src-gh")]

    result = build_digest(jobs, [], secondary_source_ids={"src-indeed"})

    assert "[Secondary]" not in result.html_body


def test_empty_secondary_source_ids_produces_no_secondary_labels():
    jobs = [Job(key="1", title="Engineer", url="https://x.test/1", company="Acme",
                source_name="Indeed", source_id="src-indeed")]

    result = build_digest(jobs, [], secondary_source_ids=set())

    assert "[Secondary]" not in result.html_body


# --- Failed source link tests ---

def test_failed_source_with_url_renders_as_link():
    result = build_digest([], [FailedSource("Acme Jobs", url="https://jobs.acme.test")])

    assert 'href="https://jobs.acme.test"' in result.html_body
    assert "Acme Jobs" in result.html_body
    assert 'target="_blank"' in result.html_body
    assert 'rel="noopener noreferrer"' in result.html_body


def test_failed_source_without_url_renders_as_plain_text():
    result = build_digest([], [FailedSource("Acme Jobs", url=None)])

    assert "Acme Jobs" in result.html_body
    assert "<a " not in result.html_body


def test_failed_source_url_is_html_escaped():
    result = build_digest([], [FailedSource('Acme"Evil', url='https://jobs.acme.test/?a=1&b=2')])

    assert "&amp;" in result.html_body
    assert 'Acme"Evil' not in result.html_body


def test_failed_source_javascript_url_is_neutralized():
    result = build_digest([], [FailedSource("Bad Co", url="javascript:alert(1)")])

    assert 'href="javascript:alert(1)"' not in result.html_body
    assert 'href="#"' in result.html_body


def test_failed_source_name_is_html_escaped_when_linked():
    result = build_digest([], [FailedSource("<b>Acme</b>", url="https://jobs.acme.test")])

    assert "<b>Acme</b>" not in result.html_body
    assert "&lt;b&gt;" in result.html_body


def test_multiple_failed_sources_render_all_items():
    result = build_digest([], [
        FailedSource("Source A", url="https://a.test"),
        FailedSource("Source B", url=None),
    ])

    assert "Source A" in result.html_body
    assert "Source B" in result.html_body
    assert 'href="https://a.test"' in result.html_body


def test_greenhouse_url_is_constructed_from_board_token():
    from app.config import GreenhouseSource, get_source_url

    source = GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme-corp")

    assert get_source_url(source) == "https://boards.greenhouse.io/acme-corp"


def test_lever_url_is_constructed_from_board_token():
    from app.config import LeverSource, get_source_url

    source = LeverSource(id="s1", name="Beta", type="lever", board_token="beta-inc")

    assert get_source_url(source) == "https://jobs.lever.co/beta-inc"


def test_healthcaresource_url_is_constructed_from_site_id():
    from app.config import HealthcareSource, get_source_url

    source = HealthcareSource(id="s1", name="Hospital", type="healthcaresource", site_id="hospital-hcs")

    assert get_source_url(source) == "https://pm.healthcaresource.com/CS/hospital-hcs"


def test_generic_html_returns_configured_url():
    from app.config import GenericHtmlSource, Selectors, get_source_url

    source = GenericHtmlSource(
        id="s1", name="Acme", type="generic_html",
        url="https://acme.test/careers",
        selectors=Selectors(job_card=".job", title="h2", link="a"),
    )

    assert get_source_url(source) == "https://acme.test/careers"


def test_workday_returns_career_site_url():
    from app.config import WorkdaySource, get_source_url

    source = WorkdaySource(id="s1", name="Corp", type="workday",
                           career_site_url="https://corp.wd5.myworkdayjobs.com/careers")

    assert get_source_url(source) == "https://corp.wd5.myworkdayjobs.com/careers"
