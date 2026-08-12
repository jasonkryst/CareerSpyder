from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.adapters.browser import render_html
from app.config import IndeedSource
from app.models import Job


def fetch(source: IndeedSource, html_renderer=render_html) -> list[Job]:
    html = html_renderer(source.url)
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("div.job_seen_beacon"):
        title_el = card.select_one("h2.jobTitle span")
        link_el = card.select_one("h2.jobTitle a")
        if title_el is None or link_el is None:
            continue
        company_el = card.select_one("span.companyName")
        location_el = card.select_one("div.companyLocation")
        href = urljoin(source.url, link_el.get("href", ""))
        jobs.append(Job(
            key=f"indeed:{href}",
            title=title_el.get_text(strip=True),
            url=href,
            company=company_el.get_text(strip=True) if company_el else None,
            location=location_el.get_text(strip=True) if location_el else None,
            posted_date=None,
            source_name=source.name,
        ))
    return jobs
