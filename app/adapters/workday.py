import logging
import time
from collections.abc import Callable
from urllib.parse import urlparse

from app.config import WorkdaySource
from app.models import Job
from app.security.ssrf_guard import safe_post

logger = logging.getLogger(__name__)

_PAGE_SIZE = 20

# Workday throttles per client IP across a whole wdN cluster (HTTP 429), so an
# unpaced crawl of one large tenant can also starve the next Workday source.
# Pause between pages, and retry a throttled page instead of failing the run.
_PAGE_DELAY_S = 1.0
_RETRY_STATUSES = frozenset({429, 503})
_MAX_RETRIES = 3
_BACKOFF_BASE_S = 5.0
_MAX_RETRY_WAIT_S = 60.0

# Resolved at call time (not bound as a default arg) so tests can patch it.
_sleep: Callable[[float], None] = time.sleep


def _retry_wait(resp, attempt: int) -> float:
    """Seconds to wait before retry `attempt` (0-based): the server's numeric
    Retry-After if it sent one, else exponential backoff -- capped either way."""
    retry_after = (getattr(resp, "headers", None) or {}).get("Retry-After")
    try:
        wait = float(retry_after) if retry_after is not None else _BACKOFF_BASE_S * 2 ** attempt
    except ValueError:  # HTTP-date form; not worth parsing for a capped wait
        wait = _BACKOFF_BASE_S * 2 ** attempt
    return min(max(wait, 0.0), _MAX_RETRY_WAIT_S)


def _resolve(career_site_url: str) -> tuple[str, str]:
    """Returns (api_url, site_base), both derived from the career site URL.

    site_base is `{origin}/{site}`: Workday's `externalPath` is relative to
    the career site, so `{origin}{externalPath}` 404s (issue #175)."""
    parsed = urlparse(career_site_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    tenant = parsed.netloc.split(".")[0]
    site = parsed.path.strip("/").split("/")[-1]
    return f"{origin}/wday/cxs/{tenant}/{site}/jobs", f"{origin}/{site}"


def _parse_postings(postings: list[dict], source: WorkdaySource, site_base: str) -> list[Job]:
    jobs = []
    for posting in postings:
        try:
            bullet_fields = posting.get("bulletFields") or []
            external_path = posting.get("externalPath", "")
            requisition_id = bullet_fields[1] if len(bullet_fields) > 1 else external_path
            jobs.append(Job(
                key=f"workday:{requisition_id}",
                title=posting["title"],
                url=f"{site_base}{external_path}",
                company=source.company,
                location=posting.get("locationsText"),
                posted_date=posting.get("postedOn"),
                source_name=source.name,
                source_id=source.id,
            ))
        except (KeyError, TypeError, AttributeError):
            logger.warning("workday: skipping malformed record from %s: %r", source.name, posting)
    return jobs


def fetch(
    source: WorkdaySource, http_post=safe_post, sleep: Callable[[float], None] | None = None,
) -> list[Job]:
    api_url, site_base = _resolve(source.career_site_url)
    pause = sleep or _sleep

    def fetch_page(offset: int):
        # A page still throttled after _MAX_RETRIES raises, failing the whole
        # source: returning the pages fetched so far would let reconcile_jobs
        # mark every job on the missing pages as removed.
        for attempt in range(_MAX_RETRIES + 1):
            resp = http_post(
                api_url,
                json={"appliedFacets": {}, "limit": _PAGE_SIZE, "offset": offset, "searchText": ""},
                timeout=15,
            )
            if resp.status_code not in _RETRY_STATUSES or attempt == _MAX_RETRIES:
                break
            wait = _retry_wait(resp, attempt)
            logger.info(
                "workday: %s throttled (HTTP %s) at offset %d; retrying in %.0fs",
                source.name, resp.status_code, offset, wait,
            )
            pause(wait)
        resp.raise_for_status()
        return resp.json()

    first_page = fetch_page(0)
    total = first_page.get("total", 0)
    all_jobs = _parse_postings(first_page.get("jobPostings", []), source, site_base)

    # `total` is only trustworthy on this first response -- every later
    # response reports 0 regardless of how many real results remain, and
    # requesting an offset at/past this frozen total wraps back around to
    # page 1's content instead of returning empty. Both verified directly
    # against a real Workday site -- never re-derive the bound mid-loop.
    max_offset = min(total, source.max_pages * _PAGE_SIZE)

    offset = _PAGE_SIZE
    while offset < max_offset:
        pause(_PAGE_DELAY_S)
        page = fetch_page(offset)
        all_jobs.extend(_parse_postings(page.get("jobPostings", []), source, site_base))
        offset += _PAGE_SIZE

    return all_jobs
