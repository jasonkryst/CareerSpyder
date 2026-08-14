import requests

from app.config import FindlySource
from app.models import Job

_API_URL = "https://jobsapi-internal.m-cloud.io/api/job"
_PAGE_SIZE = 500


def _location(record: dict) -> str | None:
    location_type = record.get("location_type")
    if location_type:
        return location_type
    parts = [p for p in (record.get("primary_city"), record.get("primary_state")) if p]
    return ", ".join(parts) if parts else None


def fetch(source: FindlySource, http_get=requests.get) -> list[Job]:
    all_jobs: list[Job] = []
    for page in range(source.max_pages):
        offset = page * _PAGE_SIZE + 1
        resp = http_get(
            _API_URL,
            params={
                "Organization": source.org_id, "Limit": _PAGE_SIZE, "offset": offset,
                "sortfield": "open_date", "sortorder": "descending",
            },
            timeout=15,
        )
        resp.raise_for_status()
        records = resp.json().get("queryResult") or []

        for record in records:
            all_jobs.append(Job(
                key=f"findly:{record['id']}",
                title=record["title"],
                url=record["url"],
                company=record.get("company_name") or source.company,
                location=_location(record),
                posted_date=record.get("open_date"),
                source_name=source.name,
            ))

        if len(records) < _PAGE_SIZE:
            break

    return all_jobs
