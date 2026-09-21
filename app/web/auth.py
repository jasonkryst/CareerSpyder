"""Session helpers, FastAPI dependencies, and password utilities for auth."""
import logging

import bcrypt as _bcrypt
from fastapi import Depends, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from app import db

logger = logging.getLogger(__name__)


def hash_password(plaintext: str) -> str:
    return _bcrypt.hashpw(plaintext.encode(), _bcrypt.gensalt()).decode()


def verify_password(plaintext: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plaintext.encode(), hashed.encode())


def get_current_user(request: Request) -> dict | None:
    """Returns the session user dict, or None if the session has no valid user."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with request.app.state.pool.connection() as conn:
        user = db.get_user_by_id(conn, user_id)
    if user is None or not user["is_active"]:
        request.session.clear()
        return None
    return user


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
            user_id = request.session.get("user_id")
            if user_id:
                try:
                    with request.app.state.pool.connection() as conn:
                        user = db.get_user_by_id(conn, user_id)
                    if user and user["is_active"]:
                        request.state.user = user
                    else:
                        request.session.clear()
                        request.state.user = None
                except Exception:
                    logger.exception("UserContextMiddleware: failed to load user %s", user_id)
                    request.state.user = None
            else:
                request.state.user = None
        return await call_next(request)
