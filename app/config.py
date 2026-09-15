import json
import os
import threading
import uuid
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import AfterValidator, BaseModel, Field

# Serializes all read-modify-write cycles on sources.json within a process.
# A single FastAPI process can receive concurrent requests (two browser tabs,
# scheduler + UI), and load-then-save without a lock loses one write.
_sources_lock = threading.Lock()


def _require_http_scheme(url: str) -> str:
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"URL must use http or https, got {scheme!r}")
    return url


# Restricts a source URL field to http/https at save time (issue #131) --
# the deeper check (rejecting private/loopback/link-local resolved
# addresses, re-checked after redirects) lives in app/security/ssrf_guard.py
# and runs at request time, since DNS resolution doesn't belong in a
# pydantic validator.
HttpUrlStr = Annotated[str, Field(min_length=1), AfterValidator(_require_http_scheme)]


class BaseSource(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    company: str | None = None
    secondary: bool = False
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)


class GreenhouseSource(BaseSource):
    type: Literal["greenhouse"]
    board_token: str = Field(min_length=1)


class LeverSource(BaseSource):
    type: Literal["lever"]
    board_token: str = Field(min_length=1)


class Selectors(BaseModel):
    job_card: str = Field(min_length=1)
    title: str = Field(min_length=1)
    link: str = Field(min_length=1)
    location: str | None = None


class GenericHtmlSource(BaseSource):
    type: Literal["generic_html"]
    url: HttpUrlStr
    render_js: bool = False
    selectors: Selectors


class LinkedInSource(BaseSource):
    type: Literal["linkedin"]
    url: HttpUrlStr


class IndeedSource(BaseSource):
    type: Literal["indeed"]
    url: HttpUrlStr


class InforSource(BaseSource):
    type: Literal["infor"]
    url: HttpUrlStr
    max_pages: int = 3


class HealthcareSource(BaseSource):
    type: Literal["healthcaresource"]
    site_id: str = Field(min_length=1)


class TalentBrewSource(BaseSource):
    type: Literal["talentbrew"]
    base_url: HttpUrlStr
    max_pages: int = 60


class WorkdaySource(BaseSource):
    type: Literal["workday"]
    career_site_url: HttpUrlStr
    max_pages: int = 60


class PhenomPeopleSource(BaseSource):
    type: Literal["phenompeople"]
    career_site_url: HttpUrlStr
    state: str | None = None


class FindlySource(BaseSource):
    type: Literal["findly"]
    org_id: str = Field(min_length=1)
    career_site_url: str = Field(min_length=1)
    max_pages: int = 20


SourceConfig = Annotated[
    GreenhouseSource | LeverSource | GenericHtmlSource | LinkedInSource | IndeedSource | InforSource
    | HealthcareSource | TalentBrewSource | WorkdaySource | PhenomPeopleSource | FindlySource,
    Field(discriminator="type"),
]


class SourcesFile(BaseModel):
    sources: list[SourceConfig]


def get_source_url(source: SourceConfig) -> str | None:
    match source.type:
        case "greenhouse":
            return f"https://boards.greenhouse.io/{source.board_token}"
        case "lever":
            return f"https://jobs.lever.co/{source.board_token}"
        case "generic_html" | "linkedin" | "indeed" | "infor":
            return source.url
        case "talentbrew":
            return source.base_url
        case "workday" | "phenompeople" | "findly":
            return source.career_site_url
        case "healthcaresource":
            return f"https://pm.healthcaresource.com/CS/{source.site_id}"
        case _:
            return None


def load_sources(path: str) -> list[SourceConfig]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return SourcesFile.model_validate(data).sources


def save_sources(path: str, sources: list) -> None:
    payload = {"sources": [s.model_dump() for s in sources]}
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_path, path)


def export_sources_json(path: str) -> str:
    sources = load_sources(path)
    payload = {"sources": [s.model_dump() for s in sources]}
    return json.dumps(payload, indent=2)


def import_sources_json(path: str, raw: bytes) -> list[SourceConfig]:
    data = json.loads(raw)
    sources = SourcesFile.model_validate(data).sources
    with _sources_lock:
        save_sources(path, sources)
    return sources


def add_source(path: str, source) -> None:
    with _sources_lock:
        sources = load_sources(path)
        sources.append(source)
        save_sources(path, sources)


def update_source(path: str, source_id: str, updated) -> None:
    with _sources_lock:
        sources = load_sources(path)
        for i, s in enumerate(sources):
            if s.id == source_id:
                sources[i] = updated
                save_sources(path, sources)
                return
    raise KeyError(source_id)


def delete_source(path: str, source_id: str) -> None:
    with _sources_lock:
        sources = load_sources(path)
        remaining = [s for s in sources if s.id != source_id]
        if len(remaining) == len(sources):
            raise KeyError(source_id)
        save_sources(path, remaining)


def get_source(path: str, source_id: str):
    for s in load_sources(path):
        if s.id == source_id:
            return s
    raise KeyError(source_id)
