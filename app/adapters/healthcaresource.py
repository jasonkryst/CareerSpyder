import requests

from app.config import HealthcareSource
from app.models import Job

_SEARCH_BODY = {
    "query": {
        "bool": {
            "must": {"match_all": {}},
            "should": {"match": {"userArea.isFeaturedJob": {"query": True, "boost": 1}}},
        }
    },
    "sort": {"title.raw": "asc"},
}


def fetch(source: HealthcareSource, http_post=requests.post) -> list[Job]:
    url = f"https://pm.healthcaresource.com/JobseekerSearchAPI/{source.site_id}/api/Search?size=1000"
    resp = http_post(url, json=_SEARCH_BODY, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    jobs = []
    for hit in data.get("hits", {}).get("hits", []):
        src = hit["_source"]
        job_id = hit["_id"].split("_")[-1]
        hiring_org = src.get("hiringOrganization") or {}
        address = (src.get("jobLocation") or {}).get("address") or {}
        jobs.append(Job(
            key=f"healthcaresource:{hit['_id']}",
            title=src["title"],
            url=f"https://pm.healthcaresource.com/CS/{source.site_id}/#/job/{job_id}",
            company=hiring_org.get("name") or source.company,
            location=address.get("addressLocalityRegion"),
            posted_date=src.get("datePosted"),
            source_name=source.name,
        ))
    return jobs
