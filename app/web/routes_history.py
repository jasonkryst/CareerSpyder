from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import db

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/history", response_class=HTMLResponse)
def history(request: Request):
    runs = db.list_runs(request.app.state.conn, limit=50)
    return templates.TemplateResponse(request, "history.html", {"runs": runs})
