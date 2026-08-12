from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app import db
from app.web.templating import templates

router = APIRouter()


@router.get("/history", response_class=HTMLResponse)
def history(request: Request):
    runs = db.list_runs(request.app.state.conn, limit=50)
    return templates.TemplateResponse(request, "history.html", {"runs": runs})
