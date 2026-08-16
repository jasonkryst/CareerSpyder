from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db
from app.scheduler import run_and_notify
from app.web.pagination import paginate
from app.web.templating import templates

router = APIRouter()

PAGE_SIZE = 25


def _dashboard_context(request: Request, page: str) -> dict:
    total = db.count_runs(request.app.state.conn)
    pagination = paginate(total, page, PAGE_SIZE)
    runs = db.list_runs(request.app.state.conn, limit=PAGE_SIZE, offset=pagination.offset)
    return {"runs": runs, "pagination": pagination}


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, page: str = "1"):
    return templates.TemplateResponse(request, "dashboard.html", _dashboard_context(request, page))


@router.get("/rows", response_class=HTMLResponse)
def dashboard_rows(request: Request, page: str = "1"):
    return templates.TemplateResponse(request, "_history_rows.html", _dashboard_context(request, page))


@router.post("/run-now")
def run_now(request: Request, background_tasks: BackgroundTasks):
    background_tasks.add_task(
        run_and_notify, request.app.state.conn, request.app.state.sources_path, force=True,
    )
    return RedirectResponse(url="/", status_code=303)
