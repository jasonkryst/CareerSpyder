"""Tests for app.platform_detector — URL-pattern detection, page detection, and
GitHub issue reporting.  All tests are network-free: page-fetch tests inject a
fake http_get; private-IP SSRF tests rely on IP classification (no DNS needed)."""
from unittest.mock import MagicMock

import pytest
import requests

from app.platform_detector import detect, report_unsupported

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_page(html: str):
    """Return a fake http_get that always returns `html` as response text."""
    def _get(url, **kwargs):
        m = MagicMock()
        m.text = html
        return m
    return _get


def _never_called(url, **kwargs):
    raise AssertionError(f"Unexpected HTTP call to {url}")


# ---------------------------------------------------------------------------
# URL-pattern positive tests — must NOT make any network call
# ---------------------------------------------------------------------------

class TestUrlPatternPositive:
    def test_greenhouse_boards_url(self):
        r = detect("https://boards.greenhouse.io/stripe/jobs", http_get=_never_called)
        assert r.platform_type == "greenhouse"
        assert r.confidence == "url"
        assert r.fields["board_token"] == "stripe"

    def test_greenhouse_extracts_token_without_path(self):
        r = detect("https://boards.greenhouse.io/acme", http_get=_never_called)
        assert r.fields["board_token"] == "acme"

    def test_greenhouse_api_url(self):
        r = detect("https://boards-api.greenhouse.io/v1/boards/beta/jobs?content=true", http_get=_never_called)
        assert r.platform_type == "greenhouse"
        assert r.fields["board_token"] == "beta"

    def test_lever_jobs_url(self):
        r = detect("https://jobs.lever.co/openai", http_get=_never_called)
        assert r.platform_type == "lever"
        assert r.confidence == "url"
        assert r.fields["board_token"] == "openai"

    def test_lever_api_url(self):
        r = detect("https://api.lever.co/v0/postings/anthropic?mode=json", http_get=_never_called)
        assert r.platform_type == "lever"
        assert r.fields["board_token"] == "anthropic"

    def test_linkedin_jobs_search(self):
        r = detect("https://www.linkedin.com/jobs/search/?keywords=engineer", http_get=_never_called)
        assert r.platform_type == "linkedin"
        assert r.confidence == "url"
        assert "url" in r.fields

    def test_linkedin_company_page(self):
        r = detect("https://www.linkedin.com/company/acme/jobs/", http_get=_never_called)
        assert r.platform_type == "linkedin"

    def test_indeed_with_www(self):
        r = detect("https://www.indeed.com/jobs?q=engineer", http_get=_never_called)
        assert r.platform_type == "indeed"
        assert r.fields["url"].startswith("https://")

    def test_indeed_without_www(self):
        r = detect("https://indeed.com/jobs", http_get=_never_called)
        assert r.platform_type == "indeed"

    def test_workday_wd5_subdomain(self):
        r = detect("https://acme.wd5.myworkdayjobs.com/careers", http_get=_never_called)
        assert r.platform_type == "workday"
        assert r.fields["career_site_url"].startswith("https://")

    def test_workday_wd1_subdomain(self):
        r = detect("https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly", http_get=_never_called)
        assert r.platform_type == "workday"

    def test_workday_myworkday_domain(self):
        r = detect("https://acme.myworkday.com/acme/d/inst/1234/RelatedAction", http_get=_never_called)
        assert r.platform_type == "workday"

    def test_healthcaresource_extracts_site_id(self):
        r = detect("https://pm.healthcaresource.com/CS/rcmc/", http_get=_never_called)
        assert r.platform_type == "healthcaresource"
        assert r.fields["site_id"] == "rcmc"

    def test_healthcaresource_lowercase_cs(self):
        r = detect("https://pm.healthcaresource.com/cs/acme", http_get=_never_called)
        assert r.platform_type == "healthcaresource"
        assert r.fields["site_id"] == "acme"

    def test_phenompeople_subdomain(self):
        r = detect("https://careers.acme.phenompeople.com/", http_get=_never_called)
        assert r.platform_type == "phenompeople"
        assert "phenompeople_career_site_url" in r.fields

    def test_findly_com(self):
        r = detect("https://jobs.findly.com/", http_get=_never_called)
        assert r.platform_type == "findly"
        assert "findly_career_site_url" in r.fields

    def test_findly_com_au(self):
        r = detect("https://jobs.findly.com.au/", http_get=_never_called)
        assert r.platform_type == "findly"

    def test_url_prefill_uses_full_input_url(self):
        url = "https://www.indeed.com/jobs?q=backend+engineer&l=Chicago"
        r = detect(url, http_get=_never_called)
        assert r.fields["url"] == url

    def test_workday_prefill_uses_full_input_url(self):
        url = "https://acme.wd5.myworkdayjobs.com/careers"
        r = detect(url, http_get=_never_called)
        assert r.fields["career_site_url"] == url


# ---------------------------------------------------------------------------
# Page-detection positive tests
# ---------------------------------------------------------------------------

class TestPageDetectionPositive:
    def test_greenhouse_from_page_script(self):
        html = '<script src="https://boards-api.greenhouse.io/v1/embed.js"></script>'
        r = detect("https://careers.custom.com/jobs", http_get=_fake_page(html))
        assert r.platform_type == "greenhouse"
        assert r.confidence == "page"

    def test_lever_from_page_api_reference(self):
        html = '<script>fetch("https://api.lever.co/v0/postings/acme")</script>'
        r = detect("https://careers.example.com/", http_get=_fake_page(html))
        assert r.platform_type == "lever"
        assert r.confidence == "page"

    def test_workday_from_page_domain_reference(self):
        html = '<meta name="workday" content="myworkdayjobs.com/acme/jobs">'
        r = detect("https://ourcareers.custom.com/", http_get=_fake_page(html))
        assert r.platform_type == "workday"
        assert r.confidence == "page"

    def test_talentbrew_from_page_script(self):
        html = '<script src="https://static.talentbrew.com/widget/v1.js"></script>'
        r = detect("https://careers.hospital.org/", http_get=_fake_page(html))
        assert r.platform_type == "talentbrew"
        assert r.confidence == "page"
        assert "base_url" in r.fields

    def test_healthcaresource_from_page(self):
        html = '<iframe src="https://pm.healthcaresource.com/CS/acme/"></iframe>'
        r = detect("https://jobs.hospital.org/", http_get=_fake_page(html))
        assert r.platform_type == "healthcaresource"
        assert r.confidence == "page"

    def test_phenompeople_from_page_domain(self):
        html = '<script src="https://cdn.phenompeople.com/widget.js"></script>'
        r = detect("https://custom-careers.co/", http_get=_fake_page(html))
        assert r.platform_type == "phenompeople"

    def test_findly_from_page_api_url(self):
        html = '{"api":"https://jobsapi-internal.m-cloud.io/api/job"}'
        r = detect("https://careers.au-company.com/", http_get=_fake_page(html))
        assert r.platform_type == "findly"

    def test_infor_from_page_domain(self):
        html = '<script src="https://infortalentscience.com/api.js"></script>'
        r = detect("https://careers.company.com/", http_get=_fake_page(html))
        assert r.platform_type == "infor"

    def test_page_detection_prefills_url(self):
        html = "<script>talentbrew.com loaded</script>"
        url = "https://careers.example.org/"
        r = detect(url, http_get=_fake_page(html))
        assert r.fields["base_url"] == url

    def test_page_detection_is_case_insensitive(self):
        html = "<META NAME='GENERATOR' CONTENT='MYWORKDAYJOBS.COM'>"
        r = detect("https://custom-careers.co/", http_get=_fake_page(html))
        assert r.platform_type == "workday"


# ---------------------------------------------------------------------------
# Negative tests
# ---------------------------------------------------------------------------

class TestNegative:
    def test_unknown_platform_returns_none(self):
        html = "<html><body>Custom hand-rolled careers page</body></html>"
        r = detect("https://custom-careers.example.com/", http_get=_fake_page(html))
        assert r.platform_type is None
        assert r.confidence == "none"
        assert r.message  # some human-readable message

    def test_empty_string(self):
        r = detect("")
        assert r.platform_type is None
        assert r.confidence == "none"

    def test_no_scheme(self):
        r = detect("boards.greenhouse.io/acme")
        assert r.platform_type is None

    def test_javascript_scheme_rejected(self):
        r = detect("javascript:alert(1)")
        assert r.platform_type is None

    def test_data_scheme_rejected(self):
        r = detect("data:text/html,<script>alert(1)</script>")
        assert r.platform_type is None

    def test_ftp_scheme_rejected(self):
        r = detect("ftp://files.example.com/")
        assert r.platform_type is None

    def test_private_ip_blocked_without_dns(self):
        """192.168.x.x is classified private by IP alone — no DNS, no network."""
        r = detect("http://192.168.1.1/careers")
        assert r.platform_type is None
        assert "private" in r.message.lower() or "internal" in r.message.lower()

    def test_loopback_blocked(self):
        r = detect("http://127.0.0.1/careers")
        assert r.platform_type is None

    def test_localhost_blocked(self):
        """localhost resolves to 127.0.0.1 (loopback) — SSRF guard blocks it."""
        r = detect("http://localhost/careers")
        assert r.platform_type is None

    def test_page_fetch_network_error_returns_none(self):
        def failing_get(url, **k):
            raise ConnectionError("Network error")
        r = detect("https://unknown.example.com/", http_get=failing_get)
        assert r.platform_type is None
        assert r.confidence == "none"

    def test_url_pattern_never_calls_http(self):
        r = detect("https://boards.greenhouse.io/acme/jobs", http_get=_never_called)
        assert r.platform_type == "greenhouse"  # network-free path succeeded


# ---------------------------------------------------------------------------
# report_unsupported tests
# ---------------------------------------------------------------------------

class TestReportUnsupported:
    def test_without_token_returns_new_issue_url(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        result = report_unsupported("https://unknown.example.com/careers")
        assert result["issue_url"] is None
        assert "new_issue_url" in result
        assert "github.com" in result["new_issue_url"]
        assert "Platform" in result["new_issue_url"]

    def test_new_issue_url_includes_domain_in_title(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        result = report_unsupported("https://secret-company.com/jobs/123")
        assert "secret-company.com" in result["new_issue_url"]

    def test_with_token_calls_github_api(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")

        def fake_post(url, *, json, headers, timeout, **k):
            m = MagicMock()
            m.json.return_value = {"html_url": "https://github.com/jasonkryst/CareerSpyder/issues/999"}
            m.raise_for_status = lambda: None
            return m

        result = report_unsupported("https://unknown.example.com/careers", http_post=fake_post)
        assert result["issue_url"] == "https://github.com/jasonkryst/CareerSpyder/issues/999"
        assert result["new_issue_url"] is None

    def test_with_token_sends_authorization_header(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "my-secret-token")
        captured: dict = {}

        def fake_post(url, *, json, headers, timeout, **k):
            captured["headers"] = headers
            m = MagicMock()
            m.json.return_value = {"html_url": "https://github.com/jasonkryst/CareerSpyder/issues/1"}
            m.raise_for_status = lambda: None
            return m

        report_unsupported("https://example.com/careers", http_post=fake_post)
        assert "Bearer my-secret-token" in captured["headers"]["Authorization"]

    def test_api_failure_raises_http_error(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")

        def failing_post(url, **k):
            m = MagicMock()
            m.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
            return m

        with pytest.raises(requests.HTTPError):
            report_unsupported("https://unknown.example.com/", http_post=failing_post)

    def test_issue_body_includes_full_url(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        submitted_url = "https://company.com/careers?filter=engineering"
        captured: dict = {}

        def fake_post(url, *, json, headers, timeout, **k):
            captured["json"] = json
            m = MagicMock()
            m.json.return_value = {"html_url": "https://github.com/jasonkryst/CareerSpyder/issues/2"}
            m.raise_for_status = lambda: None
            return m

        report_unsupported(submitted_url, http_post=fake_post)
        assert submitted_url in captured["json"]["body"]
