"""Tests for the in-memory sliding-window rate limiter (app/web/ratelimit.py).

Covers:
- Basic allow / block behaviour
- Sliding-window expiry
- TRUSTED_PROXIES env-var gating for X-Forwarded-For / X-Real-IP
- clear() isolation helper used by test fixtures
"""

from unittest.mock import MagicMock

import pytest

from app.web import ratelimit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_request(host: str, xff: str = "", xri: str = "") -> MagicMock:
    """Build a minimal fake FastAPI Request for ratelimit._client_ip."""
    req = MagicMock()
    req.client.host = host
    req.headers = {}
    if xff:
        req.headers["X-Forwarded-For"] = xff
    if xri:
        req.headers["X-Real-IP"] = xri
    # Make .get() work like a dict
    req.headers = MagicMock()
    req.headers.get = lambda k, default="": {
        "X-Forwarded-For": xff,
        "X-Real-IP": xri,
    }.get(k, default)
    return req


# ---------------------------------------------------------------------------
# check() — core sliding-window logic
# ---------------------------------------------------------------------------


def test_check_allows_within_limit():
    ratelimit.clear()
    for _ in range(3):
        assert ratelimit.check("test:127.0.0.1", max_attempts=3, window_seconds=60) is True


def test_check_blocks_at_limit():
    ratelimit.clear()
    for _ in range(3):
        ratelimit.check("test:127.0.0.1", max_attempts=3, window_seconds=60)
    assert ratelimit.check("test:127.0.0.1", max_attempts=3, window_seconds=60) is False


def test_check_uses_separate_buckets_per_key():
    ratelimit.clear()
    for _ in range(3):
        ratelimit.check("endpoint_a:1.2.3.4", max_attempts=3, window_seconds=60)
    # Same IP but different endpoint key — separate bucket
    assert ratelimit.check("endpoint_b:1.2.3.4", max_attempts=3, window_seconds=60) is True


def test_check_expired_entries_slide_out():
    """Entries older than window_seconds should not count toward the limit."""
    ratelimit.clear()
    # Fill the bucket once
    for _ in range(3):
        ratelimit.check("test:2.2.2.2", max_attempts=3, window_seconds=60)
    # Use a window of 0 seconds: all previous entries are already outside it
    # so the next call should be allowed, re-counting from zero.
    assert ratelimit.check("test:2.2.2.2", max_attempts=3, window_seconds=0) is True


# ---------------------------------------------------------------------------
# _client_ip() — proxy header trust
# ---------------------------------------------------------------------------


def test_client_ip_direct_no_proxy(monkeypatch):
    """Without TRUSTED_PROXIES the direct peer IP is always used."""
    monkeypatch.setattr(ratelimit, "_TRUSTED_PROXIES", ratelimit.parse_trusted_proxies(""))
    req = _mock_request("1.2.3.4", xff="9.9.9.9")
    assert ratelimit._client_ip(req) == "1.2.3.4"


def test_client_ip_trusted_proxy_uses_xff(monkeypatch):
    """When the direct peer IS a trusted proxy, use X-Forwarded-For."""
    monkeypatch.setattr(ratelimit, "_TRUSTED_PROXIES", ratelimit.parse_trusted_proxies("10.0.0.1"))
    req = _mock_request("10.0.0.1", xff="203.0.113.5, 10.0.0.1")
    # The right-most entry is the trusted proxy itself, so it is skipped and
    # the next untrusted address to its left is the client.
    assert ratelimit._client_ip(req) == "203.0.113.5"


def test_client_ip_trusted_proxy_single_xff_entry(monkeypatch):
    """Single XFF entry: that entry is the real client IP."""
    monkeypatch.setattr(ratelimit, "_TRUSTED_PROXIES", ratelimit.parse_trusted_proxies("172.18.0.1"))
    req = _mock_request("172.18.0.1", xff="203.0.113.99")
    assert ratelimit._client_ip(req) == "203.0.113.99"


def test_client_ip_trusted_proxy_falls_back_to_xri(monkeypatch):
    """No XFF but X-Real-IP present and peer is trusted — use X-Real-IP."""
    monkeypatch.setattr(ratelimit, "_TRUSTED_PROXIES", ratelimit.parse_trusted_proxies("10.0.0.1"))
    req = _mock_request("10.0.0.1", xri="203.0.113.7")
    assert ratelimit._client_ip(req) == "203.0.113.7"


def test_client_ip_untrusted_proxy_ignores_xff(monkeypatch):
    """Peer not in TRUSTED_PROXIES — XFF is ignored even if present."""
    monkeypatch.setattr(ratelimit, "_TRUSTED_PROXIES", ratelimit.parse_trusted_proxies("10.0.0.1"))
    req = _mock_request("5.5.5.5", xff="1.1.1.1")
    assert ratelimit._client_ip(req) == "5.5.5.5"


def test_client_ip_trusted_proxy_no_headers_falls_back_to_direct(monkeypatch):
    """Trusted peer but no XFF/X-Real-IP — fall back to the direct peer."""
    monkeypatch.setattr(ratelimit, "_TRUSTED_PROXIES", ratelimit.parse_trusted_proxies("10.0.0.1"))
    req = _mock_request("10.0.0.1")
    assert ratelimit._client_ip(req) == "10.0.0.1"


# ---------------------------------------------------------------------------
# rate_limit() integration
# ---------------------------------------------------------------------------


def test_rate_limit_blocks_after_max_attempts(monkeypatch):
    ratelimit.clear()
    monkeypatch.setattr(ratelimit, "_TRUSTED_PROXIES", ratelimit.parse_trusted_proxies(""))
    req = _mock_request("8.8.8.8")
    for _ in range(5):
        ratelimit.rate_limit(req, "login", max_attempts=5, window_seconds=900)
    assert ratelimit.rate_limit(req, "login", max_attempts=5, window_seconds=900) is False


def test_rate_limit_different_ips_independent(monkeypatch):
    ratelimit.clear()
    monkeypatch.setattr(ratelimit, "_TRUSTED_PROXIES", ratelimit.parse_trusted_proxies(""))
    req_a = _mock_request("1.1.1.1")
    req_b = _mock_request("2.2.2.2")
    for _ in range(5):
        ratelimit.rate_limit(req_a, "login", max_attempts=5, window_seconds=900)
    # IP b should still be allowed
    assert ratelimit.rate_limit(req_b, "login", max_attempts=5, window_seconds=900) is True


# ---------------------------------------------------------------------------
# #291: CIDR trust, right-walk over chains, spoofing, warnings, Retry-After
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _ratelimit_logger_enabled(monkeypatch):
    """Alembic's fileConfig (run by DB fixtures elsewhere in the session)
    disables already-created loggers; caplog needs this one live."""
    import logging
    monkeypatch.setattr(logging.getLogger("app.web.ratelimit"), "disabled", False)


def _trust(monkeypatch, raw: str) -> None:
    monkeypatch.setattr(ratelimit, "_TRUSTED_PROXIES", ratelimit.parse_trusted_proxies(raw))


def test_parse_trusted_proxies_accepts_ips_and_cidrs():
    nets = ratelimit.parse_trusted_proxies(" 172.16.0.0/12 , 10.0.0.1,::1 ,, ")
    assert [str(n) for n in nets] == ["172.16.0.0/12", "10.0.0.1/32", "::1/128"]


def test_parse_trusted_proxies_skips_invalid_entries(caplog):
    with caplog.at_level("WARNING", logger="app.web.ratelimit"):
        nets = ratelimit.parse_trusted_proxies("not-an-ip, 10.0.0.0/8, 999.1.1.1")
    assert [str(n) for n in nets] == ["10.0.0.0/8"]
    assert "not-an-ip" in caplog.text and "999.1.1.1" in caplog.text


def test_client_ip_cidr_trusts_any_docker_gateway(monkeypatch):
    """NPM's Docker gateway address changes; a CIDR covers all of them."""
    _trust(monkeypatch, "172.16.0.0/12")
    for gateway in ("172.18.0.1", "172.24.0.1", "172.31.255.254"):
        req = _mock_request(gateway, xff="198.51.100.20")
        assert ratelimit._client_ip(req) == "198.51.100.20"


def test_client_ip_one_hop_spoofed_left_entries_ignored(monkeypatch):
    """One proxy: the client can prepend anything; NPM appends the real peer
    on the right, and that is what we key on."""
    _trust(monkeypatch, "172.16.0.0/12")
    req = _mock_request("172.18.0.1", xff="1.2.3.4, 198.51.100.20")
    assert ratelimit._client_ip(req) == "198.51.100.20"


def test_client_ip_two_hops_skips_both_trusted_proxies(monkeypatch):
    """Cloudflare → NPM → app: the right-most entry is the Cloudflare edge,
    which is trusted, so the next one left is the real visitor."""
    _trust(monkeypatch, "172.16.0.0/12, 173.245.48.0/20")
    req = _mock_request("172.18.0.1", xff="198.51.100.20, 173.245.48.10")
    assert ratelimit._client_ip(req) == "198.51.100.20"


def test_client_ip_two_hops_distinct_visitors_get_distinct_keys(monkeypatch):
    _trust(monkeypatch, "172.16.0.0/12, 173.245.48.0/20")
    a = _mock_request("172.18.0.1", xff="198.51.100.20, 173.245.48.10")
    b = _mock_request("172.18.0.1", xff="198.51.100.99, 173.245.48.11")
    assert ratelimit._client_ip(a) != ratelimit._client_ip(b)


def test_client_ip_two_hops_with_only_inner_proxy_trusted_keys_on_edge(monkeypatch):
    """Negative: if the outer proxy isn't listed, its address is treated as
    the client (safe, never trusts a forgeable entry)."""
    _trust(monkeypatch, "172.16.0.0/12")
    req = _mock_request("172.18.0.1", xff="1.2.3.4, 198.51.100.20, 173.245.48.10")
    assert ratelimit._client_ip(req) == "173.245.48.10"


def test_client_ip_all_hops_trusted_uses_leftmost(monkeypatch):
    _trust(monkeypatch, "10.0.0.0/8")
    req = _mock_request("10.0.0.1", xff="10.1.1.1, 10.2.2.2")
    assert ratelimit._client_ip(req) == "10.1.1.1"


def test_client_ip_spoofed_xff_from_untrusted_peer_ignored(monkeypatch):
    _trust(monkeypatch, "172.16.0.0/12")
    req = _mock_request("203.0.113.66", xff="198.51.100.1, 172.18.0.1")
    assert ratelimit._client_ip(req) == "203.0.113.66"


def test_client_ip_garbage_xff_entry_is_not_trusted(monkeypatch):
    _trust(monkeypatch, "172.16.0.0/12")
    req = _mock_request("172.18.0.1", xff="garbage")
    assert ratelimit._client_ip(req) == "garbage"


def test_client_ip_ipv4_mapped_ipv6_peer_is_trusted(monkeypatch):
    _trust(monkeypatch, "172.16.0.0/12")
    req = _mock_request("::ffff:172.18.0.1", xff="198.51.100.20")
    assert ratelimit._client_ip(req) == "198.51.100.20"


def test_untrusted_xff_logs_one_time_warning(monkeypatch, caplog):
    ratelimit.clear()
    _trust(monkeypatch, "")
    with caplog.at_level("WARNING", logger="app.web.ratelimit"):
        ratelimit._client_ip(_mock_request("172.18.0.1", xff="198.51.100.20"))
        ratelimit._client_ip(_mock_request("172.18.0.1", xff="198.51.100.21"))
    warnings = [r for r in caplog.records if "TRUSTED_PROXIES" in r.getMessage()]
    assert len(warnings) == 1
    assert "172.18.0.1" in warnings[0].getMessage()


def test_no_warning_without_xff(monkeypatch, caplog):
    ratelimit.clear()
    _trust(monkeypatch, "")
    with caplog.at_level("WARNING", logger="app.web.ratelimit"):
        ratelimit._client_ip(_mock_request("203.0.113.5"))
    assert "TRUSTED_PROXIES" not in caplog.text


def test_hit_returns_zero_when_allowed_and_seconds_when_blocked():
    ratelimit.clear()
    assert ratelimit.hit("t:1", max_attempts=1, window_seconds=600) == 0
    wait = ratelimit.hit("t:1", max_attempts=1, window_seconds=600)
    assert 1 <= wait <= 600


def test_retry_after_counts_down_from_oldest_attempt(monkeypatch):
    ratelimit.clear()
    clock = [1000.0]
    monkeypatch.setattr(ratelimit, "monotonic", lambda: clock[0])
    ratelimit.hit("t:2", max_attempts=2, window_seconds=900)
    clock[0] += 300
    ratelimit.hit("t:2", max_attempts=2, window_seconds=900)
    clock[0] += 100
    # oldest attempt was 400s ago, so 500s remain
    assert ratelimit.hit("t:2", max_attempts=2, window_seconds=900) == 500


def test_blocked_attempt_is_not_recorded(monkeypatch):
    """A rejected attempt must not extend the lockout."""
    ratelimit.clear()
    clock = [0.0]
    monkeypatch.setattr(ratelimit, "monotonic", lambda: clock[0])
    ratelimit.hit("t:3", max_attempts=1, window_seconds=60)
    for _ in range(5):
        clock[0] += 10
        ratelimit.hit("t:3", max_attempts=1, window_seconds=60)
    clock[0] = 61
    assert ratelimit.hit("t:3", max_attempts=1, window_seconds=60) == 0


def test_wait_message_rounds_up_and_pluralizes():
    assert ratelimit.wait_message(1) == "Try again in 1 minute."
    assert ratelimit.wait_message(60) == "Try again in 1 minute."
    assert ratelimit.wait_message(61) == "Try again in 2 minutes."
    assert ratelimit.wait_message(900) == "Try again in 15 minutes."
