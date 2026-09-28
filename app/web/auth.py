"""Session helpers, FastAPI dependencies, and password utilities for auth."""
import hashlib
import logging

import bcrypt as _bcrypt
import psycopg
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadData, URLSafeTimedSerializer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from app import db

logger = logging.getLogger(__name__)


def hash_password(plaintext: str) -> str:
    return _bcrypt.hashpw(plaintext.encode(), _bcrypt.gensalt()).decode()


def verify_password(plaintext: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plaintext.encode(), hashed.encode())


def password_fingerprint(pw_hash: str) -> str:
    """Short digest of the stored hash. Kept in the session so any password
    change or reset invalidates every other session (audit M5)."""
    return hashlib.sha256(pw_hash.encode()).hexdigest()[:16]


def start_session(request: Request, user_with_hash: dict) -> None:
    request.session["user_id"] = user_with_hash["id"]
    request.session["pw_fp"] = password_fingerprint(user_with_hash["password_hash"])


def load_session_user(request: Request) -> dict | None:
    """The session's user (without password_hash), or None -- clearing the
    session if the user is gone, deactivated, or changed password since."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with request.app.state.pool.connection() as conn:
        user = db.get_user_by_id_with_hash(conn, user_id)
    if (
        user is None or not user["is_active"]
        or request.session.get("pw_fp") != password_fingerprint(user["password_hash"])
    ):
        request.session.clear()
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}


def get_current_user(request: Request) -> dict | None:
    """Returns the session user dict, or None if the session has no valid user."""
    return load_session_user(request)


def require_user(user: dict | None = Depends(get_current_user)) -> dict:
    """FastAPI dependency: raises 401 if not authenticated."""
    if user is None:
        raise HTTPException(status_code=401)
    return user


def require_admin(user: dict = Depends(require_user)) -> dict:
    """FastAPI dependency: raises 403 if the user is not an admin."""
    if user["role"] != "admin":
        raise HTTPException(status_code=403)
    return user


class UserContextMiddleware(BaseHTTPMiddleware):
    """Sets request.state.user from the session on every non-static request.

    This makes the current user available in Jinja2 templates via
    `request.state.user` without passing it to every TemplateResponse.
    Must be registered after SessionMiddleware so the session is already
    populated when this middleware runs.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not request.url.path.startswith("/static"):
            try:
                request.state.user = load_session_user(request)
            except Exception:
                logger.exception("UserContextMiddleware: failed to load session user")
                request.state.user = None
        return await call_next(request)


_RESET_SALT = "password-reset"


def generate_reset_token(secret_key: str, user_id: str, email: str, pw_hash: str) -> str:
    s = URLSafeTimedSerializer(secret_key)
    pw_fp = hashlib.sha256(pw_hash.encode()).hexdigest()[:8]
    return s.dumps({"user_id": user_id, "email": email, "pw_fp": pw_fp}, salt=_RESET_SALT)


def verify_reset_token(
    secret_key: str, token: str, conn: psycopg.Connection, max_age: int = 3600,
) -> dict | None:
    s = URLSafeTimedSerializer(secret_key)
    try:
        payload = s.loads(token, salt=_RESET_SALT, max_age=max_age)
    except BadData:
        return None
    user = db.get_user_by_id_with_hash(conn, payload["user_id"])
    if user is None or not user["is_active"]:
        return None
    expected_fp = hashlib.sha256(user["password_hash"].encode()).hexdigest()[:8]
    if payload.get("pw_fp") != expected_fp:
        return None
    return user
