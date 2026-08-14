from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app import db
from app.web.pagination import paginate
from app.web.templating import templates

router = APIRouter()

PAGE_SIZE = 25


@router.get("/history", response_class=HTMLResponse)
def history(request: Request, page: str = "1"):
    total = db.count_runs(request.app.state.conn)
    pagination = paginate(total, page, PAGE_SIZE)
    runs = db.list_runs(request.app.state.conn, limit=PAGE_SIZE, offset=pagination.offset)
    return templates.TemplateResponse(
        request, "history.html", {"runs": runs, "pagination": pagination}
    )
