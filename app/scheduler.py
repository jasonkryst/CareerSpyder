import os

from apscheduler.schedulers.background import BackgroundScheduler

from app import config, db, digest, emailer, orchestrator


def run_and_notify(conn, sources_path: str) -> None:
    sources = config.load_sources(sources_path)
    summary = orchestrator.run_once(conn, sources)
    d = digest.build_digest(summary.new_jobs, summary.failed_sources)
    if d is None:
        return
    settings = db.get_settings(conn)
    emailer.send_email(
        settings["smtp_host"], settings["smtp_port"], settings["smtp_user"],
        os.environ["SMTP_PASSWORD"], settings["email_from"], settings["email_to"],
        d.subject, d.html_body,
    )


def create_scheduler(conn, sources_path: str, run_hour: int, tz: str) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=tz)
    sched.add_job(run_and_notify, "cron", hour=run_hour, args=[conn, sources_path], id="daily_run")
    sched.start()
    return sched
