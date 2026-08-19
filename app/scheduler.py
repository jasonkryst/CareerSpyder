import logging
import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from app import config, db, digest, emailer, orchestrator

logger = logging.getLogger(__name__)

_DAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _resolve_tz(tz: str):
    # "UTC" is special-cased the same way apscheduler.util.astimezone does,
    # so this never requires the optional `tzdata` package to be installed.
    return UTC if tz == "UTC" else ZoneInfo(tz)


def _today_code(tz: str) -> str:
    return _DAY_CODES[datetime.now(_resolve_tz(tz)).weekday()]


def run_and_notify(conn, sources_path: str, tz: str = "UTC", force: bool = False) -> None:
    settings = db.get_settings(conn)
    if not force and settings is not None and _today_code(tz) not in (settings["email_days"] or "").split(","):
        return

    sources = config.load_sources(sources_path)
    summary = orchestrator.run_once(conn, sources)

    resend = bool(settings and settings["resend_jobs"])
    jobs_to_send = summary.found_jobs if resend else summary.new_jobs
    job_label = "job" if resend else "new job"

    statuses = db.get_job_statuses(conn, [j.key for j in jobs_to_send])
    public_base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    jobs_url = f"{public_base_url}/jobs" if public_base_url else None

    d = digest.build_digest(
        jobs_to_send, summary.failed_sources, job_label,
        statuses=statuses, searched_at=datetime.now(UTC), jobs_url=jobs_url,
    )
    if d is None:
        return

    if settings is None:
        logger.warning("Skipping digest email for run %s: no settings configured", summary.run_id)
        return

    email_to = [addr.strip() for addr in (settings["email_to"] or "").split(",") if addr.strip()]
    if not email_to:
        logger.warning("Skipping digest email for run %s: no recipients configured", summary.run_id)
        return

    try:
        emailer.send_email(
            settings["smtp_host"], settings["smtp_port"], settings["smtp_user"],
            os.environ.get("SMTP_PASSWORD", ""), settings["email_from"], email_to,
            d.subject, d.html_body,
        )
        db.mark_emailed(conn, [j.key for j in jobs_to_send])
    except Exception:
        logger.exception("Failed to send digest email for run %s", summary.run_id)


def create_scheduler(conn, sources_path: str, run_hour: int, tz: str) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=tz)
    sched.add_job(run_and_notify, "cron", hour=run_hour, args=[conn, sources_path, tz], id="daily_run")
    sched.start()
    return sched
