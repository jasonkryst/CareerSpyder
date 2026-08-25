import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

import requests

logger = logging.getLogger(__name__)

_REMOVED_STATUSES = frozenset({404, 410})


def check_job_urls(
    conn: sqlite3.Connection,
    http_head: Callable = requests.head,
) -> int:
    """HEAD each active job URL and mark removed on 404/410. Returns count of newly removed jobs."""
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
        placeholders = ",".join("?" * len(removed_keys))
        conn.execute(
            f"UPDATE jobs SET removed_at = ? WHERE key IN ({placeholders})",  # noqa: S608
            [now, *removed_keys],
        )
        conn.commit()

    return len(removed_keys)
