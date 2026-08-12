from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db
from app.web.templating import templates

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
def show_settings(request: Request):
    settings = db.get_settings(request.app.state.conn)
    return templates.TemplateResponse(request, "settings.html", {"settings": settings})


@router.post("/settings")
async def save_settings(request: Request):
    form = dict((await request.form()).items())
    db.save_settings(
        request.app.state.conn,
        form["smtp_host"], int(form["smtp_port"]), form["smtp_user"],
        form["email_from"], form["email_to"],
    )
    return RedirectResponse(url="/settings", status_code=303)
