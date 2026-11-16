"""Simple in-memory per-IP sliding-window rate limiter.

Suitable for a single-process deployment. Limits reset on process restart
and do not share state across replicas, which is acceptable for a small
private instance.

Proxy trust: set the TRUSTED_PROXIES env var to a comma-separated list of
proxy IPs and/or CIDR ranges (e.g. "172.16.0.0/12" for any Docker bridge
network, or "172.18.0.1,203.0.113.0/24"). Forwarded headers are honoured
only when the direct peer is trusted. X-Forwarded-For is then walked from
the right, skipping every trusted entry, and the first untrusted address is
the client. That handles one proxy (NPM) and a chain (Cloudflare → NPM)
alike, as long as every proxy in the chain is listed.

Without this env var the direct connection IP is always used. That's safe
for a directly exposed app, but behind a proxy every visitor then shares one
bucket. The first time X-Forwarded-For arrives from an untrusted peer, a
one-time warning is logged that names the peer, so it's easy to see what to
add.
"""

import ipaddress
import logging
import math
import os
import threading
from collections import defaultdict, deque
from time import monotonic

from fastapi import Request

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_buckets: dict[str, deque[float]] = defaultdict(deque)

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_trusted_proxies(raw: str) -> tuple[_Network, ...]:
    """Parse a comma-separated list of IPs/CIDRs. Invalid entries are logged
    and skipped, so one typo can't stop the app from starting."""
    networks: list[_Network] = []
    entries = [e.strip() for e in raw.split(",") if e.strip()]
    for position, entry in enumerate(entries, start=1):
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            # Report where, not what: the value comes from the environment and
            # isn't echoed into logs (CodeQL #21).
            logger.warning(
                "TRUSTED_PROXIES: ignoring entry %d of %d, which is not an IP "
                "address or CIDR range", position, len(entries),
            )
    return tuple(networks)


_TRUSTED_PROXIES: tuple[_Network, ...] = parse_trusted_proxies(
    os.environ.get("TRUSTED_PROXIES", "")
)
_warned_untrusted_xff = False


def _is_trusted(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.strip())
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in net for net in _TRUSTED_PROXIES)


def _warn_untrusted_xff(peer: str) -> None:
    global _warned_untrusted_xff
    if _warned_untrusted_xff:
        return
    _warned_untrusted_xff = True
    logger.warning(
        "X-Forwarded-For received from %s, which is not in TRUSTED_PROXIES; "
        "ignoring it and rate-limiting by the peer address. If this app is "
        "behind a reverse proxy, every visitor now shares one login limit. "
        "Add the proxy's IP or network (e.g. 172.16.0.0/12 for a Docker "
        "network) to TRUSTED_PROXIES.",
        peer,
    )


def _client_ip(request: Request) -> str:
    direct = request.client.host if request.client else "unknown"
    xff = request.headers.get("X-Forwarded-For", "")
    if not _is_trusted(direct):
        if xff:
            _warn_untrusted_xff(direct)
        return direct
    if xff:
        # Proxies append on the right, so walk right-to-left past our own
        # proxies; the first address nobody we trust vouches for is the
        # client. Anything further left was supplied by that client and can
        # be forged.
        hops = [h.strip() for h in xff.split(",") if h.strip()]
        for hop in reversed(hops):
            if not _is_trusted(hop):
                return hop
        # Every hop is a trusted proxy: the left-most is the closest we have.
        if hops:
            return hops[0]
    xri = request.headers.get("X-Real-IP", "")
    if xri:
        return xri.strip()
    return direct


def hit(key: str, max_attempts: int, window_seconds: int) -> int:
    """Record an attempt. Return 0 if allowed, else whole seconds (≥1) until
    the oldest attempt in the window expires and one more is allowed.

    Timestamps use the monotonic clock so they are immune to clock changes.
    """
    now = monotonic()
    cutoff = now - window_seconds
    with _lock:
        dq = _buckets[key]
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= max_attempts:
            return max(1, math.ceil(dq[0] + window_seconds - now))
        dq.append(now)
        return 0


def check(key: str, max_attempts: int, window_seconds: int) -> bool:
    """Return True (allowed) or False (rate-limited).

    key should be unique per endpoint + client, e.g. f"login:{ip}".
    """
    return hit(key, max_attempts, window_seconds) == 0


def retry_after(request: Request, endpoint: str, max_attempts: int, window_seconds: int) -> int:
    """Like rate_limit, but return 0 if allowed or the seconds to wait."""
    ip = _client_ip(request)
    wait = hit(f"{endpoint}:{ip}", max_attempts, window_seconds)
    if wait:
        logger.info("Rate limit reached for %s from %s; retry in %ss", endpoint, ip, wait)
    return wait


def rate_limit(request: Request, endpoint: str, max_attempts: int, window_seconds: int) -> bool:
    """Convenience wrapper: build key from endpoint + client IP, return allowed."""
    return retry_after(request, endpoint, max_attempts, window_seconds) == 0


def wait_message(seconds: int) -> str:
    """Human wording for a Retry-After value, rounded up to whole minutes."""
    minutes = max(1, math.ceil(seconds / 60))
    return f"Try again in {minutes} minute{'s' if minutes != 1 else ''}."


def clear() -> None:
    """Clear all rate-limit buckets. Call from test fixtures to isolate tests."""
    global _warned_untrusted_xff
    with _lock:
        _buckets.clear()
        _warned_untrusted_xff = False
