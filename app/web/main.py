import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool
from starlette.middleware.sessions import SessionMiddleware

from app import db
from app.scheduler import create_scheduler
from app.web.auth import UserContextMiddleware, hash_password
from app.web.csrf_protection import OriginCheckMiddleware
from app.web.routes_auth import router as auth_router
from app.web.routes_dashboard import router as dashboard_router
from app.web.routes_guide import router as guide_router
from app.web.routes_jobs import router as jobs_router
from app.web.routes_pwa import router as pwa_router
from app.web.routes_settings import router as settings_router
from app.web.routes_sources import router as sources_router
from app.web.routes_users import router as users_router
from app.web.security_headers import SecurityHeadersMiddleware

logger = logging.getLogger(__name__)


def _resolve_secret_key() -> str:
    key = os.environ.get("SECRET_KEY", "")
    if not key:
        key = "dev-insecure-secret-change-me"
        logger.warning(
            "SECRET_KEY is not set — using an insecure dev default. "
            "Set SECRET_KEY in production."
        )
    return key


def _resolve_admin_password_hash() -> str | None:
    """Return a bcrypt hash for the initial admin, or None if not configured."""
    hashed = os.environ.get("ADMIN_PASSWORD_HASH", "")
    if hashed:
        return hashed
    plaintext = os.environ.get("ADMIN_PASSWORD", "")
    if plaintext:
        return hash_password(plaintext)
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    dsn = os.environ.get("DATABASE_URL", "postgresql://careerspyder:dev@localhost:5432/careerspyder")
    run_cron = os.environ.get("RUN_CRON", "0 7 * * *")
    tz = os.environ.get("TZ", "UTC")

    pool: ConnectionPool = db.init_db(dsn)

    admin_username = os.environ.get("ADMIN_USERNAME", "")
    admin_email = os.environ.get("ADMIN_EMAIL", f"{admin_username}@localhost")
    admin_password_hash = _resolve_admin_password_hash()

    with pool.connection() as conn:
        if admin_username and admin_password_hash:
            db.seed_admin_if_empty(
                conn,
                admin_username,
                admin_email,
                admin_password_hash,
                smtp_host=os.environ.get("SMTP_HOST", ""),
                smtp_port=int(os.environ.get("SMTP_PORT", "587")),
                smtp_user=os.environ.get("SMTP_USER", ""),
                email_from=os.environ.get("EMAIL_FROM", ""),
                email_to=os.environ.get("EMAIL_TO", ""),
            )
        elif not admin_username:
            logger.warning(
                "ADMIN_USERNAME is not set — no admin user will be created. "
                "Set ADMIN_USERNAME and ADMIN_PASSWORD (or ADMIN_PASSWORD_HASH)."
            )

    app.state.pool = pool
    app.state.tz = tz
    app.state.scheduler = create_scheduler(pool, run_cron, tz)

    yield

    if app.state.scheduler.running:
        app.state.scheduler.shutdown(wait=False)
    pool.close()


app = FastAPI(title="CareerSpyder", lifespan=lifespan)

# Middleware registration order: Starlette wraps in reverse-add order so the
# last-added middleware becomes the outermost (first to run on request).
# Desired dispatch order: SecurityHeaders → OriginCheck → Session → UserContext → route.
# Register SecurityHeaders last (outermost), UserContext first (innermost, runs after Session).
app.add_middleware(UserContextMiddleware)
app.add_middleware(SessionMiddleware, secret_key=_resolve_secret_key(),
                   max_age=7 * 24 * 3600)
app.add_middleware(OriginCheckMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(jobs_router)
app.include_router(sources_router)
app.include_router(settings_router)
app.include_router(guide_router)
app.include_router(users_router)
app.include_router(pwa_router)


@app.exception_handler(401)
async def _auth_redirect(_: Request, __: Exception) -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)
