from app.adapters import generic_html
from app.config import GenericHtmlSource, Selectors


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


HTML = """
<html><body>
  <div class="job">
    <span class="t">Backend Engineer</span>
    <a href="https://customco.test/jobs/1">apply</a>
    <span class="loc">Remote</span>
  </div>
  <div class="job">
    <span class="t">Sales Rep</span>
    <a href="https://customco.test/jobs/2">apply</a>
    <span class="loc">NYC</span>
  </div>
</body></html>
"""


def selectors():
    return Selectors(job_card=".job", title=".t", link="a", location=".loc")


def test_fetch_static_page_uses_http_get():
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return FakeResponse(HTML)

    source = GenericHtmlSource(id="s1", name="Custom Co", company="Custom Co", type="generic_html",
                                url="https://customco.test/careers", render_js=False, selectors=selectors())

    jobs = generic_html.fetch(source, http_get=fake_get)

    assert calls == ["https://customco.test/careers"]
    assert len(jobs) == 2
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].url == "https://customco.test/jobs/1"
    assert jobs[0].location == "Remote"
    assert jobs[0].source_name == "Custom Co"


def test_fetch_render_js_uses_html_renderer_instead_of_http_get():
    renderer_calls = []

    def fake_renderer(url):
        renderer_calls.append(url)
        return HTML

    def fake_get(url, timeout):
        raise AssertionError("http_get should not be called when render_js is True")

    source = GenericHtmlSource(id="s1", name="Custom Co", company="Custom Co", type="generic_html",
                                url="https://customco.test/careers", render_js=True, selectors=selectors())

    jobs = generic_html.fetch(source, http_get=fake_get, html_renderer=fake_renderer)

    assert renderer_calls == ["https://customco.test/careers"]
    assert len(jobs) == 2


def test_relative_href_is_resolved_against_source_url():
    html = """
    <html><body>
      <div class="job">
        <span class="t">Backend Engineer</span>
        <a href="/careers/apply/1">apply</a>
        <span class="loc">Remote</span>
      </div>
    </body></html>
    """

    def fake_get(url, timeout):
        return FakeResponse(html)

    source = GenericHtmlSource(id="s1", name="Custom Co", company="Custom Co", type="generic_html",
                                url="https://customco.test/careers", selectors=selectors())

    jobs = generic_html.fetch(source, http_get=fake_get)

    assert len(jobs) == 1
    assert jobs[0].url == "https://customco.test/careers/apply/1"


def test_missing_title_or_link_is_skipped_not_crashed():
    html = '<div class="job"><span class="t">No Link</span></div>'

    def fake_get(url, timeout):
        return FakeResponse(html)

    source = GenericHtmlSource(id="s1", name="Custom Co", type="generic_html",
                                url="https://customco.test/careers", selectors=selectors())

    jobs = generic_html.fetch(source, http_get=fake_get)

    assert jobs == []
