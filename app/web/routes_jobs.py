import functools
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse

from app import config, db
from app.geocoding.base import GeocoderTransientError
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


@functools.lru_cache(maxsize=256)
def _geocode_zip(zip_code: str) -> tuple[float, float] | None:
    """Cached ZIP→(lat, lng). ZIP codes are stable, so caching process-wide
    avoids a Nominatim round-trip on every page render when a zip filter is
    active (issue #B from 2026-09-04 audit, Performance H2 / Security N1)."""
    try:
        result = get_geocoder().geocode(zip_code)
    except Exception:  # noqa: BLE001
        return None
    return (result.lat, result.lng) if result else None


@router.get("/jobs", response_class=HTMLResponse)
def jobs(
    request: Request, page: str = "1", sort: str = "",
    direction: str = Query("", alias="dir"),
    company: str = "", source: Annotated[list[str], Query()] = [],  # noqa: B006
    removed: str = "active", emailed: str = "",
    status: Annotated[list[str], Query()] = [],  # noqa: B006
    location: str = "", duplicates: str = "",
    state: Annotated[list[str], Query()] = [],  # noqa: B006
    zip_code: str = Query("", alias="zip"), radius: str = "25",
):
    zip_lat: float | None = None
    zip_lng: float | None = None
    radius_miles: float | None = None
    zip_error = False
    if zip_code:
        coords = _geocode_zip(zip_code)
        if coords:
            zip_lat, zip_lng = coords
            radius_miles = float(radius) if radius in ("10", "25", "50", "100") else 25.0
        else:
            zip_error = True
    source_name = source or None
    status_filter = status or None
    state_filter = state or None
    secondary_ids = _secondary_source_ids(request.app.state.sources_path)
    with request.app.state.pool.connection() as conn:
        total = db.count_jobs(
            conn, company=company or None, source_name=source_name,
            removed=removed or None, emailed=emailed or None, status=status_filter,
            location=location or None, duplicates=duplicates or None, state=state_filter,
            zip_lat=zip_lat, zip_lng=zip_lng, radius_miles=radius_miles,
        )
        pagination = paginate(total, page, PAGE_SIZE)
        rows = db.list_jobs(
            conn, limit=PAGE_SIZE, offset=pagination.offset, sort=sort, direction=direction,
            company=company or None, source_name=source_name,
            removed=removed or None, emailed=emailed or None, status=status_filter,
            location=location or None, duplicates=duplicates or None, state=state_filter,
            zip_lat=zip_lat, zip_lng=zip_lng, radius_miles=radius_miles,
        )
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
        states = db.list_job_states(conn)
    return templates.TemplateResponse(request, "jobs.html", {
        "jobs": rows, "pagination": pagination, "source_names": source_names,
        "locations": locations, "states": states,
        "statuses": STATUSES,
        "filters": {
            "company": company, "source": source, "removed": removed, "emailed": emailed,
            "status": status, "location": location, "duplicates": duplicates,
            "state": state, "zip": zip_code, "radius": radius, "zip_error": zip_error,
        },
    })


@router.get("/jobs/map", response_class=HTMLResponse)
def jobs_map(
    request: Request,
    company: str = "", source: Annotated[list[str], Query()] = [],  # noqa: B006
    location: str = "", removed: str = "active", emailed: str = "",
    status: Annotated[list[str], Query()] = [],  # noqa: B006
    state: Annotated[list[str], Query()] = [],  # noqa: B006
    zip_code: str = Query("", alias="zip"), radius: str = "25",
):
    with request.app.state.pool.connection() as conn:
        source_names = db.list_job_source_names(conn)
        locations = db.list_job_locations(conn)
        states = db.list_job_states(conn)
    return templates.TemplateResponse(request, "jobs_map.html", {
        "source_names": source_names, "locations": locations, "states": states,
        "filters": {
            "company": company, "source": source, "location": location,
            "removed": removed, "emailed": emailed, "status": status,
            "state": state, "zip": zip_code, "radius": radius, "zip_error": False,
        },
    })


@router.get("/jobs/map/data")
def jobs_map_data(
    request: Request,
    company: str = "", source: Annotated[list[str], Query()] = [],  # noqa: B006
    location: str = "", removed: str = "active", emailed: str = "",
    status: Annotated[list[str], Query()] = [],  # noqa: B006
    state: Annotated[list[str], Query()] = [],  # noqa: B006
    zip_code: str = Query("", alias="zip"), radius: str = "25",
):
    zip_lat: float | None = None
    zip_lng: float | None = None
    radius_miles: float | None = None
    if zip_code:
        coords = _geocode_zip(zip_code)
        if coords:
            zip_lat, zip_lng = coords
            radius_miles = float(radius) if radius in ("10", "25", "50", "100") else 25.0
    with request.app.state.pool.connection() as conn:
        settings = db.get_settings(conn)
        hide_not_interested = settings is None or settings["hide_not_interested_on_map"]
        exclude_status = "not_interested" if hide_not_interested and "not_interested" not in status else None
        rows = db.list_mappable_jobs(
            conn, company=company or None, source_name=source or None, location=location or None,
            removed=removed or None, emailed=emailed or None, status=status or None,
            exclude_status=exclude_status,
            state=state or None,
            zip_lat=zip_lat, zip_lng=zip_lng, radius_miles=radius_miles,
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
        with request.app.state.pool.connection() as conn:
            db.set_job_status(conn, key, status)
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
    with request.app.state.pool.connection() as conn:
        try:
            db.mark_job_removed(conn, key)
        except KeyError:
            raise HTTPException(status_code=404, detail="Job not found")
        if _wants_json(request):
            row = conn.execute("SELECT removed_at FROM jobs WHERE key = %s", (key,)).fetchone()
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

    with request.app.state.pool.connection() as conn:
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

    if not location:
        with request.app.state.pool.connection() as conn:
            try:
                db.clear_location_override(conn, key)
            except KeyError:
                raise HTTPException(status_code=404, detail="Job not found")
        return JSONResponse({"ok": True, "message": "Location override cleared."})

    with request.app.state.pool.connection() as conn:
        cached = db.get_geocoded_location(conn, location)

    if cached is not None:
        display_name, city, region, country = (
            cached["display_name"], cached["city"], cached["region"], cached["country"],
        )
        lat, lng, provider = cached["lat"], cached["lng"], cached["provider"]
    else:
        geocoder = get_geocoder()
        # Nominatim is a blocking `requests` call; run_in_threadpool keeps it
        # off the single asyncio event loop thread (see #133) the same way
        # /sources/test-preview already does for adapter fetches.
        try:
            result = await run_in_threadpool(geocoder.geocode, location)
        except GeocoderTransientError:
            result = None
        if result is None:
            raise HTTPException(status_code=400, detail="Location could not be resolved on the map")
        display_name, city, region, country = result.display_name, result.city, result.region, result.country
        lat, lng, provider = result.lat, result.lng, geocoder.name

    with request.app.state.pool.connection() as conn:
        try:
            db.set_location_override(
                conn, key, location,
                display_name=display_name, city=city, region=region, country=country,
                lat=lat, lng=lng, provider=provider,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Job not found")

    return JSONResponse({
        "ok": True, "message": "Location override saved.",
        "display_name": display_name,
        "location_override": location,
    })
