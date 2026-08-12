from bs4 import BeautifulSoup

from app.adapters.browser import render_html
from app.config import LinkedInSource
from app.models import Job


def fetch(source: LinkedInSource, html_renderer=render_html) -> list[Job]:
    html = html_renderer(source.url)
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("div.base-card"):
        title_el = card.select_one("h3.base-search-card__title")
        link_el = card.select_one("a.base-card__full-link")
        if title_el is None or link_el is None:
            continue
        company_el = card.select_one("h4.base-search-card__subtitle")
        location_el = card.select_one("span.job-search-card__location")
        href = str(link_el.get("href", "")).split("?")[0]
        jobs.append(Job(
            key=f"linkedin:{href}",
            title=title_el.get_text(strip=True),
            url=href,
            company=company_el.get_text(strip=True) if company_el else None,
            location=location_el.get_text(strip=True) if location_el else None,
            posted_date=None,
            source_name=source.name,
        ))
    return jobs
