import logging
from urllib.parse import quote

import requests

from app.config import GreenhouseSource
from app.models import Job
from app.textutils import to_summary

logger = logging.getLogger(__name__)


def fetch(source: GreenhouseSource, http_get=requests.get) -> list[Job]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{quote(source.board_token, safe='')}/jobs?content=true"
    resp = http_get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    jobs = []
    for item in data.get("jobs", []):
        try:
            jobs.append(Job(
                key=f"greenhouse:{item['id']}",
                title=item["title"],
                url=item["absolute_url"],
                company=source.company,
                location=(item.get("location") or {}).get("name"),
                posted_date=item.get("updated_at"),
                source_name=source.name,
                source_id=source.id,
                summary=to_summary(item.get("content")),
            ))
        except (KeyError, TypeError, AttributeError):
            logger.warning("greenhouse: skipping malformed record from %s: %r", source.name, item)
    return jobs
