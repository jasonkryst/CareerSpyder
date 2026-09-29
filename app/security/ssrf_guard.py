import ipaddress
import logging
import socket
import sys
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import (
    ConnectTimeoutError,
    NameResolutionError,
    NewConnectionError,
)
from urllib3.util import connection as _u3conn

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}
_DEFAULT_MAX_REDIRECTS = 5
_DEFAULT_TIMEOUT = 30
_NAT64 = ipaddress.ip_network("64:ff9b::/96")

UNSAFE_URL_MESSAGE = "That URL points to a private or internal network address, which isn't allowed."


class UnsafeUrlError(ValueError):
    pass


def _is_disallowed_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip in _NAT64:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    # is_global excludes CGNAT (100.64/10 -- Tailscale), benchmarking, and the
    # other special-purpose ranges the individual is_* flags miss (audit M2).
    return (
        not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def _resolve_public_ip(host: str, port: int | None) -> str:
    """Resolve `host`, reject it if *any* answer is non-public, and return the
    address to dial -- the caller connects to exactly this IP (no second lookup)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Could not resolve host: {host!r}") from exc
    for info in infos:
        if _is_disallowed_ip(str(info[4][0])):
            logger.info("Blocked outbound request to %s (resolves to %s)", host, info[4][0])
            raise UnsafeUrlError(UNSAFE_URL_MESSAGE)
    return str(infos[0][4][0])


def assert_safe_url(url: str) -> None:
    """Raises UnsafeUrlError unless `url` is http(s) and its host resolves only
    to public addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"Disallowed URL scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise UnsafeUrlError("URL has no hostname")
    _resolve_public_ip(parsed.hostname, parsed.port)


class _PinnedConnectionMixin:
    """Resolve-validate-connect in one step, closing the DNS-rebinding window
    between assert_safe_url's lookup and urllib3's own. TLS SNI and certificate
    checks still use the hostname (urllib3 takes those from self.host)."""

    def _new_conn(self):
        # Mirrors urllib3's own HTTPConnection._new_conn exception mapping
        # (see urllib3.connection.HTTPConnection._new_conn) so callers still
        # see the same ConnectTimeoutError/NewConnectionError/NameResolutionError
        # -> requests.exceptions.{ConnectTimeout,ConnectionError} behavior they'd
        # get from an unpinned connection. UnsafeUrlError (a ValueError) is
        # raised by _resolve_public_ip before the try below and propagates
        # unchanged -- it must never be caught and rewrapped here.
        ip = _resolve_public_ip(self._dns_host, self.port)
        try:
            sock = _u3conn.create_connection(
                (ip, self.port),
                self.timeout,
                source_address=self.source_address,
                socket_options=self.socket_options,
            )
        except socket.gaierror as exc:
            # Unreachable in practice: `ip` above is already a literal address,
            # so create_connection's own getaddrinfo can't fail to resolve it.
            # Kept only to mirror urllib3's mapping exactly.
            raise NameResolutionError(self.host, self, exc) from exc
        except TimeoutError as exc:
            raise ConnectTimeoutError(
                self,
                f"Connection to {self.host} timed out. (connect timeout={self.timeout})",
            ) from exc
        except OSError as exc:
            raise NewConnectionError(
                self, f"Failed to establish a new connection: {exc}"
            ) from exc
        sys.audit("http.client.connect", self, self.host, self.port)
        return sock


class _PinnedHTTPConnection(_PinnedConnectionMixin, HTTPConnection):
    pass


class _PinnedHTTPSConnection(_PinnedConnectionMixin, HTTPSConnection):
    pass


class _PinnedHTTPPool(HTTPConnectionPool):
    ConnectionCls = _PinnedHTTPConnection


class _PinnedHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _PinnedHTTPSConnection


class _PinnedAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _PinnedHTTPPool, "https": _PinnedHTTPSPool}


def _guarded_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False  # an env proxy would dial the target itself, unpinned
    adapter = _PinnedAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def safe_request(method: str, url: str, *, max_redirects: int = _DEFAULT_MAX_REDIRECTS,
                  **kwargs) -> requests.Response:
    """requests.request wrapper that SSRF-validates every hop and dials only
    the validated address."""
    assert_safe_url(url)
    kwargs["allow_redirects"] = False
    kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
    current_url = url
    with _guarded_session() as session:
        for _ in range(max_redirects + 1):
            response = session.request(method, current_url, **kwargs)
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                if not location:
                    return response
                current_url = urljoin(current_url, location)
                assert_safe_url(current_url)
                continue
            return response
    raise UnsafeUrlError(f"Too many redirects (> {max_redirects})")


def safe_get(url: str, **kwargs) -> requests.Response:
    return safe_request("GET", url, **kwargs)


def safe_post(url: str, **kwargs) -> requests.Response:
    return safe_request("POST", url, **kwargs)


def safe_head(url: str, **kwargs) -> requests.Response:
    kwargs.pop("allow_redirects", None)  # redirects are always followed hop-by-hop
    return safe_request("HEAD", url, **kwargs)


def make_route_handler(check: Callable[[str], None] = assert_safe_url):
    """Playwright route handler enforcing `check` on every request.

    page.route only sees the first URL of a redirect chain -- Chromium follows
    3xx hops unrouted (audit H4, verified against Playwright 1.62). So for
    documents the handler fetches hop-by-hop itself, vets every Location, and
    fulfils the final response. Subresources are vetted on their first URL.
    """

    def _handle(route) -> None:
        request = route.request
        try:
            check(request.url)
        except UnsafeUrlError:
            route.abort("blockedbyclient")
            return
        if request.resource_type != "document":
            route.continue_()
            return
        url = request.url
        for _ in range(_DEFAULT_MAX_REDIRECTS + 1):
            response = route.fetch(url=url, max_redirects=0)
            location = response.headers.get("location")
            if not (300 <= response.status < 400 and location):
                route.fulfill(response=response)
                return
            url = urljoin(url, location)
            try:
                check(url)
            except UnsafeUrlError:
                route.abort("blockedbyclient")
                return
        route.abort("blockedbyclient")

    return _handle


def install_ssrf_guard(page, check: Callable[[str], None] = assert_safe_url) -> None:
    """Attaches a Playwright route handler (see `make_route_handler`) that
    SSRF-validates every request the page makes, walking redirect chains
    hop-by-hop itself since Chromium follows 3xx redirects unrouted."""
    page.route("**/*", make_route_handler(check))
