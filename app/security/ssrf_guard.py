import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests

_ALLOWED_SCHEMES = {"http", "https"}
_DEFAULT_MAX_REDIRECTS = 5
_DEFAULT_TIMEOUT = 30


class UnsafeUrlError(ValueError):
    pass


def _is_disallowed_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def assert_safe_url(url: str) -> None:
    """Raises UnsafeUrlError unless `url` is http(s) and every address its
    host resolves to is public -- the same check must run again on each
    redirect hop, since a first-hop-only check lets a public URL 302 to an
    internal one."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"Disallowed URL scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise UnsafeUrlError("URL has no hostname")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Could not resolve host: {parsed.hostname!r}") from exc
    for info in infos:
        ip_str = str(info[4][0])
        if _is_disallowed_ip(ip_str):
            raise UnsafeUrlError(f"URL resolves to a disallowed address: {ip_str}")


def safe_request(method: str, url: str, *, max_redirects: int = _DEFAULT_MAX_REDIRECTS,
                  **kwargs) -> requests.Response:
    """requests.request wrapper that SSRF-validates the URL and re-validates
    after every redirect hop before following it."""
    assert_safe_url(url)
    kwargs["allow_redirects"] = False
    kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
    current_url = url
    for _ in range(max_redirects + 1):
        response = requests.request(method, current_url, **kwargs)  # noqa: S113 -- timeout defaulted above
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


def install_ssrf_guard(page) -> None:
    """Attaches a Playwright route handler that SSRF-validates every
    top-level document navigation (including redirect hops, which arrive as
    separate routed requests) before letting the browser follow it.
    Subresources (images/scripts/css) are left unchecked so normal page
    rendering isn't affected."""

    def _handle_route(route) -> None:
        request = route.request
        if request.resource_type != "document":
            route.continue_()
            return
        try:
            assert_safe_url(request.url)
        except UnsafeUrlError:
            route.abort()
            return
        route.continue_()

    page.route("**/*", _handle_route)
