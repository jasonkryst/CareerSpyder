from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db
from app.scheduler import run_and_notify
from app.web.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    runs = db.list_runs(request.app.state.conn, limit=1)
    last_run = runs[0] if runs else None
    return templates.TemplateResponse(request, "dashboard.html", {"last_run": last_run})


@router.post("/run-now")
def run_now(request: Request, background_tasks: BackgroundTasks):
    background_tasks.add_task(run_and_notify, request.app.state.conn, request.app.state.sources_path)
    return RedirectResponse(url="/", status_code=303)
