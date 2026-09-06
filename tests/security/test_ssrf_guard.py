import socket
from unittest.mock import Mock, patch

import pytest
import requests

from app.security.ssrf_guard import (
    UnsafeUrlError,
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
         pytest.raises(UnsafeUrlError, match="disallowed"):
        assert_safe_url("https://internal.test/")


def test_assert_safe_url_rejects_when_dns_resolution_fails():
    with patch("app.security.ssrf_guard.socket.getaddrinfo", side_effect=socket.gaierror("no such host")), \
         pytest.raises(UnsafeUrlError, match="resolve"):
        assert_safe_url("https://nowhere.invalid/")


def test_safe_get_validates_before_calling_requests():
    with patch("app.security.ssrf_guard.socket.getaddrinfo", side_effect=socket.gaierror("boom")), \
         pytest.raises(UnsafeUrlError):
        safe_get("https://nowhere.invalid/")


def test_safe_get_calls_through_to_requests_for_a_safe_url():
    fake_response = Mock(spec=requests.Response)
    fake_response.is_redirect = False
    fake_response.is_permanent_redirect = False
    with patch("app.security.ssrf_guard.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")), \
         patch("app.security.ssrf_guard.requests.request", return_value=fake_response) as mock_request:
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
         patch("app.security.ssrf_guard.requests.request", return_value=first_hop), \
         pytest.raises(UnsafeUrlError, match="disallowed"):
        safe_get("https://example.test/")


def test_safe_get_follows_a_safe_redirect_to_its_final_response():
    first_hop = Mock(spec=requests.Response)
    first_hop.is_redirect = True
    first_hop.is_permanent_redirect = False
    first_hop.headers = {"Location": "https://example.test/final"}
    final = Mock(spec=requests.Response)
    final.is_redirect = False
    final.is_permanent_redirect = False

    with patch("app.security.ssrf_guard.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")), \
         patch("app.security.ssrf_guard.requests.request", side_effect=[first_hop, final]):
        result = safe_get("https://example.test/")

    assert result is final


def test_safe_get_raises_after_too_many_redirects():
    hop = Mock(spec=requests.Response)
    hop.is_redirect = True
    hop.is_permanent_redirect = False
    hop.headers = {"Location": "https://example.test/loop"}

    with patch("app.security.ssrf_guard.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")), \
         patch("app.security.ssrf_guard.requests.request", return_value=hop), \
         pytest.raises(UnsafeUrlError, match="redirects"):
        safe_get("https://example.test/", max_redirects=2)


def test_safe_post_uses_post_method():
    fake_response = Mock(spec=requests.Response)
    fake_response.is_redirect = False
    fake_response.is_permanent_redirect = False
    with patch("app.security.ssrf_guard.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")), \
         patch("app.security.ssrf_guard.requests.request", return_value=fake_response) as mock_request:
        safe_post("https://example.test/api", json={"a": 1})

    args, _ = mock_request.call_args
    assert args[0] == "POST"


def test_install_ssrf_guard_routes_document_requests_through_the_page():
    fake_page = Mock()
    install_ssrf_guard(fake_page)
    assert fake_page.route.call_count == 1
    args, _ = fake_page.route.call_args
    assert args[0] == "**/*"


def test_install_ssrf_guard_aborts_a_disallowed_document_navigation():
    fake_page = Mock()
    install_ssrf_guard(fake_page)
    handler = fake_page.route.call_args[0][1]

    fake_route = Mock()
    fake_route.request.resource_type = "document"
    fake_route.request.url = "http://169.254.169.254/"

    with patch("app.security.ssrf_guard.socket.getaddrinfo", return_value=_addrinfo("169.254.169.254")):
        handler(fake_route)

    fake_route.abort.assert_called_once()
    fake_route.continue_.assert_not_called()


def test_install_ssrf_guard_allows_a_safe_document_navigation():
    fake_page = Mock()
    install_ssrf_guard(fake_page)
    handler = fake_page.route.call_args[0][1]

    fake_route = Mock()
    fake_route.request.resource_type = "document"
    fake_route.request.url = "https://example.test/"

    with patch("app.security.ssrf_guard.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
        handler(fake_route)

    fake_route.continue_.assert_called_once()
    fake_route.abort.assert_not_called()


def test_install_ssrf_guard_lets_non_document_resources_through_unchecked():
    fake_page = Mock()
    install_ssrf_guard(fake_page)
    handler = fake_page.route.call_args[0][1]

    fake_route = Mock()
    fake_route.request.resource_type = "image"
    fake_route.request.url = "http://169.254.169.254/logo.png"

    handler(fake_route)

    fake_route.continue_.assert_called_once()
    fake_route.abort.assert_not_called()
