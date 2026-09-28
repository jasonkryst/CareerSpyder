from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from psycopg_pool import ConnectionPool

from app import checker, db
from app.orchestrator import _run_lock
from app.scheduler import run_and_notify
from app.web import ratelimit
from app.web.auth import require_user
from app.web.flash import flash_redirect
from app.web.pagination import paginate
from app.web.templating import templates

router = APIRouter()

PAGE_SIZE = 25

# Each run launches Chromium for JS-rendered sources and holds _run_lock, so a
# member mashing the button must not be able to starve the scheduler (M3).
_RUN_LIMIT = 3
_RUN_WINDOW_S = 600
_RUN_LIMITED = "Too many runs started recently. Try again in a few minutes."


def _dashboard_context(conn, request: Request, page: str, sort: str, direction: str, failures: str, current_user: dict) -> dict:
    failures_filter = failures or None
    is_admin = current_user["role"] == "admin"
    filter_user_id = None if is_admin else current_user["id"]
    total = db.count_runs(conn, failures=failures_filter, user_id=filter_user_id)
    pagination = paginate(total, page, PAGE_SIZE)
    runs = db.list_runs(
        conn, limit=PAGE_SIZE, offset=pagination.offset,
        sort=sort, direction=direction, failures=failures_filter,
        user_id=filter_user_id,
    )
    return {"runs": runs, "pagination": pagination, "failures": failures, "is_admin": is_admin}


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request, page: str = "1", sort: str = "",
    direction: str = Query("", alias="dir"), failures: str = "",
    current_user: dict = Depends(require_user),
):
    with request.app.state.pool.connection() as conn:
        context = _dashboard_context(conn, request, page, sort, direction, failures, current_user)
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/rows", response_class=HTMLResponse)
def dashboard_rows(
    request: Request, page: str = "1", sort: str = "",
    direction: str = Query("", alias="dir"), failures: str = "",
    current_user: dict = Depends(require_user),
):
    with request.app.state.pool.connection() as conn:
        context = _dashboard_context(conn, request, page, sort, direction, failures, current_user)
    return templates.TemplateResponse(request, "_history_rows.html", context)


@router.post("/run-now")
def run_now(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_user),
):
    if not ratelimit.check(f"run-now:{current_user['id']}", _RUN_LIMIT, _RUN_WINDOW_S):
        return flash_redirect("/", _RUN_LIMITED)
    only_user_id = None if current_user["role"] == "admin" else current_user["id"]
    background_tasks.add_task(
        run_and_notify, request.app.state.pool, request.app.state.tz,
        force=True, only_user_id=only_user_id,
    )
    return RedirectResponse(url="/", status_code=303)


def _run_url_check(pool: ConnectionPool, run_id: int, user_id: str | None = None) -> None:
    # Serializes against orchestrator.run_once the same way two overlapping
    # runs already serialize against each other (see #132) -- without this,
    # clicking "Check job URLs" mid-scrape writes through the shared
    # connection from two threads with no coordination.
    with _run_lock, pool.connection() as conn:
        removed = checker.check_job_urls(conn, user_id=user_id)
        db.finish_run(conn, run_id, removed, [])


@router.post("/check-urls")
def check_urls(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_user),
):
    if not ratelimit.check(f"check-urls:{current_user['id']}", _RUN_LIMIT, _RUN_WINDOW_S):
        return flash_redirect("/", _RUN_LIMITED)
    is_admin = current_user["role"] == "admin"
    check_user_id = None if is_admin else current_user["id"]
    with request.app.state.pool.connection() as conn:
        run_id = db.start_run(conn, kind="url_check", user_id=current_user["id"])
    background_tasks.add_task(_run_url_check, request.app.state.pool, run_id, check_user_id)
    return RedirectResponse(url="/", status_code=303)
