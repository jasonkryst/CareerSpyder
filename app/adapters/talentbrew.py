import re

import requests
from bs4 import BeautifulSoup

from app.config import TalentBrewSource
from app.models import Job

_RESULTS_PARAMS = {
    "ActiveFacetID": "0",
    "RecordsPerPage": "25",
    "TotalContentResults": "",
    "Distance": "50",
    "RadiusUnitType": "0",
    "Keywords": "",
    "Location": "",
    "ShowRadius": "False",
    "IsPagination": "True",
    "CustomFacetName": "",
    "FacetTerm": "",
    "FacetType": "0",
    "SearchResultsModuleName": "Search Results",
    "SearchFiltersModuleName": "Search Filters",
    # Title (A-Z), not the page's default Relevancy (0) -- Relevancy was
    # verified to produce overlapping, non-deterministic pagination on a
    # real TalentBrew site.
    "SortCriteria": "3",
    "SortDirection": "0",
    "SearchType": "1",
    "PostalCode": "",
    "ResultsType": "0",
    "fc": "",
    "fl": "",
    "fcf": "",
    "afc": "",
    "afl": "",
    "afcf": "",
    "TotalContentPages": "",
}

_TOTAL_PAGES_RE = re.compile(r'data-total-pages="(\d+)"')


def _parse_page(html: str, source: TalentBrewSource) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select(".search-job-list-data li"):
        link = card.select_one("a")
        heading = card.select_one("h2")
        if link is None or heading is None:
            continue
        job_id = link.get("data-job-id")
        href = link.get("href", "")
        location_el = card.select_one(".job-location")
        jobs.append(Job(
            key=f"talentbrew:{job_id}",
            title=heading.get_text(strip=True),
            url=f"{source.base_url}{href}",
            company=source.company,
            location=location_el.get_text(strip=True) if location_el else None,
            posted_date=None,
            source_name=source.name,
        ))
    return jobs


def fetch(source: TalentBrewSource, http_get=requests.get) -> list[Job]:
    all_jobs: list[Job] = []
    total_pages = None
    page = 1
    while page <= source.max_pages and (total_pages is None or page <= total_pages):
        params = {**_RESULTS_PARAMS, "CurrentPage": str(page)}
        resp = http_get(
            f"{source.base_url}/search-jobs/results", params=params, timeout=15,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        resp.raise_for_status()
        html = resp.json().get("results", "")

        if total_pages is None:
            match = _TOTAL_PAGES_RE.search(html)
            total_pages = int(match.group(1)) if match else 1

        page_jobs = _parse_page(html, source)
        if not page_jobs:
            break
        all_jobs.extend(page_jobs)
        page += 1

    return all_jobs
