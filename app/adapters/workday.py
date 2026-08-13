from urllib.parse import urlparse

import requests

from app.config import WorkdaySource
from app.models import Job

_PAGE_SIZE = 20


def _resolve(career_site_url: str) -> tuple[str, str]:
    """Returns (api_url, origin), both derived from the career site URL."""
    parsed = urlparse(career_site_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    tenant = parsed.netloc.split(".")[0]
    site = parsed.path.strip("/").split("/")[-1]
    return f"{origin}/wday/cxs/{tenant}/{site}/jobs", origin


def _parse_postings(postings: list[dict], source: WorkdaySource, origin: str) -> list[Job]:
    jobs = []
    for posting in postings:
        bullet_fields = posting.get("bulletFields") or []
        external_path = posting.get("externalPath", "")
        requisition_id = bullet_fields[1] if len(bullet_fields) > 1 else external_path
        jobs.append(Job(
            key=f"workday:{requisition_id}",
            title=posting["title"],
            url=f"{origin}{external_path}",
            company=source.company,
            location=posting.get("locationsText"),
            posted_date=posting.get("postedOn"),
            source_name=source.name,
        ))
    return jobs


def fetch(source: WorkdaySource, http_post=requests.post) -> list[Job]:
    api_url, origin = _resolve(source.career_site_url)

    def fetch_page(offset: int):
        resp = http_post(
            api_url,
            json={"appliedFacets": {}, "limit": _PAGE_SIZE, "offset": offset, "searchText": ""},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    first_page = fetch_page(0)
    total = first_page.get("total", 0)
    all_jobs = _parse_postings(first_page.get("jobPostings", []), source, origin)

    # `total` is only trustworthy on this first response -- every later
    # response reports 0 regardless of how many real results remain, and
    # requesting an offset at/past this frozen total wraps back around to
    # page 1's content instead of returning empty. Both verified directly
    # against a real Workday site -- never re-derive the bound mid-loop.
    max_offset = min(total, source.max_pages * _PAGE_SIZE)

    offset = _PAGE_SIZE
    while offset < max_offset:
        page = fetch_page(offset)
        all_jobs.extend(_parse_postings(page.get("jobPostings", []), source, origin))
        offset += _PAGE_SIZE

    return all_jobs
