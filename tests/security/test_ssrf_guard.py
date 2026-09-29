import socket
from unittest.mock import Mock, patch

import pytest
import requests

from app.security import ssrf_guard
from app.security.ssrf_guard import (
    UNSAFE_URL_MESSAGE,
    UnsafeUrlError,
    _is_disallowed_ip,
    assert_safe_url,
    install_ssrf_guard,
    safe_get,
    safe_post,
)


def _addrinfo(ip):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


def test_assert_safe_url_allows_a_public_https_host():
    with patch("app.security.ssrf_guard.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
        assert_safe_url("https://example.test/path")


def test_assert_safe_url_rejects_a_non_http_scheme():
    with pytest.raises(UnsafeUrlError, match="scheme"):
        assert_safe_url("file:///etc/passwd")


def test_assert_safe_url_rejects_javascript_scheme():
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("javascript:alert(1)")


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "192.168.1.1", "0.0.0.0"])  # noqa: S104
def test_assert_safe_url_rejects_private_and_loopback_resolved_ips(ip):
    with patch("app.security.ssrf_guard.socket.getaddrinfo", return_value=_addrinfo(ip)), \
         pytest.raises(UnsafeUrlError) as exc:
        assert_safe_url("https://internal.test/")
    assert str(exc.value) == UNSAFE_URL_MESSAGE
    assert ip not in str(exc.value)


def test_assert_safe_url_rejects_when_dns_resolution_fails():
    with patch("app.security.ssrf_guard.socket.getaddrinfo", side_effect=socket.gaierror("no such host")), \
         pytest.raises(UnsafeUrlError, match="resolve"):
        assert_safe_url("https://nowhere.invalid/")


@pytest.mark.parametrize("ip", [
    "100.64.0.1", "100.101.102.103",        # CGNAT / Tailscale
    "64:ff9b::7f00:1",                        # NAT64 of 127.0.0.1
    "::ffff:10.0.0.1", "198.18.0.1", "192.0.0.1", "0.0.0.0", "fd00::1",  # noqa: S104
])
def test_non_global_addresses_are_blocked(ip):
    assert _is_disallowed_ip(ip) is True


@pytest.mark.parametrize("ip", ["93.184.216.34", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(ip):
    assert _is_disallowed_ip(ip) is False


def _ai(ip: str, port: int = 80):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (ip, port))]


def test_safe_get_validates_before_calling_requests():
    with patch("app.security.ssrf_guard.socket.getaddrinfo", side_effect=socket.gaierror("boom")), \
         pytest.raises(UnsafeUrlError):
        safe_get("https://nowhere.invalid/")


def test_safe_get_calls_through_to_requests_for_a_safe_url():
    fake_response = Mock(spec=requests.Response)
    fake_response.is_redirect = False
    fake_response.is_permanent_redirect = False
    with patch("app.security.ssrf_guard.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")), \
         patch("requests.Session.request", return_value=fake_response) as mock_request:
        result = safe_get("https://example.test/", timeout=15)

    assert result is fake_response
    args, kwargs = mock_request.call_args
    assert args == ("GET", "https://example.test/")
    assert kwargs["timeout"] == 15
    assert kwargs["allow_redirects"] is False


def test_safe_get_revalidates_each_redirect_hop_and_rejects_an_internal_target():
    first_hop = Mock(spec=requests.Response)
    first_hop.is_redirect = True
    first_hop.is_permanent_redirect = False
    first_hop.headers = {"Location": "http://169.254.169.254/latest/meta-data/"}

    def fake_getaddrinfo(host, *args, **kwargs):
        return _addrinfo(host if host == "169.254.169.254" else "93.184.216.34")

    with patch("app.security.ssrf_guard.socket.getaddrinfo", side_effect=fake_getaddrinfo), \
         patch("requests.Session.request", return_value=first_hop), \
         pytest.raises(UnsafeUrlError) as exc:
        safe_get("https://example.test/")
    assert str(exc.value) == UNSAFE_URL_MESSAGE


def test_safe_get_follows_a_safe_redirect_to_its_final_response():
    first_hop = Mock(spec=requests.Response)
    first_hop.is_redirect = True
    first_hop.is_permanent_redirect = False
    first_hop.headers = {"Location": "https://example.test/final"}
    final = Mock(spec=requests.Response)
    final.is_redirect = False
    final.is_permanent_redirect = False

    with patch("app.security.ssrf_guard.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")), \
         patch("requests.Session.request", side_effect=[first_hop, final]):
        result = safe_get("https://example.test/")

    assert result is final


def test_safe_get_raises_after_too_many_redirects():
    hop = Mock(spec=requests.Response)
    hop.is_redirect = True
    hop.is_permanent_redirect = False
    hop.headers = {"Location": "https://example.test/loop"}

    with patch("app.security.ssrf_guard.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")), \
         patch("requests.Session.request", return_value=hop), \
         pytest.raises(UnsafeUrlError, match="redirects"):
        safe_get("https://example.test/", max_redirects=2)


def test_safe_post_uses_post_method():
    fake_response = Mock(spec=requests.Response)
    fake_response.is_redirect = False
    fake_response.is_permanent_redirect = False
    with patch("app.security.ssrf_guard.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")), \
         patch("requests.Session.request", return_value=fake_response) as mock_request:
        safe_post("https://example.test/api", json={"a": 1})

    args, _ = mock_request.call_args
    assert args[0] == "POST"


def test_safe_get_pins_the_validated_address_against_dns_rebinding(monkeypatch):
    calls = []

    def rebinding(host, *args, **kwargs):
        calls.append(host)
        return _ai("93.184.216.34") if len(calls) == 1 else _ai("127.0.0.1")

    monkeypatch.setattr(socket, "getaddrinfo", rebinding)
    with pytest.raises(UnsafeUrlError):
        ssrf_guard.safe_get("http://rebind.test/")


def test_safe_get_connects_to_the_address_it_validated(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _ai("93.184.216.34"))
    dialed = []

    def fake_create_connection(address, *args, **kwargs):
        dialed.append(address)
        raise OSError("no network in tests")

    monkeypatch.setattr(ssrf_guard._u3conn, "create_connection", fake_create_connection)
    with pytest.raises(requests.ConnectionError):
        ssrf_guard.safe_get("http://public.test/")
    assert dialed == [("93.184.216.34", 80)]


def test_safe_get_connect_timeout_surfaces_as_requests_connect_timeout(monkeypatch):
    """The pinned connection must map a socket timeout during connect the same
    way urllib3's own HTTPConnection._new_conn does (ConnectTimeoutError), not
    fold it into the generic NewConnectionError/OSError branch -- otherwise a
    connect timeout would surface as ConnectionError instead of ConnectTimeout."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _ai("93.184.216.34"))

    def fake_create_connection(address, *args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(ssrf_guard._u3conn, "create_connection", fake_create_connection)
    with pytest.raises(requests.exceptions.ConnectTimeout):
        ssrf_guard.safe_get("http://public.test/")


def test_unsafe_url_errors_do_not_reveal_resolved_addresses(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _ai("10.0.0.5"))
    with pytest.raises(UnsafeUrlError) as exc:
        ssrf_guard.assert_safe_url("http://intranet.test/")
    assert "10.0.0.5" not in str(exc.value)


def test_install_ssrf_guard_routes_every_request_through_the_page():
    # The redirect-walking / subresource handler logic itself is covered by
    # tests/security/test_browser_guard.py (fake Route) and
    # tests/web/e2e/test_ssrf_browser_guard.py (real Chromium). This just
    # checks install_ssrf_guard wires a handler up for every request.
    fake_page = Mock()
    install_ssrf_guard(fake_page)
    assert fake_page.route.call_count == 1
    args, _ = fake_page.route.call_args
    assert args[0] == "**/*"
    assert callable(args[1])


def test_install_ssrf_guard_uses_the_given_check_instead_of_the_default():
    fake_page = Mock()
    custom_check = Mock(side_effect=UnsafeUrlError("blocked"))
    install_ssrf_guard(fake_page, check=custom_check)
    handler = fake_page.route.call_args[0][1]

    fake_route = Mock()
    fake_route.request.resource_type = "image"
    fake_route.request.url = "https://example.test/logo.png"

    handler(fake_route)

    custom_check.assert_called_once_with("https://example.test/logo.png")
    fake_route.abort.assert_called_once_with("blockedbyclient")
