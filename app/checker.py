import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime

import psycopg
import requests

logger = logging.getLogger(__name__)

_REMOVED_STATUSES = frozenset({404, 410})
_MAX_WORKERS = 8
# Overall budget for one check pass. This runs under orchestrator._run_lock,
# so a handful of dead hosts must not be able to block "Run now" for minutes.
_DEADLINE_S = 60.0


def check_job_urls(
    conn: psycopg.Connection,
    http_head: Callable = requests.head,
    user_id: str | None = None,
    max_workers: int = _MAX_WORKERS,
    deadline_s: float = _DEADLINE_S,
) -> int:
    """HEAD each active job URL and mark removed on 404/410. Returns count of newly removed jobs.

    Pass user_id to restrict checks to that user's jobs; None checks all (admin/scheduler use).
    HEADs run in a thread pool; URLs not answered within deadline_s are left
    untouched until the next pass. Only the calling thread touches `conn`.
    """
    if user_id is not None:
        rows = conn.execute(
            "SELECT key, url FROM jobs WHERE removed_at IS NULL AND user_id = %s",
            (user_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT key, url FROM jobs WHERE removed_at IS NULL"
        ).fetchall()

    def _is_removed(key: str, url: str) -> bool:
        try:
            resp = http_head(url, timeout=10, allow_redirects=True)
        except requests.exceptions.RequestException:
            logger.debug("URL check skipped for job %s (%s): request failed", key, url)
            return False
        if resp.status_code in _REMOVED_STATUSES:
            logger.info("Job %s marked removed: HTTP %s for %s", key, resp.status_code, url)
            return True
        return False

    removed_keys: list[str] = []
    if rows:
        executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="url-check")
        futures = {executor.submit(_is_removed, key, url): key for key, url in rows}
        done, not_done = wait(futures, timeout=deadline_s)
        # Don't block on stragglers: queued checks are cancelled, in-flight
        # ones finish on their own (bounded by the per-request timeout).
        executor.shutdown(wait=False, cancel_futures=True)
        removed_keys = [futures[f] for f in done if f.result()]
        if not_done:
            logger.warning(
                "URL check deadline (%.0fs) reached; %d of %d URLs left unchecked this pass",
                deadline_s, len(not_done), len(rows),
            )

    if removed_keys:
        now = datetime.now(UTC).isoformat()
        placeholders = ",".join(["%s"] * len(removed_keys))
        conn.execute(
            f"UPDATE jobs SET removed_at = %s WHERE key IN ({placeholders})",  # noqa: S608
            [now, *removed_keys],
        )
        conn.commit()

    return len(removed_keys)
