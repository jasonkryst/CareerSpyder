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


# --- emailed_keys split-section tests (resend=ON) ---

def _make_job(key, title, company="Acme"):
    return Job(key=key, title=title, url=f"https://x.test/{key}", company=company, source_name="s")


def test_emailed_keys_none_produces_flat_layout():
    """Default (resend=OFF) — no subsection headers, jobs listed flat."""
    jobs = [_make_job("1", "Engineer")]

    result = build_digest(jobs, [], emailed_keys=None)

    assert "Newly identified" not in result.html_body
    assert "Already identified" not in result.html_body
    assert "Engineer" in result.html_body


def test_emailed_keys_empty_set_shows_all_jobs_as_newly_identified():
    """resend=ON, none previously emailed — all jobs land in Newly identified."""
    jobs = [_make_job("1", "Backend"), _make_job("2", "Frontend")]

    result = build_digest(jobs, [], emailed_keys=set())

    assert "Newly identified" in result.html_body
    assert "Already identified" in result.html_body
    assert "Backend" in result.html_body
    assert "Frontend" in result.html_body
    assert "No newly identified jobs" not in result.html_body
    assert "No previously identified jobs" in result.html_body


def test_emailed_keys_splits_per_company_by_prior_email_status():
    """resend=ON — job 1 was emailed before, job 2 is new; should land in opposite sections."""
    jobs = [_make_job("1", "Old Role"), _make_job("2", "New Role")]

    result = build_digest(jobs, [], emailed_keys={"1"})

    # Both section headers appear
    assert result.html_body.index("Newly identified") < result.html_body.index("Already identified")
    # New Role appears before Already identified header
    ni_end = result.html_body.index("<h4>Already identified</h4>")
    assert "New Role" in result.html_body[:ni_end]
    assert "Old Role" in result.html_body[ni_end:]


def test_emailed_keys_all_jobs_previously_emailed_shows_empty_newly_identified():
    """All jobs in the email have been seen before — Newly identified is empty."""
    jobs = [_make_job("1", "Old Role")]

    result = build_digest(jobs, [], emailed_keys={"1"})

    assert "No newly identified jobs" in result.html_body
    assert "Old Role" in result.html_body


def test_emailed_keys_split_shown_per_company_separately():
    """Split sections appear independently for each company."""
    jobs = [
        _make_job("a1", "Acme New", company="Acme"),
        _make_job("b1", "Beta Old", company="Beta"),
    ]

    result = build_digest(jobs, [], emailed_keys={"b1"})

    # Both companies have both subsection headers
    assert result.html_body.count("Newly identified") == 2
    assert result.html_body.count("Already identified") == 2


def test_emailed_keys_empty_state_text_is_html_escaped():
    """Placeholder text must not contain raw HTML."""
    jobs = [_make_job("1", "Role")]

    result = build_digest(jobs, [], emailed_keys=set())

    assert "<em>No previously identified jobs.</em>" in result.html_body


def test_emailed_keys_does_not_affect_subject_line():
    """Subject line still counts total jobs, not the new/seen split."""
    jobs = [_make_job("1", "R1"), _make_job("2", "R2")]

    result = build_digest(jobs, [], job_label="job", emailed_keys={"1"})

    assert "2 job(s)" in result.subject


# --- max_per_company truncation tests ---

def test_max_per_company_zero_shows_all_jobs():
    jobs = [_make_job(str(i), f"Role {i}") for i in range(10)]

    result = build_digest(jobs, [], max_per_company=0)

    for i in range(10):
        assert f"Role {i}" in result.html_body
    assert "more" not in result.html_body


def test_max_per_company_truncates_and_shows_overflow_count():
    jobs = [_make_job(str(i), f"Role {i}") for i in range(5)]

    result = build_digest(jobs, [], max_per_company=3)

    assert "Role 0" in result.html_body
    assert "Role 2" in result.html_body
    assert "Role 3" not in result.html_body
    assert "… and 2 more" in result.html_body


def test_max_per_company_at_exact_limit_does_not_add_overflow_note():
    jobs = [_make_job(str(i), f"Role {i}") for i in range(3)]

    result = build_digest(jobs, [], max_per_company=3)

    for i in range(3):
        assert f"Role {i}" in result.html_body
    assert "more" not in result.html_body


def test_max_per_company_overflow_note_includes_jobs_url_link():
    jobs = [_make_job(str(i), f"Role {i}") for i in range(5)]

    result = build_digest(jobs, [], max_per_company=2, jobs_url="https://cs.example.com/jobs")

    assert "… and 3 more" in result.html_body
    assert 'href="https://cs.example.com/jobs"' in result.html_body
    assert "view all" in result.html_body


def test_max_per_company_overflow_note_without_jobs_url():
    jobs = [_make_job(str(i), f"Role {i}") for i in range(5)]

    result = build_digest(jobs, [], max_per_company=2)

    assert "… and 3 more not shown." in result.html_body
    assert "<a " not in result.html_body.split("… and 3 more")[1].split("</p>")[0]


def test_max_per_company_applies_independently_per_company():
    jobs = [
        _make_job("a1", "Acme A1", company="Acme"),
        _make_job("a2", "Acme A2", company="Acme"),
        _make_job("a3", "Acme A3", company="Acme"),
        _make_job("b1", "Beta B1", company="Beta"),
        _make_job("b2", "Beta B2", company="Beta"),
    ]

    result = build_digest(jobs, [], max_per_company=2)

    assert "Acme A1" in result.html_body
    assert "Acme A2" in result.html_body
    assert "Acme A3" not in result.html_body
    assert "Beta B1" in result.html_body
    assert "Beta B2" in result.html_body
    assert result.html_body.count("… and 1 more") == 1


def test_max_per_company_subject_reflects_full_count_not_truncated():
    jobs = [_make_job(str(i), f"Role {i}") for i in range(10)]

    result = build_digest(jobs, [], max_per_company=3)

    assert "10 new job" in result.subject
