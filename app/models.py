from dataclasses import dataclass


@dataclass
class Job:
    key: str
    title: str
    url: str
    company: str | None = None
    location: str | None = None
    posted_date: str | None = None
    source_name: str = ""
