"""Route-level tests for /sources/detect-platform and /sources/report-unsupported."""
from unittest.mock import patch

import pytest

from app.platform_detector import DetectionResult


@pytest.fixture
def detect_greenhouse():
    return DetectionResult("greenhouse", "url", {"board_token": "acme"}, "Detected greenhouse")


@pytest.fixture
def detect_none():
    return DetectionResult(None, "none", {}, "Platform not recognized")


# ---------------------------------------------------------------------------
# POST /sources/detect-platform
# ---------------------------------------------------------------------------

class TestDetectPlatform:
    def test_returns_detection_result_for_known_url(self, client, detect_greenhouse):
        with patch("app.web.routes_sources.detect", return_value=detect_greenhouse):
            resp = client.post(
                "/sources/detect-platform",
                json={"url": "https://boards.greenhouse.io/acme/jobs"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["platform_type"] == "greenhouse"
        assert body["confidence"] == "url"
        assert body["fields"]["board_token"] == "acme"

    def test_returns_none_for_unknown_platform(self, client, detect_none):
        with patch("app.web.routes_sources.detect", return_value=detect_none):
            resp = client.post(
                "/sources/detect-platform",
                json={"url": "https://custom-careers.example.com/"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["platform_type"] is None
        assert body["confidence"] == "none"

    def test_returns_400_when_url_missing(self, client):
        resp = client.post("/sources/detect-platform", json={})
        assert resp.status_code == 400

    def test_returns_400_when_url_empty(self, client):
        resp = client.post("/sources/detect-platform", json={"url": ""})
        assert resp.status_code == 400

    def test_returns_400_on_non_json_body(self, client):
        resp = client.post(
            "/sources/detect-platform",
            data="not json",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code in (400, 422)

    def test_includes_message_in_response(self, client, detect_greenhouse):
        with patch("app.web.routes_sources.detect", return_value=detect_greenhouse):
            resp = client.post(
                "/sources/detect-platform",
                json={"url": "https://boards.greenhouse.io/acme"},
            )
        assert "message" in resp.json()

    def test_requires_authentication(self, unauthed_client):
        resp = unauthed_client.post(
            "/sources/detect-platform",
            json={"url": "https://boards.greenhouse.io/acme"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303, 401)


# ---------------------------------------------------------------------------
# POST /sources/report-unsupported
# ---------------------------------------------------------------------------

class TestReportUnsupported:
    def test_returns_new_issue_url_without_token(self, client, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        resp = client.post(
            "/sources/report-unsupported",
            json={"url": "https://unknown.example.com/careers"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "new_issue_url" in body
        assert "github.com" in (body.get("new_issue_url") or "")

    def test_returns_issue_url_with_token(self, client, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        fake_result = {
            "issue_url": "https://github.com/jasonkryst/CareerSpyder/issues/999",
            "new_issue_url": None,
        }
        with patch("app.web.routes_sources.report_unsupported", return_value=fake_result):
            resp = client.post(
                "/sources/report-unsupported",
                json={"url": "https://unknown.example.com/careers"},
            )
        assert resp.status_code == 200
        assert resp.json()["issue_url"].endswith("/issues/999")

    def test_returns_400_when_url_missing(self, client):
        resp = client.post("/sources/report-unsupported", json={})
        assert resp.status_code == 400

    def test_returns_400_when_url_empty(self, client):
        resp = client.post("/sources/report-unsupported", json={"url": "  "})
        assert resp.status_code == 400

    def test_github_api_failure_returns_502(self, client, monkeypatch):
        import requests as _requests
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")

        def raise_http_error(url, **k):
            raise _requests.HTTPError("403 Forbidden")

        with patch("app.web.routes_sources.report_unsupported", side_effect=raise_http_error):
            resp = client.post(
                "/sources/report-unsupported",
                json={"url": "https://unknown.example.com/"},
            )
        assert resp.status_code == 502

    def test_requires_authentication(self, unauthed_client):
        resp = unauthed_client.post(
            "/sources/report-unsupported",
            json={"url": "https://unknown.example.com/"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303, 401)
