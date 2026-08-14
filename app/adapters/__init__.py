from collections.abc import Callable

from app.adapters import (
    findly,
    generic_html,
    greenhouse,
    healthcaresource,
    indeed,
    infor,
    lever,
    linkedin,
    phenompeople,
    talentbrew,
    workday,
)
from app.models import Job

ADAPTERS: dict[str, Callable[..., list[Job]]] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "generic_html": generic_html.fetch,
    "linkedin": linkedin.fetch,
    "indeed": indeed.fetch,
    "infor": infor.fetch,
    "healthcaresource": healthcaresource.fetch,
    "talentbrew": talentbrew.fetch,
    "workday": workday.fetch,
    "phenompeople": phenompeople.fetch,
    "findly": findly.fetch,
}
