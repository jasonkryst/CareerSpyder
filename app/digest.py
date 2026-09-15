from dataclasses import dataclass
from datetime import datetime
from html import escape

from app.models import JOB_STATUSES, FailedSource, Job
from app.textutils import safe_url_scheme


@dataclass
class Digest:
    subject: str
    html_body: str


def _safe_href(url: str) -> str:
    return escape(safe_url_scheme(url), quote=True)


def _render_job_item(
    job: Job,
    secondary_source_ids: set[str],
    statuses: dict[str, str | None],
) -> str:
    location = f" — {escape(job.location)}" if job.location else ""
    is_secondary = job.source_id in secondary_source_ids
    source_label = f"{escape(job.source_name)} [Secondary]" if is_secondary else escape(job.source_name)
    source = f" (via {source_label})" if job.source_name else ""
    status = statuses.get(job.key)
    status_html = f" [{escape(JOB_STATUSES.get(status, status))}]" if status else ""
    href = _safe_href(job.url)
    title = escape(job.title)
    return f'<li><a href="{href}">{title}</a>{location}{source}{status_html}</li>'


def _render_job_list(
    jobs: list[Job],
    secondary_source_ids: set[str],
    statuses: dict[str, str | None],
    empty_text: str,
) -> list[str]:
    if not jobs:
        return [f"<p><em>{escape(empty_text)}</em></p>"]
    parts = ["<ul>"]
    for job in jobs:
        parts.append(_render_job_item(job, secondary_source_ids, statuses))
    parts.append("</ul>")
    return parts


def build_digest(
    new_jobs: list[Job], failed_sources: list[FailedSource], job_label: str = "new job", *,
    statuses: dict[str, str | None] | None = None,
    searched_at: datetime | None = None,
    jobs_url: str | None = None,
    secondary_source_ids: set[str] | None = None,
    emailed_keys: set[str] | None = None,
) -> Digest | None:
    """Build an email digest.

    When `emailed_keys` is provided (resend=ON), each company section is split
    into "Newly identified" (never been in a digest before) and "Already
    identified" (emailed at least once in a prior run). Each subsection shows a
    placeholder when empty. When `emailed_keys` is None the flat layout is used.
    """
    if not new_jobs and not failed_sources:
        return None

    statuses = statuses or {}
    secondary_source_ids = secondary_source_ids or set()

    subject = (
        f"CareerSpyder: {len(new_jobs)} {job_label}(s)" if new_jobs
        else "CareerSpyder: run had failed sources"
    )

    parts: list[str] = []
    if searched_at is not None:
        parts.append(f"<p>Searched {escape(searched_at.strftime('%b %d, %Y %I:%M %p %Z'))}</p>")

    if new_jobs:
        by_company: dict[str, list[Job]] = {}
        for job in new_jobs:
            by_company.setdefault(job.company or "Unknown", []).append(job)
        for company, jobs in by_company.items():
            parts.append(f"<h3>{escape(company)}</h3>")
            if emailed_keys is not None:
                unseen = [j for j in jobs if j.key not in emailed_keys]
                seen = [j for j in jobs if j.key in emailed_keys]
                parts.append("<h4>Newly identified</h4>")
                parts.extend(_render_job_list(unseen, secondary_source_ids, statuses, "No newly identified jobs."))
                parts.append("<h4>Already identified</h4>")
                parts.extend(_render_job_list(seen, secondary_source_ids, statuses, "No previously identified jobs."))
            else:
                parts.extend(_render_job_list(jobs, secondary_source_ids, statuses, ""))

    if failed_sources:
        parts.append("<h3>Sources that failed this run</h3><ul>")
        for fs in failed_sources:
            if fs.url:
                href = _safe_href(fs.url)
                parts.append(
                    f'<li><a href="{href}" target="_blank" rel="noopener noreferrer">'
                    f'{escape(fs.name)}</a></li>'
                )
            else:
                parts.append(f"<li>{escape(fs.name)}</li>")
        parts.append("</ul>")

    if jobs_url:
        parts.append(f'<p><a href="{escape(jobs_url, quote=True)}">View all jobs</a></p>')

    return Digest(subject=subject, html_body="".join(parts))
