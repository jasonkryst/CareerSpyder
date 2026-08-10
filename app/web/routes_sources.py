from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import config
from app.web.source_form import source_from_form

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


@router.get("/sources/new", response_class=HTMLResponse)
def new_source_form(request: Request):
    return templates.TemplateResponse(request, "source_form.html", {"source": None, "action": "/sources/new"})


@router.post("/sources/new")
async def create_source(request: Request):
    form = dict((await request.form()).items())
    source = source_from_form(form)
    config.add_source(request.app.state.sources_path, source)
    return RedirectResponse(url="/sources", status_code=303)


@router.get("/sources/{source_id}/edit", response_class=HTMLResponse)
def edit_source_form(request: Request, source_id: str):
    source = config.get_source(request.app.state.sources_path, source_id)
    return templates.TemplateResponse(
        request, "source_form.html", {"source": source, "action": f"/sources/{source_id}/edit"}
    )


@router.post("/sources/{source_id}/edit")
async def update_source(request: Request, source_id: str):
    form = dict((await request.form()).items())
    source = source_from_form(form)
    config.update_source(request.app.state.sources_path, source_id, source)
    return RedirectResponse(url="/sources", status_code=303)
