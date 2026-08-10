from dataclasses import dataclass
from html import escape
from urllib.parse import urlparse

from app.models import Job

_SAFE_URL_SCHEMES = {"http", "https"}


@dataclass
class Digest:
    subject: str
    html_body: str


def _safe_href(url: str) -> str:
    try:
        scheme = urlparse(url).scheme.lower()
    except ValueError:
        return "#"
    if scheme and scheme not in _SAFE_URL_SCHEMES:
        return "#"
    return escape(url, quote=True)


def build_digest(new_jobs: list[Job], failed_sources: list[str]) -> Digest | None:
    if not new_jobs and not failed_sources:
        return None

    subject = f"CareerSpyder: {len(new_jobs)} new job(s)" if new_jobs else "CareerSpyder: run had failed sources"

    parts: list[str] = []
    if new_jobs:
        by_company: dict[str, list[Job]] = {}
        for job in new_jobs:
            by_company.setdefault(job.company or "Unknown", []).append(job)
        for company, jobs in by_company.items():
            parts.append(f"<h3>{escape(company)}</h3><ul>")
            for job in jobs:
                location = f" — {escape(job.location)}" if job.location else ""
                href = _safe_href(job.url)
                title = escape(job.title)
                parts.append(f'<li><a href="{href}">{title}</a>{location}</li>')
            parts.append("</ul>")

    if failed_sources:
        parts.append("<h3>Sources that failed this run</h3><ul>")
        for name in failed_sources:
            parts.append(f"<li>{escape(name)}</li>")
        parts.append("</ul>")

    return Digest(subject=subject, html_body="".join(parts))
