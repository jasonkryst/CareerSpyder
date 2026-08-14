from datetime import UTC, datetime

from fastapi import APIRouter, Request
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
def jobs(request: Request, page: str = "1"):
    total = db.count_jobs(request.app.state.conn)
    pagination = paginate(total, page, PAGE_SIZE)
    rows = db.list_jobs(request.app.state.conn, limit=PAGE_SIZE, offset=pagination.offset)
    for row in rows:
        row["age_days"] = _age_days(row["first_seen_at"], row["removed_at"])
        row["safe_url"] = safe_url_scheme(row["url"])
    return templates.TemplateResponse(request, "jobs.html", {"jobs": rows, "pagination": pagination})
