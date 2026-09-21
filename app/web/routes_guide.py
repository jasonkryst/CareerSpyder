from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.web.auth import require_user
from app.web.templating import templates

router = APIRouter()


@router.get("/guide", response_class=HTMLResponse)
def guide(
    request: Request,
    current_user: dict = Depends(require_user),
):
    return templates.TemplateResponse(request, "guide.html", {})
