from unittest.mock import patch

from app.models import Job


def test_preview_returns_jobs_from_adapter(client):
    fake_jobs = [Job(key="k1", title="Backend Engineer", url="https://x.test/1", source_name="Acme")]

    with patch("app.web.routes_sources.ADAPTERS", {"greenhouse": lambda source: fake_jobs}):
        resp = client.post("/sources/test-preview", data={
            "type": "greenhouse", "name": "Acme", "board_token": "acme",
            "include_keywords": "", "exclude_keywords": "",
        })

    assert resp.status_code == 200
    body = resp.json()
    assert body["jobs"] == [{"title": "Backend Engineer", "url": "https://x.test/1"}]


def test_preview_returns_error_on_adapter_failure(client):
    def failing_adapter(source):
        raise RuntimeError("boom")

    with patch("app.web.routes_sources.ADAPTERS", {"greenhouse": failing_adapter}):
        resp = client.post("/sources/test-preview", data={
            "type": "greenhouse", "name": "Acme", "board_token": "acme",
            "include_keywords": "", "exclude_keywords": "",
        })

    assert resp.status_code == 200
    assert resp.json()["error"] == "boom"


def test_preview_returns_error_on_invalid_form(client):
    resp = client.post("/sources/test-preview", data={"type": "greenhouse", "name": "Acme"})
    assert resp.status_code == 200
    assert "error" in resp.json()
