from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db
from app.web.auth import hash_password, verify_password
from app.web.templating import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    next_url = request.query_params.get("next", "/")
    return templates.TemplateResponse(request, "login.html", {"next": next_url})


@router.post("/login")
async def login(request: Request):
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

    if user is None or not user["is_active"] or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Invalid username or password.", "next": next_url},
            status_code=401,
        )

    request.session["user_id"] = user["id"]

    # Reject anything with a scheme or host (catches //evil.com, http://…, etc.)
    parsed = urlparse(next_url)
    safe_next = next_url if (parsed.scheme == "" and parsed.netloc == "" and next_url.startswith("/")) else "/"
    return RedirectResponse(url=safe_next, status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


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
    if password != password_confirm:
        return _error("Passwords do not match.")

    with request.app.state.pool.connection() as conn:
        if db.get_user_by_username(conn, username):
            return _error("That username is already taken.")
        if db.get_user_by_email(conn, invite["email"]):  # type: ignore[index]
            return _error("An account with that email already exists.")

        user = db.create_user(conn, username, invite["email"], hash_password(password))  # type: ignore[index]
        db.use_invite(conn, token)
        db._seed_settings(conn, user["id"], "", 587, "", "", "")

    request.session["user_id"] = user["id"]
    return RedirectResponse(url="/", status_code=303)


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
