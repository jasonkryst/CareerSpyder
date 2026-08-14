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
            "descriptionPlain": "Great platform role.",
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
    assert jobs[0].source_id == "s1"
    assert jobs[0].summary == "Great platform role."


def test_fetch_falls_back_to_html_description_when_plain_text_missing():
    payload = [
        {
            "id": "abc-123",
            "text": "Platform Engineer",
            "hostedUrl": "https://jobs.lever.co/beta/abc-123",
            "description": "<p>HTML <i>role</i> description.</p>",
        }
    ]

    def fake_get(url, timeout):
        return FakeResponse(payload)

    source = LeverSource(id="s1", name="Beta (Lever)", type="lever", board_token="beta")

    jobs = lever.fetch(source, http_get=fake_get)

    assert jobs[0].summary == "HTML role description."


def test_fetch_summary_is_none_when_no_description_present():
    payload = [
        {"id": "abc-123", "text": "Platform Engineer", "hostedUrl": "https://jobs.lever.co/beta/abc-123"}
    ]

    def fake_get(url, timeout):
        return FakeResponse(payload)

    source = LeverSource(id="s1", name="Beta (Lever)", type="lever", board_token="beta")

    jobs = lever.fetch(source, http_get=fake_get)

    assert jobs[0].summary is None
