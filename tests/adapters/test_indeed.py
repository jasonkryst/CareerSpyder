from app.adapters import indeed
from app.adapters.indeed import _normalize_indeed_url
from app.config import IndeedSource

HTML = """
<html><body>
  <div class="job_seen_beacon">
    <a class="jcs-JobTitle" href="/rc/clk?jk=xyz"><span title="Backend Engineer">Backend Engineer</span></a>
    <span data-testid="company-name">Acme Corp</span>
    <div data-testid="text-location">Remote</div>
  </div>
</body></html>
"""

HTML_WITH_TRACKING = """
<html><body>
  <div class="job_seen_beacon">
    <a class="jcs-JobTitle" href="/rc/clk?jk=abc123&fccid=deadbeef&vjs=3&from=jasx&tk=1ij"><span title="SWE">SWE</span></a>
    <span data-testid="company-name">Corp</span>
    <div data-testid="text-location">Chicago, IL</div>
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
    # key is now stable jk-only; url retains jk but strips tracking params
    assert jobs[0].key == "indeed:xyz"
    assert jobs[0].url == "https://indeed.test/rc/clk?jk=xyz"
    assert jobs[0].source_id == "s1"


def test_fetch_strips_tracking_params_so_same_job_gets_the_same_key():
    """Regression for the dedup bug: the same posting served with different
    tracking params (fccid, vjs, from, tk, …) must produce the same key."""
    source = IndeedSource(id="s1", name="Indeed", type="indeed",
                           url="https://indeed.test/jobs?q=swe")

    jobs = indeed.fetch(source, html_renderer=lambda _: HTML_WITH_TRACKING)

    assert len(jobs) == 1
    assert jobs[0].key == "indeed:abc123"
    assert jobs[0].url == "https://indeed.test/rc/clk?jk=abc123"


def test_normalize_indeed_url_strips_all_tracking_params():
    url = "https://www.indeed.com/rc/clk?jk=abc123&fccid=deadbeef&vjs=3&from=jasx"
    norm_url, key = _normalize_indeed_url(url)
    assert norm_url == "https://www.indeed.com/rc/clk?jk=abc123"
    assert key == "indeed:abc123"


def test_normalize_indeed_url_falls_back_to_path_when_no_jk():
    url = "https://www.indeed.com/jobs/view/some-job"
    norm_url, key = _normalize_indeed_url(url)
    assert norm_url == "https://www.indeed.com/jobs/view/some-job"
    assert key == "indeed:https://www.indeed.com/jobs/view/some-job"


def test_fetch_returns_empty_list_when_no_cards_match():
    def fake_renderer(url):
        return "<html><body>no jobs here</body></html>"

    source = IndeedSource(id="s1", name="Indeed", type="indeed", url="https://indeed.test/jobs")

    assert indeed.fetch(source, html_renderer=fake_renderer) == []
