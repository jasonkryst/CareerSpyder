import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import db
from app.scheduler import create_scheduler
from app.web.routes_dashboard import router as dashboard_router
from app.web.routes_guide import router as guide_router
from app.web.routes_jobs import router as jobs_router
from app.web.routes_settings import router as settings_router
from app.web.routes_sources import router as sources_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("CAREERSPYDER_DB_PATH", "/app/data/state.db")
    sources_path = os.environ.get("CAREERSPYDER_SOURCES_PATH", "/app/config/sources.json")
    run_hour = int(os.environ.get("RUN_HOUR", "8"))
    tz = os.environ.get("TZ", "UTC")

    conn = db.init_db(db_path)
    db.seed_settings_if_empty(
        conn,
        os.environ.get("SMTP_HOST", ""),
        int(os.environ.get("SMTP_PORT", "587")),
        os.environ.get("SMTP_USER", ""),
        os.environ.get("EMAIL_FROM", ""),
        os.environ.get("EMAIL_TO", ""),
    )

    app.state.conn = conn
    app.state.sources_path = sources_path
    app.state.scheduler = create_scheduler(conn, sources_path, run_hour, tz)

    yield

    app.state.scheduler.shutdown()
    conn.close()


app = FastAPI(title="CareerSpyder", lifespan=lifespan)
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)
app.include_router(dashboard_router)
app.include_router(jobs_router)
app.include_router(sources_router)
app.include_router(settings_router)
app.include_router(guide_router)
