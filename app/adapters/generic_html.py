import requests
from bs4 import BeautifulSoup

from app.adapters.browser import render_html
from app.config import GenericHtmlSource
from app.models import Job


def fetch(source: GenericHtmlSource, http_get=requests.get, html_renderer=render_html) -> list[Job]:
    if source.render_js:
        html = html_renderer(source.url)
    else:
        resp = http_get(source.url, timeout=15)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select(source.selectors.job_card):
        title_el = card.select_one(source.selectors.title)
        link_el = card.select_one(source.selectors.link)
        if title_el is None or link_el is None:
            continue
        location_el = card.select_one(source.selectors.location) if source.selectors.location else None
        href = link_el.get("href", "")
        title = title_el.get_text(strip=True)
        jobs.append(Job(
            key=f"html:{source.company}:{title}:{href}",
            title=title,
            url=href,
            company=source.company,
            location=location_el.get_text(strip=True) if location_el else None,
            posted_date=None,
            source_name=source.name,
        ))
    return jobs
