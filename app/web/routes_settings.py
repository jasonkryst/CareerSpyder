import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from app import config, db
from app.web.templating import templates

router = APIRouter()


def _str_field(form: dict, key: str) -> str:
    value = form[key]
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{key} must be a text field")
    return value


DAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _str_list_field(form, key: str) -> list[str]:
    values = form.getlist(key)
    for value in values:
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail=f"{key} must be text fields")
    return values


def _split_emails(raw: str | None) -> list[str]:
    return [addr.strip() for addr in (raw or "").split(",") if addr.strip()]


@router.get("/settings", response_class=HTMLResponse)
def settings_redirect():
    return RedirectResponse(url="/settings/email")


@router.get("/settings/email", response_class=HTMLResponse)
def show_settings(request: Request):
    settings = db.get_settings(request.app.state.conn)
    return templates.TemplateResponse(request, "settings_email.html", {"settings": settings})


@router.post("/settings/email")
async def save_settings(request: Request):
    form = dict((await request.form()).items())
    db.save_settings(
        request.app.state.conn,
        _str_field(form, "smtp_host"), int(_str_field(form, "smtp_port")), _str_field(form, "smtp_user"),
        _str_field(form, "email_from"),
    )
    return RedirectResponse(url="/settings/email", status_code=303)


@router.get("/settings/data", response_class=HTMLResponse)
def show_settings_data(request: Request):
    return templates.TemplateResponse(request, "settings_data.html", {})


@router.get("/settings/preferences", response_class=HTMLResponse)
def show_settings_preferences(request: Request):
    settings = db.get_settings(request.app.state.conn)
    email_days_selected = set((settings["email_days"] if settings else "").split(","))
    email_to_list = _split_emails(settings["email_to"] if settings else "") or [""]
    return templates.TemplateResponse(
        request, "settings_preferences.html",
        {"settings": settings, "email_days_selected": email_days_selected, "email_to_list": email_to_list},
    )


@router.post("/settings/preferences")
async def save_preferences(request: Request):
    form = await request.form()
    selected_days = set(_str_list_field(form, "email_days")) & set(DAY_CODES)
    email_days = ",".join(day for day in DAY_CODES if day in selected_days)
    resend_jobs = "resend_jobs" in form
    email_to = ",".join(addr.strip() for addr in _str_list_field(form, "email_to") if addr.strip())
    db.save_preferences(request.app.state.conn, email_days, resend_jobs, email_to)
    return RedirectResponse(url="/settings/preferences", status_code=303)


@router.post("/settings/data/clear-cache")
def clear_cache(request: Request):
    db.clear_jobs(request.app.state.conn)
    return RedirectResponse(url="/settings/data?cleared=1", status_code=303)


DEFAULT_PREFERENCES = {"email_days": [], "resend_jobs": False, "email_to": []}


def _export_payload(request: Request) -> dict:
    sources = config.load_sources(request.app.state.sources_path)
    settings = db.get_settings(request.app.state.conn)
    if settings is None:
        preferences = dict(DEFAULT_PREFERENCES)
    else:
        preferences = {
            "email_days": [d for d in settings["email_days"].split(",") if d],
            "resend_jobs": settings["resend_jobs"],
            "email_to": [a for a in settings["email_to"].split(",") if a],
        }
    return {"sources": [s.model_dump() for s in sources], "preferences": preferences}


def _parse_preferences_import(data: dict) -> tuple[str, bool, str] | None:
    preferences = data.get("preferences")
    if preferences is None:
        return None

    raw_days = preferences.get("email_days")
    days = raw_days if isinstance(raw_days, list) else []
    selected_days = {d for d in days if isinstance(d, str)} & set(DAY_CODES)
    email_days = ",".join(day for day in DAY_CODES if day in selected_days)

    resend_jobs = preferences.get("resend_jobs")
    if not isinstance(resend_jobs, bool):
        resend_jobs = False

    raw_emails = preferences.get("email_to")
    emails = raw_emails if isinstance(raw_emails, list) else []
    email_to = ",".join(addr.strip() for addr in emails if isinstance(addr, str) and addr.strip())

    return email_days, resend_jobs, email_to


@router.get("/settings/data/export")
def export_settings(request: Request):
    payload = json.dumps(_export_payload(request), indent=2)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="settings.json"'},
    )


@router.post("/settings/data/import")
async def import_settings(request: Request):
    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return templates.TemplateResponse(
            request, "settings_data.html", {"error": "Choose a file to import."}, status_code=400,
        )
    raw = await upload.read()
    try:
        sources = config.import_sources_json(request.app.state.sources_path, raw)
    except (json.JSONDecodeError, ValidationError) as exc:
        return templates.TemplateResponse(
            request, "settings_data.html", {"error": f"Import failed: {exc}"}, status_code=400,
        )

    parsed_preferences = _parse_preferences_import(json.loads(raw))
    if parsed_preferences is not None:
        email_days, resend_jobs, email_to = parsed_preferences
        db.save_preferences(request.app.state.conn, email_days, resend_jobs, email_to)

    redirect_url = f"/settings/data?imported={len(sources)}"
    if parsed_preferences is not None:
        redirect_url += "&preferences=1"
    return RedirectResponse(url=redirect_url, status_code=303)
