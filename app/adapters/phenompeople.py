import logging

from app.config import PhenomPeopleSource
from app.models import Job
from app.security.ssrf_guard import safe_post

logger = logging.getLogger(__name__)

_SIZE = 2000


def fetch(source: PhenomPeopleSource, http_post=safe_post) -> list[Job]:
    selected_fields = {"state": [source.state]} if source.state else {}
    resp = http_post(
        f"{source.career_site_url}/widgets",
        json={
            "ddoKey": "refineSearch",
            "from": 0,
            "size": _SIZE,
            "jobs": True,
            "counts": True,
            "selected_fields": selected_fields,
        },
        timeout=15,
    )
    resp.raise_for_status()
    hits = resp.json().get("refineSearch", {}).get("data", {}).get("jobs", [])

    jobs = []
    for hit in hits:
        try:
            job_id = hit["jobId"]
            jobs.append(Job(
                key=f"phenompeople:{job_id}",
                title=hit["title"],
                url=f"{source.career_site_url}/us/en/job/{job_id}",
                company=source.company,
                location=hit.get("location"),
                posted_date=hit.get("postedDate"),
                source_name=source.name,
                source_id=source.id,
            ))
        except (KeyError, TypeError, AttributeError):
            logger.warning("phenompeople: skipping malformed record from %s: %r", source.name, hit)
    return jobs
