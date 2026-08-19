from dataclasses import dataclass

JOB_STATUSES = {
    "applied": "Applied",
    "ignored": "Ignored",
    "accepted": "Accepted",
    "rejected": "Rejected",
    "not_interested": "Not Interested",
}


@dataclass
class Job:
    key: str
    title: str
    url: str
    company: str | None = None
    location: str | None = None
    posted_date: str | None = None
    source_name: str = ""
    source_id: str | None = None
    summary: str | None = None
