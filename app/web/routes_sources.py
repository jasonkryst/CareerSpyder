from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from app import db
from app.adapters import ADAPTERS
from app.textutils import safe_url_scheme
from app.web.auth import require_user
from app.web.flash import flash_redirect
from app.web.pagination import paginate
from app.web.source_form import echo_source, source_from_form
from app.web.templating import templates
from app.web.validation import fmt_validation_error

router = APIRouter()

PAGE_SIZE = 25

_SOURCE_SORT_KEYS = {
    "name": lambda s: (s.name or "").lower(),
    "type": lambda s: (s.type or "").lower(),
    "company": lambda s: (s.company or "").lower(),
}


@router.get("/sources", response_class=HTMLResponse)
def list_sources(
    request: Request,
    page: str = "1",
    sort: str = "",
    direction: str = Query("", alias="dir"),
    source_type: str = Query("", alias="type"),
    current_user: dict = Depends(require_user),
):
    with request.app.state.pool.connection() as conn:
        all_sources = db.list_sources(conn, current_user["id"])
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
def delete_source(
    request: Request,
    source_id: str,
    current_user: dict = Depends(require_user),
):
    with request.app.state.pool.connection() as conn:
        try:
            db.delete_source(conn, current_user["id"], source_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Source not found")
    return flash_redirect("/sources", "Source deleted.")


@router.get("/sources/new", response_class=HTMLResponse)
def new_source_form(
    request: Request,
    current_user: dict = Depends(require_user),
):
    return templates.TemplateResponse(request, "source_form.html", {"source": None, "action": "/sources/new"})


@router.post("/sources/new")
async def create_source(
    request: Request,
    current_user: dict = Depends(require_user),
):
    form = dict((await request.form()).items())
    try:
        source = source_from_form(form)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "source_form.html",
            {"source": echo_source(form), "action": "/sources/new", "error": fmt_validation_error(exc)},
            status_code=400,
        )
    with request.app.state.pool.connection() as conn:
        db.add_source(conn, current_user["id"], source)
    return flash_redirect("/sources", "Source added.")


@router.get("/sources/{source_id}/edit", response_class=HTMLResponse)
def edit_source_form(
    request: Request,
    source_id: str,
    current_user: dict = Depends(require_user),
):
    with request.app.state.pool.connection() as conn:
        source = db.get_source(conn, current_user["id"], source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return templates.TemplateResponse(
        request, "source_form.html", {"source": source, "action": f"/sources/{source_id}/edit"}
    )


@router.post("/sources/{source_id}/edit")
async def update_source(
    request: Request,
    source_id: str,
    current_user: dict = Depends(require_user),
):
    form = dict((await request.form()).items())
    action = f"/sources/{source_id}/edit"
    try:
        source = source_from_form(form)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "source_form.html",
            {"source": echo_source(form), "action": action, "error": fmt_validation_error(exc)},
            status_code=400,
        )
    # The id is determined by the URL path, not by whatever the (hidden)
    # form field carried — prevents a tampered hidden field from rewriting
    # a different source's id.
    source.id = source_id
    with request.app.state.pool.connection() as conn:
        try:
            db.update_source(conn, current_user["id"], source_id, source)
        except KeyError:
            raise HTTPException(status_code=404, detail="Source not found")
    return flash_redirect("/sources", "Source saved.")


@router.post("/sources/test-preview")
async def test_source_preview(
    request: Request,
    current_user: dict = Depends(require_user),
):
    form = dict((await request.form()).items())
    try:
        source = source_from_form(form)
    except ValidationError as exc:
        return {"error": fmt_validation_error(exc)}
    try:
        # Adapters raise heterogeneous exceptions (requests, BeautifulSoup
        # selectors, Playwright) — this endpoint's job is to report any of
        # them back to the UI as a preview error, not to crash.
        jobs: list = await run_in_threadpool(ADAPTERS[source.type], source)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return {"jobs": [{"title": j.title, "url": safe_url_scheme(j.url)} for j in jobs]}
