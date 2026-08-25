import logging
import sqlite3
import threading
from dataclasses import dataclass

from app import checker, db
from app.adapters import ADAPTERS
from app.config import SourceConfig, get_source_url
from app.filters import apply_keyword_filters
from app.geocoding.base import Geocoder
from app.geocoding.factory import get_geocoder
from app.geocoding.service import geocode_pending
from app.models import FailedSource, Job

logger = logging.getLogger(__name__)

# Serializes overlapping runs (e.g. a "Run now" click racing the daily cron,
# or two "Run now" clicks) so the get-new-jobs -> save-jobs sequence against
# the shared SQLite connection can never race and double-report new jobs.
_run_lock = threading.Lock()


@dataclass
class RunSummary:
    run_id: int
    new_jobs: list[Job]
    found_jobs: list[Job]
    failed_sources: list[FailedSource]
    url_removed_count: int = 0


def run_once(conn: sqlite3.Connection, sources: list[SourceConfig], geocoder: Geocoder | None = None) -> RunSummary:
    with _run_lock:
        run_id = db.start_run(conn)
        all_jobs: list[Job] = []
        all_raw_jobs: list[Job] = []
        succeeded_source_ids: set[str] = set()
        failed_sources: list[FailedSource] = []

        for source in sources:
            try:
                adapter = ADAPTERS[source.type]
                found = adapter(source)
            except Exception:
                logger.exception("Source %r failed", source.name)
                failed_sources.append(FailedSource(name=source.name, url=get_source_url(source)))
                continue
            succeeded_source_ids.add(source.id)
            all_raw_jobs.extend(found)
            all_jobs.extend(apply_keyword_filters(found, source.include_keywords, source.exclude_keywords))

        deduped_jobs = list({j.key: j for j in all_jobs}.values())
        deduped_raw_jobs = list({j.key: j for j in all_raw_jobs}.values())

        new_jobs = db.get_new_jobs(conn, deduped_jobs)
        db.save_jobs(conn, new_jobs, run_id)

        configured_source_ids = {s.id for s in sources}
        db.reconcile_jobs(conn, configured_source_ids, succeeded_source_ids, deduped_raw_jobs)

        try:
            geocode_pending(conn, geocoder or get_geocoder())
        except Exception:
            logger.exception("Geocoding step failed for run %s", run_id)

        try:
            url_removed_count = checker.check_job_urls(conn)
        except Exception:
            logger.exception("URL check step failed for run %s", run_id)
            url_removed_count = 0

        db.finish_run(conn, run_id, len(new_jobs), failed_sources)
        return RunSummary(
            run_id=run_id, new_jobs=new_jobs, found_jobs=deduped_jobs,
            failed_sources=failed_sources, url_removed_count=url_removed_count,
        )
