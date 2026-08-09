from dataclasses import dataclass
from typing import Optional


@dataclass
class Job:
    key: str
    title: str
    url: str
    company: Optional[str] = None
    location: Optional[str] = None
    posted_date: Optional[str] = None
    source_name: str = ""
