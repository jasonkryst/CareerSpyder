from datetime import UTC, datetime

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app import db
from app.textutils import safe_url_scheme
from app.web.pagination import paginate
from app.web.templating import templates

router = APIRouter()

PAGE_SIZE = 25


def _age_days(first_seen_at: str, removed_at: str | None) -> int:
    start = datetime.fromisoformat(first_seen_at)
    end = datetime.fromisoformat(removed_at) if removed_at else datetime.now(UTC)
    return (end - start).days


@router.get("/jobs", response_class=HTMLResponse)
def jobs(
    request: Request, page: str = "1", sort: str = "",
    direction: str = Query("", alias="dir"),
    company: str = "", source: str = "", removed: str = "", emailed: str = "",
):
    conn = request.app.state.conn
    filters = {
        "company": company or None, "source_name": source or None,
        "removed": removed or None, "emailed": emailed or None,
    }
    total = db.count_jobs(conn, **filters)
    pagination = paginate(total, page, PAGE_SIZE)
    rows = db.list_jobs(
        conn, limit=PAGE_SIZE, offset=pagination.offset, sort=sort, direction=direction, **filters,
    )
    for row in rows:
        row["age_days"] = _age_days(row["first_seen_at"], row["removed_at"])
        row["safe_url"] = safe_url_scheme(row["url"])
    source_names = db.list_job_source_names(conn)
    return templates.TemplateResponse(request, "jobs.html", {
        "jobs": rows, "pagination": pagination, "source_names": source_names,
        "filters": {"company": company, "source": source, "removed": removed, "emailed": emailed},
    })
