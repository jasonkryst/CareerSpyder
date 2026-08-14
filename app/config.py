import json
import os
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class BaseSource(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    company: str | None = None
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
    url: str = Field(min_length=1)
    render_js: bool = False
    selectors: Selectors


class LinkedInSource(BaseSource):
    type: Literal["linkedin"]
    url: str = Field(min_length=1)


class IndeedSource(BaseSource):
    type: Literal["indeed"]
    url: str = Field(min_length=1)


class InforSource(BaseSource):
    type: Literal["infor"]
    url: str = Field(min_length=1)
    max_pages: int = 3


class HealthcareSource(BaseSource):
    type: Literal["healthcaresource"]
    site_id: str = Field(min_length=1)


class TalentBrewSource(BaseSource):
    type: Literal["talentbrew"]
    base_url: str = Field(min_length=1)
    max_pages: int = 60


class WorkdaySource(BaseSource):
    type: Literal["workday"]
    career_site_url: str = Field(min_length=1)
    max_pages: int = 60


class PhenomPeopleSource(BaseSource):
    type: Literal["phenompeople"]
    career_site_url: str = Field(min_length=1)
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


def load_sources(path: str) -> list[SourceConfig]:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        data = json.load(f)
    return SourcesFile.model_validate(data).sources


def save_sources(path: str, sources: list) -> None:
    payload = {"sources": [s.model_dump() for s in sources]}
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_path, path)


def add_source(path: str, source) -> None:
    sources = load_sources(path)
    sources.append(source)
    save_sources(path, sources)


def update_source(path: str, source_id: str, updated) -> None:
    sources = load_sources(path)
    for i, s in enumerate(sources):
        if s.id == source_id:
            sources[i] = updated
            save_sources(path, sources)
            return
    raise KeyError(source_id)


def delete_source(path: str, source_id: str) -> None:
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
