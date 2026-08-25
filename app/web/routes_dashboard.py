from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import checker, db
from app.scheduler import run_and_notify
from app.web.pagination import paginate
from app.web.templating import templates

router = APIRouter()

PAGE_SIZE = 25


def _dashboard_context(request: Request, page: str, sort: str, direction: str, failures: str) -> dict:
    failures_filter = failures or None
    total = db.count_runs(request.app.state.conn, failures=failures_filter)
    pagination = paginate(total, page, PAGE_SIZE)
    runs = db.list_runs(
        request.app.state.conn, limit=PAGE_SIZE, offset=pagination.offset,
        sort=sort, direction=direction, failures=failures_filter,
    )
    return {"runs": runs, "pagination": pagination, "failures": failures}


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request, page: str = "1", sort: str = "",
    direction: str = Query("", alias="dir"), failures: str = "",
):
    context = _dashboard_context(request, page, sort, direction, failures)
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/rows", response_class=HTMLResponse)
def dashboard_rows(
    request: Request, page: str = "1", sort: str = "",
    direction: str = Query("", alias="dir"), failures: str = "",
):
    context = _dashboard_context(request, page, sort, direction, failures)
    return templates.TemplateResponse(request, "_history_rows.html", context)


@router.post("/run-now")
def run_now(request: Request, background_tasks: BackgroundTasks):
    background_tasks.add_task(
        run_and_notify, request.app.state.conn, request.app.state.sources_path, force=True,
    )
    return RedirectResponse(url="/", status_code=303)


@router.post("/check-urls")
def check_urls(request: Request, background_tasks: BackgroundTasks):
    background_tasks.add_task(checker.check_job_urls, request.app.state.conn)
    return RedirectResponse(url="/", status_code=303)
