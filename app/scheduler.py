import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

from app import config, db, digest, emailer, orchestrator

logger = logging.getLogger(__name__)


def run_and_notify(conn, sources_path: str) -> None:
    sources = config.load_sources(sources_path)
    summary = orchestrator.run_once(conn, sources)
    d = digest.build_digest(summary.new_jobs, summary.failed_sources)
    if d is None:
        return
    settings = db.get_settings(conn)
    if settings is None:
        logger.warning("Skipping digest email for run %s: no settings configured", summary.run_id)
        return
    try:
        emailer.send_email(
            settings["smtp_host"], settings["smtp_port"], settings["smtp_user"],
            os.environ.get("SMTP_PASSWORD", ""), settings["email_from"], settings["email_to"],
            d.subject, d.html_body,
        )
    except Exception:
        logger.exception("Failed to send digest email for run %s", summary.run_id)


def create_scheduler(conn, sources_path: str, run_hour: int, tz: str) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=tz)
    sched.add_job(run_and_notify, "cron", hour=run_hour, args=[conn, sources_path], id="daily_run")
    sched.start()
    return sched
