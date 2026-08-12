import logging
import sqlite3
import threading
from dataclasses import dataclass

from app import db
from app.adapters import ADAPTERS
from app.config import SourceConfig
from app.filters import apply_keyword_filters
from app.models import Job

logger = logging.getLogger(__name__)

# Serializes overlapping runs (e.g. a "Run now" click racing the daily cron,
# or two "Run now" clicks) so the get-new-jobs -> save-jobs sequence against
# the shared SQLite connection can never race and double-report new jobs.
_run_lock = threading.Lock()


@dataclass
class RunSummary:
    run_id: int
    new_jobs: list[Job]
    failed_sources: list[str]


def run_once(conn: sqlite3.Connection, sources: list[SourceConfig]) -> RunSummary:
    with _run_lock:
        run_id = db.start_run(conn)
        all_jobs: list[Job] = []
        failed_sources: list[str] = []

        for source in sources:
            try:
                adapter = ADAPTERS[source.type]
                found = adapter(source)
            except Exception:
                logger.exception("Source %r failed", source.name)
                failed_sources.append(source.name)
                continue
            all_jobs.extend(apply_keyword_filters(found, source.include_keywords, source.exclude_keywords))

        deduped_jobs = list({j.key: j for j in all_jobs}.values())

        new_jobs = db.get_new_jobs(conn, deduped_jobs)
        db.save_jobs(conn, new_jobs, run_id)
        db.finish_run(conn, run_id, len(new_jobs), failed_sources)
        return RunSummary(run_id=run_id, new_jobs=new_jobs, failed_sources=failed_sources)
