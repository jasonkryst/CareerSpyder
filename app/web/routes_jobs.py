from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app import config, db
from app.geocoding.factory import get_geocoder
from app.models import JOB_STATUSES as STATUSES
from app.textutils import safe_url_scheme
from app.web.flash import flash_redirect
from app.web.pagination import paginate
from app.web.templating import templates

router = APIRouter()

PAGE_SIZE = 25


def _age_days(first_seen_at: str, removed_at: str | None) -> int:
    start = datetime.fromisoformat(first_seen_at)
    end = datetime.fromisoformat(removed_at) if removed_at else datetime.now(UTC)
    return (end - start).days


def _form_str(form: dict, key: str) -> str:
    value = form.get(key, "")
    return value if isinstance(value, str) else ""


def _secondary_source_ids(sources_path: str) -> set[str]:
    return {s.id for s in config.load_sources(sources_path) if s.secondary}


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


@router.get("/jobs", response_class=HTMLResponse)
def jobs(
    request: Request, page: str = "1", sort: str = "",
    direction: str = Query("", alias="dir"),
    company: str = "", source: str = "", removed: str = "active", emailed: str = "", status: str = "",
    location: str = "", duplicates: str = "",
):
    conn = request.app.state.conn
    filters = {
        "company": company or None, "source_name": source or None,
        "removed": removed or None, "emailed": emailed or None, "status": status or None,
        "location": location or None, "duplicates": duplicates or None,
    }
    total = db.count_jobs(conn, **filters)
    pagination = paginate(total, page, PAGE_SIZE)
    rows = db.list_jobs(
        conn, limit=PAGE_SIZE, offset=pagination.offset, sort=sort, direction=direction, **filters,
    )
    secondary_ids = _secondary_source_ids(request.app.state.sources_path)
    history = db.get_job_status_history(conn, [row["key"] for row in rows])
    for row in rows:
        row["age_days"] = _age_days(row["first_seen_at"], row["removed_at"])
        row["safe_url"] = safe_url_scheme(row["url"])
        row["is_secondary"] = row["source_id"] in secondary_ids
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
            "status": status, "location": location, "duplicates": duplicates,
        },
    })


@router.get("/jobs/map", response_class=HTMLResponse)
def jobs_map(
    request: Request,
    company: str = "", source: str = "", location: str = "", removed: str = "active",
    emailed: str = "", status: str = "",
):
    conn = request.app.state.conn
    source_names = db.list_job_source_names(conn)
    locations = db.list_job_locations(conn)
    return templates.TemplateResponse(request, "jobs_map.html", {
        "source_names": source_names, "locations": locations,
        "filters": {
            "company": company, "source": source, "location": location,
            "removed": removed, "emailed": emailed, "status": status,
        },
    })


@router.get("/jobs/map/data")
def jobs_map_data(
    request: Request,
    company: str = "", source: str = "", location: str = "", removed: str = "active",
    emailed: str = "", status: str = "",
):
    conn = request.app.state.conn
    settings = db.get_settings(conn)
    hide_not_interested = settings is None or settings["hide_not_interested_on_map"]
    exclude_status = "not_interested" if hide_not_interested and status != "not_interested" else None
    rows = db.list_mappable_jobs(
        conn, company=company or None, source_name=source or None, location=location or None,
        removed=removed or None, emailed=emailed or None, status=status or None,
        exclude_status=exclude_status,
    )
    grouped: dict[tuple, dict] = {}
    for row in rows:
        key = (row["lat"], row["lng"])
        entry = grouped.setdefault(key, {
            "lat": row["lat"], "lng": row["lng"], "display_name": row["display_name"], "jobs": [],
        })
        entry["jobs"].append({
            "key": row["key"], "title": row["title"], "company": row["company"],
            "url": safe_url_scheme(row["url"]),
            "is_overridden": row["is_overridden"],
        })
    return list(grouped.values())


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
    if _wants_json(request):
        return JSONResponse({"ok": True, "message": message, "status": status})
    return flash_redirect("/jobs", message)


@router.post("/jobs/remove")
async def remove_job(request: Request):
    form = dict((await request.form()).items())
    key = _form_str(form, "key")
    if not key:
        raise HTTPException(status_code=400, detail="Missing job key")
    conn = request.app.state.conn
    try:
        db.mark_job_removed(conn, key)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    if _wants_json(request):
        row = conn.execute("SELECT removed_at FROM jobs WHERE key = ?", (key,)).fetchone()
        return JSONResponse({"ok": True, "message": "Job marked as removed.", "removed_at": row[0] if row else None})
    return flash_redirect("/jobs", "Job marked as removed.")


@router.post("/jobs/duplicate")
async def update_job_duplicate(request: Request):
    form = dict((await request.form()).items())
    key = _form_str(form, "key")
    action = _form_str(form, "action")
    duplicate_of = _form_str(form, "duplicate_of").strip() or None

    if not key:
        raise HTTPException(status_code=400, detail="Missing job key")

    conn = request.app.state.conn
    try:
        if action == "clear":
            db.clear_job_duplicate(conn, key)
            message = "Duplicate flag cleared."
        else:
            db.set_job_duplicate(conn, key, duplicate_of)
            message = "Marked as duplicate."
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")

    if _wants_json(request):
        return JSONResponse({
            "ok": True, "message": message,
            "is_duplicate": action != "clear",
            "duplicate_of": duplicate_of if action != "clear" else None,
        })
    return flash_redirect("/jobs", message)


@router.post("/jobs/location-override")
async def update_location_override(request: Request):
    form = dict((await request.form()).items())
    key = _form_str(form, "key")
    location = _form_str(form, "location").strip()

    if not key:
        raise HTTPException(status_code=400, detail="Missing job key")

    conn = request.app.state.conn

    if not location:
        try:
            db.clear_location_override(conn, key)
        except KeyError:
            raise HTTPException(status_code=404, detail="Job not found")
        return JSONResponse({"ok": True, "message": "Location override cleared."})

    geocoder = get_geocoder()
    result = geocoder.geocode(location)

    if result is None:
        raise HTTPException(status_code=400, detail="Location could not be resolved on the map")

    try:
        db.set_location_override(
            conn, key, location,
            display_name=result.display_name,
            city=result.city,
            region=result.region,
            country=result.country,
            lat=result.lat,
            lng=result.lng,
            provider=geocoder.name,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")

    return JSONResponse({
        "ok": True, "message": "Location override saved.",
        "display_name": result.display_name,
        "location_override": location,
    })
