from app.adapters import linkedin
from app.config import LinkedInSource

HTML = """
<html><body>
  <div class="base-card">
    <h3 class="base-search-card__title">Backend Engineer</h3>
    <h4 class="base-search-card__subtitle">Acme Corp</h4>
    <span class="job-search-card__location">Remote</span>
    <a class="base-card__full-link" href="https://linkedin.test/jobs/view/111?refId=abc">view</a>
  </div>
</body></html>
"""


def test_fetch_parses_linkedin_cards():
    calls = []

    def fake_renderer(url):
        calls.append(url)
        return HTML

    source = LinkedInSource(id="s1", name="LinkedIn - Backend Remote", type="linkedin",
                             url="https://linkedin.test/jobs/search/?keywords=backend")

    jobs = linkedin.fetch(source, html_renderer=fake_renderer)

    assert calls == ["https://linkedin.test/jobs/search/?keywords=backend"]
    assert len(jobs) == 1
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].company == "Acme Corp"
    assert jobs[0].location == "Remote"
    assert jobs[0].url == "https://linkedin.test/jobs/view/111"
    assert jobs[0].key == "linkedin:https://linkedin.test/jobs/view/111"


def test_fetch_returns_empty_list_when_no_cards_match():
    def fake_renderer(url):
        return "<html><body>no jobs here</body></html>"

    source = LinkedInSource(id="s1", name="LinkedIn", type="linkedin", url="https://linkedin.test/jobs")

    assert linkedin.fetch(source, html_renderer=fake_renderer) == []
