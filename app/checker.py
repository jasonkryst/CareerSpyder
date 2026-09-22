import logging
from collections.abc import Callable
from datetime import UTC, datetime

import psycopg
import requests

logger = logging.getLogger(__name__)

_REMOVED_STATUSES = frozenset({404, 410})


def check_job_urls(
    conn: psycopg.Connection,
    http_head: Callable = requests.head,
    user_id: str | None = None,
) -> int:
    """HEAD each active job URL and mark removed on 404/410. Returns count of newly removed jobs.

    Pass user_id to restrict checks to that user's jobs; None checks all (admin/scheduler use).
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

    removed_keys: list[str] = []
    for key, url in rows:
        try:
            resp = http_head(url, timeout=10, allow_redirects=True)
            if resp.status_code in _REMOVED_STATUSES:
                removed_keys.append(key)
                logger.info("Job %s marked removed: HTTP %s for %s", key, resp.status_code, url)
        except requests.exceptions.RequestException:
            logger.debug("URL check skipped for job %s (%s): request failed", key, url)

    if removed_keys:
        now = datetime.now(UTC).isoformat()
        placeholders = ",".join(["%s"] * len(removed_keys))
        conn.execute(
            f"UPDATE jobs SET removed_at = %s WHERE key IN ({placeholders})",  # noqa: S608
            [now, *removed_keys],
        )
        conn.commit()

    return len(removed_keys)
