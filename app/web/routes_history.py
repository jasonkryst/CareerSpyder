from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app import db
from app.web.pagination import paginate
from app.web.templating import templates

router = APIRouter()

PAGE_SIZE = 25


def _history_context(request: Request, page: str) -> dict:
    total = db.count_runs(request.app.state.conn)
    pagination = paginate(total, page, PAGE_SIZE)
    runs = db.list_runs(request.app.state.conn, limit=PAGE_SIZE, offset=pagination.offset)
    return {"runs": runs, "pagination": pagination}


@router.get("/history", response_class=HTMLResponse)
def history(request: Request, page: str = "1"):
    return templates.TemplateResponse(request, "history.html", _history_context(request, page))


@router.get("/history/rows", response_class=HTMLResponse)
def history_rows(request: Request, page: str = "1"):
    return templates.TemplateResponse(request, "_history_rows.html", _history_context(request, page))
