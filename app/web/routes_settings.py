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
    return templates.TemplateResponse(request, "settings_preferences.html", {})


@router.post("/settings/data/clear-cache")
def clear_cache(request: Request):
    db.clear_jobs(request.app.state.conn)
    return RedirectResponse(url="/settings/data?cleared=1", status_code=303)


@router.get("/settings/data/sources/export")
def export_sources(request: Request):
    payload = config.export_sources_json(request.app.state.sources_path)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="sources.json"'},
    )


@router.post("/settings/data/sources/import")
async def import_sources(request: Request):
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
    return RedirectResponse(url=f"/settings/data?imported={len(sources)}", status_code=303)
