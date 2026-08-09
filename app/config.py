import json
import uuid
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


class BaseSource(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    company: Optional[str] = None
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)


class GreenhouseSource(BaseSource):
    type: Literal["greenhouse"]
    board_token: str


class LeverSource(BaseSource):
    type: Literal["lever"]
    board_token: str


class Selectors(BaseModel):
    job_card: str
    title: str
    link: str
    location: Optional[str] = None


class GenericHtmlSource(BaseSource):
    type: Literal["generic_html"]
    url: str
    render_js: bool = False
    selectors: Selectors


class LinkedInSource(BaseSource):
    type: Literal["linkedin"]
    url: str


class IndeedSource(BaseSource):
    type: Literal["indeed"]
    url: str


SourceConfig = Annotated[
    Union[GreenhouseSource, LeverSource, GenericHtmlSource, LinkedInSource, IndeedSource],
    Field(discriminator="type"),
]


class SourcesFile(BaseModel):
    sources: list[SourceConfig]


def load_sources(path: str) -> list[SourceConfig]:
    with open(path) as f:
        data = json.load(f)
    return SourcesFile.model_validate(data).sources


def save_sources(path: str, sources: list) -> None:
    payload = {"sources": [s.model_dump() for s in sources]}
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


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
