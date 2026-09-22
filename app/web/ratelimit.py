"""Simple in-memory per-IP sliding-window rate limiter.

Suitable for a single-process deployment. Limits reset on process restart
and do not share state across replicas, which is acceptable for a small
private instance.
"""

import threading
from collections import defaultdict, deque
from time import monotonic

from fastapi import Request

_lock = threading.Lock()
_buckets: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    xri = request.headers.get("X-Real-IP", "")
    if xri:
        return xri.strip()
    return request.client.host if request.client else "unknown"


def check(key: str, max_attempts: int, window_seconds: int) -> bool:
    """Return True (allowed) or False (rate-limited).

    key should be unique per endpoint + client, e.g. f"login:{ip}".
    Timestamps use monotonic clock so they are immune to clock adjustments.
    """
    now = monotonic()
    cutoff = now - window_seconds
    with _lock:
        dq = _buckets[key]
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= max_attempts:
            return False
        dq.append(now)
        return True


def rate_limit(request: Request, endpoint: str, max_attempts: int, window_seconds: int) -> bool:
    """Convenience wrapper: build key from endpoint + client IP, return allowed."""
    ip = _client_ip(request)
    return check(f"{endpoint}:{ip}", max_attempts, window_seconds)
