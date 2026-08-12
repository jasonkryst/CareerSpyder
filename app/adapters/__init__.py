from collections.abc import Callable

from app.adapters import generic_html, greenhouse, indeed, lever, linkedin
from app.models import Job

ADAPTERS: dict[str, Callable[..., list[Job]]] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "generic_html": generic_html.fetch,
    "linkedin": linkedin.fetch,
    "indeed": indeed.fetch,
}
