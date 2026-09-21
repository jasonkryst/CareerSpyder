from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from psycopg_pool import ConnectionPool

from app import checker, db
from app.orchestrator import _run_lock
from app.scheduler import run_and_notify
from app.web.auth import require_user
from app.web.pagination import paginate
from app.web.templating import templates

router = APIRouter()

PAGE_SIZE = 25


def _dashboard_context(conn, request: Request, page: str, sort: str, direction: str, failures: str) -> dict:
    failures_filter = failures or None
    total = db.count_runs(conn, failures=failures_filter)
    pagination = paginate(total, page, PAGE_SIZE)
    runs = db.list_runs(
        conn, limit=PAGE_SIZE, offset=pagination.offset,
        sort=sort, direction=direction, failures=failures_filter,
    )
    return {"runs": runs, "pagination": pagination, "failures": failures}


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request, page: str = "1", sort: str = "",
    direction: str = Query("", alias="dir"), failures: str = "",
    current_user: dict = Depends(require_user),
):
    with request.app.state.pool.connection() as conn:
        context = _dashboard_context(conn, request, page, sort, direction, failures)
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/rows", response_class=HTMLResponse)
def dashboard_rows(
    request: Request, page: str = "1", sort: str = "",
    direction: str = Query("", alias="dir"), failures: str = "",
    current_user: dict = Depends(require_user),
):
    with request.app.state.pool.connection() as conn:
        context = _dashboard_context(conn, request, page, sort, direction, failures)
    return templates.TemplateResponse(request, "_history_rows.html", context)


@router.post("/run-now")
def run_now(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_user),
):
    background_tasks.add_task(
        run_and_notify, request.app.state.pool, request.app.state.tz, force=True,
    )
    return RedirectResponse(url="/", status_code=303)


def _run_url_check(pool: ConnectionPool, run_id: int) -> None:
    # Serializes against orchestrator.run_once the same way two overlapping
    # runs already serialize against each other (see #132) -- without this,
    # clicking "Check job URLs" mid-scrape writes through the shared
    # connection from two threads with no coordination.
    with _run_lock, pool.connection() as conn:
        removed = checker.check_job_urls(conn)
        db.finish_run(conn, run_id, removed, [])


@router.post("/check-urls")
def check_urls(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_user),
):
    with request.app.state.pool.connection() as conn:
        run_id = db.start_run(conn, kind="url_check")
    background_tasks.add_task(_run_url_check, request.app.state.pool, run_id)
    return RedirectResponse(url="/", status_code=303)
