"""Live integration tests for the Infor adapter.

These tests hit the real Infor job-board portals using a real Playwright
browser.  They are skipped automatically when the required env vars are not
set, so the regular test suite stays fast and network-free.

Required env vars (configure as GitHub Actions secrets, then add them to the
integration-test job in .github/workflows/ci.yml):

    INFOR_TEST_URL_RUMC            — RUMC's Infor portal URL
    INFOR_TEST_URL_RUSH_OAK_PARK   — Rush Oak Park's Infor portal URL (optional)

Run locally:
    INFOR_TEST_URL_RUMC=https://... pytest -m integration -v
"""

import os

import pytest

from app.adapters.infor import _parse_page, default_frame_fetcher
from app.config import InforSource

_RUMC_URL = os.environ.get("INFOR_TEST_URL_RUMC")
_RUSH_OAK_PARK_URL = os.environ.get("INFOR_TEST_URL_RUSH_OAK_PARK")


def _make_source(name: str, company: str, url: str) -> InforSource:
    return InforSource(id="live-test", name=name, company=company,
                       type="infor", url=url, max_pages=1)


def _assert_jobs_valid(jobs, url: str) -> None:
    assert len(jobs) > 0, f"No jobs parsed from {url}"
    for job in jobs[:5]:
        assert job.title and len(job.title.strip()) > 0, f"Empty title: {job}"
        assert job.location is not None, f"Missing location: {job}"


@pytest.mark.integration
@pytest.mark.skipif(not _RUMC_URL, reason="INFOR_TEST_URL_RUMC not set")
def test_rumc_returns_jobs():
    """RUMC is a Lawson-hybrid portal — #jobListScreen shell with a Slickgrid iframe."""
    assert _RUMC_URL  # narrow type for mypy
    html = default_frame_fetcher(_RUMC_URL, page_number=1)

    assert html is not None, f"frame fetcher returned None for {_RUMC_URL}"
    # Lawson-hybrid portals return v1 Slickgrid HTML from the iframe body.
    # If this assertion fails the portal UI has changed to v2 list-view.
    assert "inforCardstackCell" in html, (
        "Expected Lawson-hybrid (v1 Slickgrid) HTML — portal type may have changed. "
        f"HTML snippet: {html[:500]}"
    )

    source = _make_source("RUMC (live test)", "Rush University Medical Center", _RUMC_URL)
    jobs = _parse_page(html, source)
    _assert_jobs_valid(jobs, _RUMC_URL)


@pytest.mark.integration
@pytest.mark.skipif(not _RUSH_OAK_PARK_URL, reason="INFOR_TEST_URL_RUSH_OAK_PARK not set")
def test_rush_oak_park_returns_jobs():
    """Rush Oak Park is also a Lawson-hybrid Infor portal."""
    assert _RUSH_OAK_PARK_URL
    html = default_frame_fetcher(_RUSH_OAK_PARK_URL, page_number=1)

    assert html is not None, f"frame fetcher returned None for {_RUSH_OAK_PARK_URL}"
    assert "inforCardstackCell" in html, (
        "Expected Lawson-hybrid (v1 Slickgrid) HTML — portal type may have changed. "
        f"HTML snippet: {html[:500]}"
    )

    source = _make_source("Rush Oak Park (live test)", "Rush Oak Park Hospital", _RUSH_OAK_PARK_URL)
    jobs = _parse_page(html, source)
    _assert_jobs_valid(jobs, _RUSH_OAK_PARK_URL)
