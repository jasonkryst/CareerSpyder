from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db
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
        _str_field(form, "email_from"), _str_field(form, "email_to"),
    )
    return RedirectResponse(url="/settings/email", status_code=303)


@router.get("/settings/data", response_class=HTMLResponse)
def show_settings_data(request: Request):
    return templates.TemplateResponse(request, "settings_data.html", {})
