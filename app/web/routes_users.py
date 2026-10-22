from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db
from app.web.auth import require_admin
from app.web.config_checks import public_base_url
from app.web.templating import templates

router = APIRouter()


def _invite_base_url(request: Request) -> str:
    return public_base_url() or str(request.base_url).rstrip("/")


def _invites_for_template(conn, current_user: dict, base: str) -> list[dict]:
    """list_invites with a ready-to-copy registration link attached to each
    still-pending invite (accepted/expired invites have nothing to link to)."""
    invites = db.list_invites(conn, current_user["id"])
    for invite in invites:
        if invite["status"] == "pending":
            invite["url"] = f"{base}/register?token={invite['token']}"
    return invites


@router.get("/users", response_class=HTMLResponse)
def users_list(
    request: Request,
    current_user: dict = Depends(require_admin),
):
    with request.app.state.pool.connection() as conn:
        users = db.list_users(conn)
        invites = _invites_for_template(conn, current_user, _invite_base_url(request))
    return templates.TemplateResponse(request, "users.html", {"users": users, "invites": invites})


@router.post("/users/invite")
async def invite_user(
    request: Request,
    email: str = Form(...),
    current_user: dict = Depends(require_admin),
):
    email = email.strip().lower()
    base = _invite_base_url(request)
    if not email or "@" not in email:
        with request.app.state.pool.connection() as conn:
            users = db.list_users(conn)
            invites = _invites_for_template(conn, current_user, base)
        return templates.TemplateResponse(
            request, "users.html",
            {"users": users, "invites": invites, "invite_error": "A valid email address is required."},
            status_code=400,
        )

    with request.app.state.pool.connection() as conn:
        existing = db.get_user_by_email(conn, email)
        if existing:
            users = db.list_users(conn)
            invites = _invites_for_template(conn, current_user, base)
            return templates.TemplateResponse(
                request, "users.html",
                {"users": users, "invites": invites, "invite_error": f"An account with {email} already exists."},
                status_code=400,
            )
        invite = db.create_invite(conn, email, current_user["id"])
        users = db.list_users(conn)
        invites = _invites_for_template(conn, current_user, base)

    invite_url = f"{base}/register?token={invite['token']}"
    return templates.TemplateResponse(
        request, "users.html",
        {"users": users, "invites": invites, "invite_url": invite_url, "invite_email": email},
    )


@router.post("/users/invite/resend")
async def resend_invite(
    request: Request,
    token: str = Form(...),
    current_user: dict = Depends(require_admin),
):
    base = _invite_base_url(request)
    with request.app.state.pool.connection() as conn:
        fresh = db.resend_invite(conn, current_user["id"], token.strip())
        if fresh is None:
            raise HTTPException(status_code=404)
        users = db.list_users(conn)
        invites = _invites_for_template(conn, current_user, base)

    invite_url = f"{base}/register?token={fresh['token']}"
    return templates.TemplateResponse(
        request, "users.html",
        {"users": users, "invites": invites, "invite_url": invite_url, "invite_email": fresh["email"]},
    )


@router.post("/users/invites/{token}/revoke")
async def revoke_invite(
    request: Request,
    token: str,
    current_user: dict = Depends(require_admin),
):
    with request.app.state.pool.connection() as conn:
        revoked = db.revoke_invite(conn, current_user["id"], token)
    if not revoked:
        raise HTTPException(status_code=404)
    flash = quote("Invite revoked.")
    return RedirectResponse(url=f"/users?flash={flash}", status_code=303)


@router.post("/users/{user_id}/deactivate")
def deactivate_user(
    request: Request,
    user_id: str,
    current_user: dict = Depends(require_admin),
):
    if user_id == current_user["id"]:
        with request.app.state.pool.connection() as conn:
            users = db.list_users(conn)
            invites = _invites_for_template(conn, current_user, _invite_base_url(request))
        return templates.TemplateResponse(
            request, "users.html",
            {"users": users, "invites": invites, "deactivate_error": "You cannot deactivate your own account."},
            status_code=400,
        )

    with request.app.state.pool.connection() as conn:
        user = db.get_user_by_id(conn, user_id)
        if user is None:
            raise HTTPException(status_code=404)
        db.deactivate_user(conn, user_id)

    flash = quote(f"User {user['username']} deactivated.")
    return RedirectResponse(url=f"/users?flash={flash}", status_code=303)
