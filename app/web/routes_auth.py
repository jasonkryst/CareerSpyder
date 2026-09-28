import logging
import os
from datetime import UTC, datetime
from html import escape as _esc
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db, emailer
from app.web.auth import (
    generate_reset_token,
    hash_password,
    password_too_long,
    start_session,
    verify_password,
    verify_reset_token,
)
from app.web.config_checks import public_base_url
from app.web.flash import flash_redirect
from app.web.ratelimit import rate_limit
from app.web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()

_TOO_LONG = "Password must be at most 72 bytes."
# Verified against for unknown usernames so a miss costs the same bcrypt time
# as a hit -- response timing must not reveal which usernames exist.
_DUMMY_HASH = hash_password("not-a-real-password")


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    next_url = request.query_params.get("next", "/")
    return templates.TemplateResponse(request, "login.html", {"next": next_url})


@router.post("/login")
async def login(request: Request):
    if not rate_limit(request, "login", max_attempts=10, window_seconds=900):
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Too many login attempts. Please wait a few minutes before trying again."},
            status_code=429,
        )

    form = dict((await request.form()).items())
    username = str(form.get("username") or "").strip()
    password = str(form.get("password") or "")
    next_url = str(form.get("next") or "/").strip() or "/"

    if not username or not password:
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Username and password are required.", "next": next_url},
            status_code=400,
        )

    with request.app.state.pool.connection() as conn:
        user = db.get_user_by_username(conn, username)

    stored_hash = user["password_hash"] if user is not None else _DUMMY_HASH
    password_ok = await run_in_threadpool(verify_password, password, stored_hash)
    if user is None or not user["is_active"] or not password_ok:
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Invalid username or password.", "next": next_url},
            status_code=401,
        )

    start_session(request, user)

    # Reject anything with a scheme or host (catches //evil.com, http://…, etc.)
    parsed = urlparse(next_url)
    safe_next = next_url if (parsed.scheme == "" and parsed.netloc == "" and next_url.startswith("/")) else "/"
    return RedirectResponse(url=safe_next, status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/account-recovery", response_class=HTMLResponse)
async def account_recovery_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "account_recovery.html", {})


@router.post("/account-recovery", response_class=HTMLResponse)
async def account_recovery(request: Request, background_tasks: BackgroundTasks):
    if not rate_limit(request, "account-recovery", max_attempts=5, window_seconds=3600):
        return templates.TemplateResponse(
            request, "account_recovery.html",
            {"submitted": True},
        )

    form = dict((await request.form()).items())
    email = str(form.get("email") or "").strip().lower()

    if not email:
        return templates.TemplateResponse(
            request, "account_recovery.html",
            {"error": "Email address is required."},
            status_code=400,
        )

    user_with_hash = None
    smtp = None
    with request.app.state.pool.connection() as conn:
        user = db.get_user_by_email(conn, email)
        if user and user["is_active"]:
            user_with_hash = db.get_user_by_id_with_hash(conn, user["id"])
            smtp = db.get_admin_smtp_settings(conn)

    base_url = public_base_url()
    if base_url is None:
        logger.error(
            "Account recovery requested but PUBLIC_BASE_URL is not set; refusing to "
            "build a reset link from the request's Host header."
        )
    elif user_with_hash and smtp and smtp.get("smtp_host"):
        token = generate_reset_token(
            request.app.state.secret_key,
            user_with_hash["id"],
            user_with_hash["email"],
            user_with_hash["password_hash"],
        )
        reset_url = base_url + f"/reset-password?token={token}"
        background_tasks.add_task(
            _send_recovery_email, smtp, email, user_with_hash["username"], reset_url,
        )

    return templates.TemplateResponse(
        request, "account_recovery.html",
        {"submitted": True},
    )


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_form(request: Request):
    token = request.query_params.get("token", "").strip()
    with request.app.state.pool.connection() as conn:
        user = verify_reset_token(request.app.state.secret_key, token, conn) if token else None
    if user is None:
        return templates.TemplateResponse(
            request, "reset_password.html",
            {"error": "This link is invalid or has expired.", "show_recovery_link": True},
            status_code=400,
        )
    return templates.TemplateResponse(
        request, "reset_password.html",
        {"token": token, "username": user["username"]},
    )


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_password(request: Request):
    if not rate_limit(request, "reset-password", max_attempts=10, window_seconds=900):
        return templates.TemplateResponse(
            request, "reset_password.html",
            {"error": "Too many attempts. Please wait a few minutes and try again."},
            status_code=429,
        )

    form = dict((await request.form()).items())
    token = str(form.get("token") or "").strip()
    password = str(form.get("password") or "")
    password_confirm = str(form.get("password_confirm") or "")

    def _token_error() -> HTMLResponse:
        return templates.TemplateResponse(
            request, "reset_password.html",
            {"error": "This link is invalid or has expired.", "show_recovery_link": True},
            status_code=400,
        )

    def _form_error(msg: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "reset_password.html",
            {"error": msg, "token": token},
            status_code=400,
        )

    if not token:
        return _token_error()

    with request.app.state.pool.connection() as conn:
        user = verify_reset_token(request.app.state.secret_key, token, conn)
        if user is None:
            return _token_error()
        if len(password) < 8:
            return _form_error("Password must be at least 8 characters.")
        if password_too_long(password):
            return _form_error(_TOO_LONG)
        if password != password_confirm:
            return _form_error("Passwords do not match.")
        new_hash = await run_in_threadpool(hash_password, password)
        db.update_password(conn, user["id"], new_hash)

    request.session.clear()
    return flash_redirect("/login", "Password reset. Please sign in with your new password.")


@router.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    token = request.query_params.get("token", "").strip()
    if not token:
        return templates.TemplateResponse(
            request, "register.html",
            {"error": "A valid invite token is required to register."},
            status_code=400,
        )

    with request.app.state.pool.connection() as conn:
        invite = db.get_invite(conn, token)

    error = _validate_invite(invite)
    if error:
        return templates.TemplateResponse(
            request, "register.html", {"error": error}, status_code=400
        )

    return templates.TemplateResponse(
        request, "register.html", {"token": token, "email": invite["email"]}  # type: ignore[index]
    )


@router.post("/register")
async def register(request: Request):
    if not rate_limit(request, "register", max_attempts=10, window_seconds=3600):
        return templates.TemplateResponse(
            request, "register.html",
            {"error": "Too many attempts. Please wait and try again."}, status_code=429,
        )

    form = dict((await request.form()).items())
    token = str(form.get("token") or "").strip()
    username = str(form.get("username") or "").strip()
    password = str(form.get("password") or "")
    password_confirm = str(form.get("password_confirm") or "")

    def _error(msg: str):
        return templates.TemplateResponse(
            request, "register.html",
            {"error": msg, "token": token, "username": username},
            status_code=400,
        )

    if not token:
        return _error("Invalid or missing invite token.")

    with request.app.state.pool.connection() as conn:
        invite = db.get_invite(conn, token)

    err = _validate_invite(invite)
    if err:
        return _error(err)

    if not username:
        return _error("Username is required.")
    if len(username) < 3:
        return _error("Username must be at least 3 characters.")
    if not password:
        return _error("Password is required.")
    if len(password) < 8:
        return _error("Password must be at least 8 characters.")
    if password_too_long(password):
        return _error(_TOO_LONG)
    if password != password_confirm:
        return _error("Passwords do not match.")

    pw_hash = await run_in_threadpool(hash_password, password)

    with request.app.state.pool.connection() as conn:
        if db.get_user_by_username(conn, username):
            return _error("That username is already taken.")
        if db.get_user_by_email(conn, invite["email"]):  # type: ignore[index]
            return _error("An account with that email already exists.")

        user = db.create_user(conn, username, invite["email"], pw_hash)  # type: ignore[index]
        db.use_invite(conn, token)
        db._seed_settings(conn, user["id"], "", 587, "", "", "")
        user_with_hash = db.get_user_by_id_with_hash(conn, user["id"])
        if user_with_hash is not None:
            start_session(request, user_with_hash)

    return RedirectResponse(url="/", status_code=303)


def _send_recovery_email(smtp: dict, to: str, username: str, reset_url: str) -> None:
    """Runs after the response is sent: keeps SMTP off the event loop and makes
    known and unknown emails respond in the same time (audit M7)."""
    try:
        emailer.send_email(
            smtp_host=smtp["smtp_host"], smtp_port=smtp["smtp_port"], smtp_user=smtp["smtp_user"],
            smtp_password=os.environ.get("SMTP_PASSWORD", ""), email_from=smtp["email_from"],
            email_to=[to], subject="CareerSpyder account recovery",
            html_body=_recovery_email_html(username, reset_url),
        )
    except Exception:
        logger.exception("Failed to send recovery email to %s", to)


def _recovery_email_html(username: str, reset_url: str) -> str:
    u = _esc(username)
    r = _esc(reset_url)
    return (
        f"<p>Your username is: <strong>{u}</strong></p>"
        f"<p>To reset your password, click the link below. It expires in 1 hour.</p>"
        f'<p><a href="{r}">Reset my password</a></p>'
        f"<p>If you didn't request this, you can safely ignore this email.</p>"
    )


def _validate_invite(invite: dict | None) -> str | None:
    if invite is None:
        return "Invite token not found."
    if invite["used_at"] is not None:
        return "This invite link has already been used."
    try:
        expires = datetime.fromisoformat(invite["expires_at"])
        if expires < datetime.now(UTC):
            return "This invite link has expired."
    except (ValueError, AttributeError):
        return "Invite token is malformed."
    return None
