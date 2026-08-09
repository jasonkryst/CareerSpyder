import requests

from app.config import LeverSource
from app.models import Job


def fetch(source: LeverSource, http_get=requests.get) -> list[Job]:
    url = f"https://api.lever.co/v0/postings/{source.board_token}?mode=json"
    resp = http_get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    jobs = []
    for item in data:
        jobs.append(Job(
            key=f"lever:{item['id']}",
            title=item["text"],
            url=item["hostedUrl"],
            company=source.company,
            location=(item.get("categories") or {}).get("location"),
            posted_date=str(item.get("createdAt")) if item.get("createdAt") else None,
            source_name=source.name,
        ))
    return jobs
