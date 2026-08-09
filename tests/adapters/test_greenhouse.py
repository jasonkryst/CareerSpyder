from app.adapters import greenhouse
from app.config import GreenhouseSource


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_maps_greenhouse_jobs_to_job_objects():
    payload = {
        "jobs": [
            {
                "id": 123,
                "title": "Backend Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                "location": {"name": "Remote"},
                "updated_at": "2026-08-01T00:00:00Z",
            }
        ]
    }
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return FakeResponse(payload)

    source = GreenhouseSource(id="s1", name="Acme (Greenhouse)", company="Acme",
                               type="greenhouse", board_token="acme")

    jobs = greenhouse.fetch(source, http_get=fake_get)

    assert calls == ["https://boards-api.greenhouse.io/v1/boards/acme/jobs"]
    assert len(jobs) == 1
    assert jobs[0].key == "greenhouse:123"
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].url == "https://boards.greenhouse.io/acme/jobs/123"
    assert jobs[0].company == "Acme"
    assert jobs[0].location == "Remote"
    assert jobs[0].source_name == "Acme (Greenhouse)"
