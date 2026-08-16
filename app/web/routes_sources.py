from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from app import config
from app.adapters import ADAPTERS
from app.textutils import safe_url_scheme
from app.web.pagination import paginate
from app.web.source_form import echo_source, source_from_form
from app.web.templating import templates

router = APIRouter()

PAGE_SIZE = 25

_SOURCE_SORT_KEYS = {
    "name": lambda s: (s.name or "").lower(),
    "type": lambda s: (s.type or "").lower(),
    "company": lambda s: (s.company or "").lower(),
}


@router.get("/sources", response_class=HTMLResponse)
def list_sources(
    request: Request, page: str = "1", sort: str = "",
    direction: str = Query("", alias="dir"), source_type: str = Query("", alias="type"),
):
    all_sources = config.load_sources(request.app.state.sources_path)
    available_types = sorted({s.type for s in all_sources})
    if source_type:
        all_sources = [s for s in all_sources if s.type == source_type]
    key_fn = _SOURCE_SORT_KEYS.get(sort)
    if key_fn:
        all_sources = sorted(all_sources, key=key_fn, reverse=(direction == "desc"))
    pagination = paginate(len(all_sources), page, PAGE_SIZE)
    sources = all_sources[pagination.offset : pagination.offset + PAGE_SIZE]
    return templates.TemplateResponse(
        request, "sources_list.html", {
            "sources": sources, "pagination": pagination,
            "available_types": available_types, "filters": {"type": source_type},
        },
    )


@router.post("/sources/{source_id}/delete")
def delete_source(request: Request, source_id: str):
    try:
        config.delete_source(request.app.state.sources_path, source_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Source not found")
    return RedirectResponse(url="/sources", status_code=303)


@router.get("/sources/new", response_class=HTMLResponse)
def new_source_form(request: Request):
    return templates.TemplateResponse(request, "source_form.html", {"source": None, "action": "/sources/new"})


@router.post("/sources/new")
async def create_source(request: Request):
    form = dict((await request.form()).items())
    try:
        source = source_from_form(form)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "source_form.html",
            {"source": echo_source(form), "action": "/sources/new", "error": str(exc)},
            status_code=400,
        )
    config.add_source(request.app.state.sources_path, source)
    return RedirectResponse(url="/sources", status_code=303)


@router.get("/sources/{source_id}/edit", response_class=HTMLResponse)
def edit_source_form(request: Request, source_id: str):
    try:
        source = config.get_source(request.app.state.sources_path, source_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Source not found")
    return templates.TemplateResponse(
        request, "source_form.html", {"source": source, "action": f"/sources/{source_id}/edit"}
    )


@router.post("/sources/{source_id}/edit")
async def update_source(request: Request, source_id: str):
    form = dict((await request.form()).items())
    action = f"/sources/{source_id}/edit"
    try:
        source = source_from_form(form)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "source_form.html",
            {"source": echo_source(form), "action": action, "error": str(exc)},
            status_code=400,
        )
    # The id is determined by the URL path, not by whatever the (hidden)
    # form field carried — prevents a tampered hidden field from rewriting
    # a different source's id.
    source.id = source_id
    try:
        config.update_source(request.app.state.sources_path, source_id, source)
    except KeyError:
        raise HTTPException(status_code=404, detail="Source not found")
    return RedirectResponse(url="/sources", status_code=303)


@router.post("/sources/test-preview")
async def test_source_preview(request: Request):
    form = dict((await request.form()).items())
    try:
        source = source_from_form(form)
    except ValidationError as exc:
        return {"error": str(exc)}
    try:
        # Adapters raise heterogeneous exceptions (requests, BeautifulSoup
        # selectors, Playwright) — this endpoint's job is to report any of
        # them back to the UI as a preview error, not to crash.
        jobs: list = await run_in_threadpool(ADAPTERS[source.type], source)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return {"jobs": [{"title": j.title, "url": safe_url_scheme(j.url)} for j in jobs]}
