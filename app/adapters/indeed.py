from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from app.adapters.browser import render_html
from app.config import IndeedSource
from app.models import Job


def _normalize_indeed_url(href: str) -> tuple[str, str]:
    """Return (normalized_url, stable_key) for an Indeed job href.

    Indeed search-result links carry tracking params (fccid, vjs, from, tk, …)
    that change between runs, causing the same posting to get a different key
    and be re-reported as new. The `jk` param is the stable job ID — keep only
    that and use it as the key, matching how linkedin.py strips its query string.
    """
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)
    jk = qs.get("jk", [""])[0]
    if jk:
        norm_url = parsed._replace(query=urlencode({"jk": jk}), fragment="").geturl()
        return norm_url, f"indeed:{jk}"
    # No jk param — strip everything and fall back to path (rare, but safe)
    norm_url = parsed._replace(query="", fragment="").geturl()
    return norm_url, f"indeed:{norm_url}"


def fetch(source: IndeedSource, html_renderer=render_html) -> list[Job]:
    html = html_renderer(source.url)
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("div.job_seen_beacon"):
        link_el = card.select_one("a.jcs-JobTitle")
        title_el = link_el.select_one("span[title]") if link_el else None
        if title_el is None or link_el is None:
            continue
        company_el = card.select_one('span[data-testid="company-name"]')
        location_el = card.select_one('div[data-testid="text-location"]')
        raw_href = urljoin(source.url, str(link_el.get("href", "")))
        href, job_key = _normalize_indeed_url(raw_href)
        jobs.append(Job(
            key=job_key,
            title=title_el.get_text(strip=True),
            url=href,  # tracking params stripped; only jk retained
            company=company_el.get_text(strip=True) if company_el else None,
            location=location_el.get_text(strip=True) if location_el else None,
            posted_date=None,
            source_name=source.name,
            source_id=source.id,
        ))
    return jobs
