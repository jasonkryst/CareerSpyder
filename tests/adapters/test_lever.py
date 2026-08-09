from app.adapters import lever
from app.config import LeverSource


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_maps_lever_postings_to_job_objects():
    payload = [
        {
            "id": "abc-123",
            "text": "Platform Engineer",
            "hostedUrl": "https://jobs.lever.co/beta/abc-123",
            "categories": {"location": "Austin, TX"},
            "createdAt": 1750000000000,
        }
    ]
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return FakeResponse(payload)

    source = LeverSource(id="s1", name="Beta (Lever)", company="Beta Inc",
                          type="lever", board_token="beta")

    jobs = lever.fetch(source, http_get=fake_get)

    assert calls == ["https://api.lever.co/v0/postings/beta?mode=json"]
    assert len(jobs) == 1
    assert jobs[0].key == "lever:abc-123"
    assert jobs[0].title == "Platform Engineer"
    assert jobs[0].url == "https://jobs.lever.co/beta/abc-123"
    assert jobs[0].location == "Austin, TX"
