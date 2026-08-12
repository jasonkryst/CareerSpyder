from app.adapters import indeed
from app.config import IndeedSource

HTML = """
<html><body>
  <div class="job_seen_beacon">
    <h2 class="jobTitle"><a href="/rc/clk?jk=xyz"><span>Backend Engineer</span></a></h2>
    <span class="companyName">Acme Corp</span>
    <div class="companyLocation">Remote</div>
  </div>
</body></html>
"""


def test_fetch_parses_indeed_cards():
    calls = []

    def fake_renderer(url):
        calls.append(url)
        return HTML

    source = IndeedSource(id="s1", name="Indeed - Backend", type="indeed",
                           url="https://indeed.test/jobs?q=backend")

    jobs = indeed.fetch(source, html_renderer=fake_renderer)

    assert calls == ["https://indeed.test/jobs?q=backend"]
    assert len(jobs) == 1
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].company == "Acme Corp"
    assert jobs[0].location == "Remote"
    assert jobs[0].url == "https://indeed.test/rc/clk?jk=xyz"
    assert jobs[0].key == "indeed:https://indeed.test/rc/clk?jk=xyz"


def test_fetch_returns_empty_list_when_no_cards_match():
    def fake_renderer(url):
        return "<html><body>no jobs here</body></html>"

    source = IndeedSource(id="s1", name="Indeed", type="indeed", url="https://indeed.test/jobs")

    assert indeed.fetch(source, html_renderer=fake_renderer) == []
