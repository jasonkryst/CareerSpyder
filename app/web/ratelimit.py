"""Simple in-memory per-IP sliding-window rate limiter.

Suitable for a single-process deployment. Limits reset on process restart
and do not share state across replicas, which is acceptable for a small
private instance.

Proxy trust: set TRUSTED_PROXIES env var to a comma-separated list of
trusted proxy IPs (e.g. "172.18.0.1,10.0.0.1"). Only when the immediate
peer matches a trusted proxy will X-Forwarded-For / X-Real-IP be honoured.
Without this env var the direct connection IP is always used, which is safe
for deployments where the app is exposed directly (no proxy in front).
"""

import os
import threading
from collections import defaultdict, deque
from time import monotonic

from fastapi import Request

_lock = threading.Lock()
_buckets: dict[str, deque[float]] = defaultdict(deque)

_TRUSTED_PROXIES: frozenset[str] = frozenset(
    addr.strip()
    for addr in os.environ.get("TRUSTED_PROXIES", "").split(",")
    if addr.strip()
)


def _client_ip(request: Request) -> str:
    direct = request.client.host if request.client else "unknown"
    if direct not in _TRUSTED_PROXIES:
        return direct
    # Behind a trusted proxy: take the rightmost IP in X-Forwarded-For
    # (the one appended by the trusted proxy — least spoofable).
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[-1].strip()
    xri = request.headers.get("X-Real-IP", "")
    if xri:
        return xri.strip()
    return direct


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


def clear() -> None:
    """Clear all rate-limit buckets. Call from test fixtures to isolate tests."""
    with _lock:
        _buckets.clear()
