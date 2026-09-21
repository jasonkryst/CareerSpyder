from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db
from app.web.auth import require_admin
from app.web.templating import templates

router = APIRouter()


@router.get("/users", response_class=HTMLResponse)
def users_list(
    request: Request,
    current_user: dict = Depends(require_admin),
):
    with request.app.state.pool.connection() as conn:
        users = db.list_users(conn)
    return templates.TemplateResponse(request, "users.html", {"users": users})


@router.post("/users/invite")
async def invite_user(
    request: Request,
    email: str = Form(...),
    current_user: dict = Depends(require_admin),
):
    email = email.strip().lower()
    if not email or "@" not in email:
        with request.app.state.pool.connection() as conn:
            users = db.list_users(conn)
        return templates.TemplateResponse(
            request, "users.html",
            {"users": users, "invite_error": "A valid email address is required."},
            status_code=400,
        )

    with request.app.state.pool.connection() as conn:
        existing = db.get_user_by_email(conn, email)
        if existing:
            users = db.list_users(conn)
            return templates.TemplateResponse(
                request, "users.html",
                {"users": users, "invite_error": f"An account with {email} already exists."},
                status_code=400,
            )
        invite = db.create_invite(conn, email, current_user["id"])
        users = db.list_users(conn)

    base = str(request.base_url).rstrip("/")
    invite_url = f"{base}/register?token={invite['token']}"
    return templates.TemplateResponse(
        request, "users.html",
        {"users": users, "invite_url": invite_url, "invite_email": email},
    )


@router.post("/users/{user_id}/deactivate")
def deactivate_user(
    request: Request,
    user_id: str,
    current_user: dict = Depends(require_admin),
):
    if user_id == current_user["id"]:
        with request.app.state.pool.connection() as conn:
            users = db.list_users(conn)
        return templates.TemplateResponse(
            request, "users.html",
            {"users": users, "deactivate_error": "You cannot deactivate your own account."},
            status_code=400,
        )

    with request.app.state.pool.connection() as conn:
        user = db.get_user_by_id(conn, user_id)
        if user is None:
            raise HTTPException(status_code=404)
        db.deactivate_user(conn, user_id)

    flash = quote(f"User {user['username']} deactivated.")
    return RedirectResponse(url=f"/users?flash={flash}", status_code=303)
