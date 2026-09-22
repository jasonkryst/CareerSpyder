import logging
import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from psycopg_pool import ConnectionPool

from app import db, digest, emailer, orchestrator

logger = logging.getLogger(__name__)

_DAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _resolve_tz(tz: str):
    # "UTC" is special-cased the same way apscheduler.util.astimezone does,
    # so this never requires the optional `tzdata` package to be installed.
    return UTC if tz == "UTC" else ZoneInfo(tz)


def _today_code(tz: str) -> str:
    return _DAY_CODES[datetime.now(_resolve_tz(tz)).weekday()]


def _run_user(conn, user_id: str, sources: list, tz: str, force: bool) -> None:
    settings = db.get_settings(conn, user_id)
    if not force and settings is not None and _today_code(tz) not in (settings["email_days"] or "").split(","):
        return

    summary = orchestrator.run_once(conn, sources, user_id=user_id)

    resend = bool(settings and settings["resend_jobs"])
    jobs_to_send = list(summary.found_jobs if resend else summary.new_jobs)
    job_label = "job" if resend else "new job"

    # Rescue jobs saved in a prior run but never emailed because the process
    # crashed between save_jobs committing and mark_emailed running.
    current_keys = {j.key for j in jobs_to_send}
    for rescued in db.get_unemailed_jobs(conn, user_id=user_id):
        if rescued.key not in current_keys:
            jobs_to_send.append(rescued)
            current_keys.add(rescued.key)

    duplicate_keys = {
        row["key"] for row in db.list_jobs(conn, limit=10_000, duplicates="only")
    }
    jobs_to_send = [j for j in jobs_to_send if j.key not in duplicate_keys]

    secondary_source_ids = {s.id for s in sources if s.secondary}
    statuses = db.get_job_statuses(conn, [j.key for j in jobs_to_send])

    exclude_statuses = {
        s for s in ((settings or {}).get("digest_exclude_statuses") or "").split(",") if s
    }
    if exclude_statuses:
        jobs_to_send = [j for j in jobs_to_send if statuses.get(j.key) not in exclude_statuses]

    public_base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    jobs_url = f"{public_base_url}/jobs" if public_base_url else None

    # When resend is on, the email includes both new and re-seen jobs; split them
    # into "Newly identified" / "Already identified" sections per company.
    emailed_keys = db.get_emailed_keys(conn, [j.key for j in jobs_to_send]) if resend else None

    d = digest.build_digest(
        jobs_to_send, summary.failed_sources, job_label,
        statuses=statuses, searched_at=datetime.now(UTC), jobs_url=jobs_url,
        secondary_source_ids=secondary_source_ids,
        emailed_keys=emailed_keys,
        max_per_company=(settings or {}).get("digest_max_per_company", 0),
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

    smtp = db.get_admin_smtp_settings(conn)
    if not smtp or not smtp.get("smtp_host"):
        logger.warning("Skipping digest email for run %s: SMTP host not configured — set it at /settings/email", summary.run_id)
        return

    try:
        emailer.send_email(
            smtp["smtp_host"], smtp["smtp_port"], smtp["smtp_user"],
            os.environ.get("SMTP_PASSWORD", ""), smtp["email_from"], email_to,
            d.subject, d.html_body,
        )
        db.mark_emailed(conn, [j.key for j in jobs_to_send])
    except Exception:
        logger.exception("Failed to send digest email for run %s", summary.run_id)


def run_and_notify(pool: ConnectionPool, tz: str = "UTC", force: bool = False) -> None:
    with pool.connection() as conn:
        sources_by_user = db.list_all_sources_by_user(conn)
        if not sources_by_user:
            orchestrator.run_once(conn, [])
            return
        for user_id, sources in sources_by_user.items():
            try:
                _run_user(conn, user_id, sources, tz, force)
            except Exception:
                logger.exception("Failed run for user %s", user_id)


def create_scheduler(pool: ConnectionPool, run_cron: str, tz: str) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=tz)
    trigger = CronTrigger.from_crontab(run_cron, timezone=_resolve_tz(tz))
    sched.add_job(run_and_notify, trigger, args=[pool, tz], id="daily_run")
    sched.start()
    return sched
