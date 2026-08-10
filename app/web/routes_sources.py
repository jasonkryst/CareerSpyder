from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import config

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/sources", response_class=HTMLResponse)
def list_sources(request: Request):
    sources = config.load_sources(request.app.state.sources_path)
    return templates.TemplateResponse(request, "sources_list.html", {"sources": sources})


@router.post("/sources/{source_id}/delete")
def delete_source(request: Request, source_id: str):
    config.delete_source(request.app.state.sources_path, source_id)
    return RedirectResponse(url="/sources", status_code=303)
