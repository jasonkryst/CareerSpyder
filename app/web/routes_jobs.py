from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app import db
from app.textutils import safe_url_scheme
from app.web.flash import flash_redirect
from app.web.pagination import paginate
from app.web.templating import templates

router = APIRouter()

PAGE_SIZE = 25
STATUSES = {"applied": "Applied", "ignored": "Ignored", "accepted": "Accepted", "rejected": "Rejected"}


def _age_days(first_seen_at: str, removed_at: str | None) -> int:
    start = datetime.fromisoformat(first_seen_at)
    end = datetime.fromisoformat(removed_at) if removed_at else datetime.now(UTC)
    return (end - start).days


def _form_str(form: dict, key: str) -> str:
    value = form.get(key, "")
    return value if isinstance(value, str) else ""


@router.get("/jobs", response_class=HTMLResponse)
def jobs(
    request: Request, page: str = "1", sort: str = "",
    direction: str = Query("", alias="dir"),
    company: str = "", source: str = "", removed: str = "", emailed: str = "", status: str = "",
    location: str = "",
):
    conn = request.app.state.conn
    filters = {
        "company": company or None, "source_name": source or None,
        "removed": removed or None, "emailed": emailed or None, "status": status or None,
        "location": location or None,
    }
    total = db.count_jobs(conn, **filters)
    pagination = paginate(total, page, PAGE_SIZE)
    rows = db.list_jobs(
        conn, limit=PAGE_SIZE, offset=pagination.offset, sort=sort, direction=direction, **filters,
    )
    history = db.get_job_status_history(conn, [row["key"] for row in rows])
    for row in rows:
        row["age_days"] = _age_days(row["first_seen_at"], row["removed_at"])
        row["safe_url"] = safe_url_scheme(row["url"])
        row["history"] = [
            {"status_label": STATUSES.get(entry["status"], "No status"), "changed_at": entry["changed_at"]}
            for entry in history.get(row["key"], [])
        ]
    source_names = db.list_job_source_names(conn)
    locations = db.list_job_locations(conn)
    return templates.TemplateResponse(request, "jobs.html", {
        "jobs": rows, "pagination": pagination, "source_names": source_names, "locations": locations,
        "statuses": STATUSES,
        "filters": {
            "company": company, "source": source, "removed": removed, "emailed": emailed,
            "status": status, "location": location,
        },
    })


@router.post("/jobs/status")
async def update_job_status(request: Request):
    form = dict((await request.form()).items())
    key = _form_str(form, "key")
    status = _form_str(form, "status") or None
    if status is not None and status not in STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    try:
        db.set_job_status(request.app.state.conn, key, status)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    message = f"Marked as {STATUSES[status]}." if status else "Status cleared."
    return flash_redirect("/jobs", message)
