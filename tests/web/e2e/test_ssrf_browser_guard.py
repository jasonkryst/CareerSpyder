import http.server
import socket
import threading

import pytest
from playwright.sync_api import Error as PlaywrightError

from app.security.ssrf_guard import UnsafeUrlError, install_ssrf_guard

_REDIRECTS = {"/a": "/b", "/b": "/c"}


@pytest.fixture
def redirect_server():
    hits: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            if self.path in _REDIRECTS:
                self.send_response(302)
                self.send_header("Location", _REDIRECTS[self.path])
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(f"<p>reached {self.path}</p>".encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", hits
    server.shutdown()


def _block_c(url: str) -> None:
    if url.endswith("/c"):
        raise UnsafeUrlError("blocked")


def test_second_redirect_hop_to_a_blocked_url_is_never_requested(browser, redirect_server):
    # Reuses conftest's session-scoped `browser` fixture (its `sync_playwright()`
    # context stays open for the whole suite) rather than opening a second,
    # nested `sync_playwright()` here -- Playwright's sync API doesn't support
    # two concurrent contexts on the same thread and raises "It looks like you
    # are using Playwright Sync API inside the asyncio loop" if you try.
    base, hits = redirect_server
    page = browser.new_page(service_workers="block")
    try:
        install_ssrf_guard(page, check=_block_c)
        with pytest.raises(PlaywrightError):
            page.goto(f"{base}/a")
    finally:
        page.close()
    assert "/c" not in hits


def test_allowed_redirect_chain_renders_the_final_page(browser, redirect_server):
    base, _ = redirect_server
    page = browser.new_page(service_workers="block")
    try:
        install_ssrf_guard(page, check=lambda url: None)
        page.goto(f"{base}/a")
        assert page.inner_text("p") == "reached /c"
    finally:
        page.close()


@pytest.fixture
def tcp_listener():
    """A bare TCP listener that records every accepted connection -- stands
    in for an internal service a rendered page might open a WebSocket to."""
    accepted: list[tuple] = []
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    sock.settimeout(0.2)
    stop = threading.Event()

    def _accept():
        while not stop.is_set():
            try:
                conn, addr = sock.accept()
            except OSError:
                continue
            accepted.append(addr)
            conn.close()

    thread = threading.Thread(target=_accept, daemon=True)
    thread.start()
    yield sock.getsockname()[1], accepted
    stop.set()
    thread.join()
    sock.close()


def _open_websocket_and_wait(page, base, port) -> None:
    page.goto(f"{base}/page")
    page.evaluate(f"() => {{ window.__ws = new WebSocket('ws://127.0.0.1:{port}/'); }}")
    # wait_for_timeout, not time.sleep: the sync API only dispatches route
    # handlers while a Playwright call is pumping events.
    page.wait_for_timeout(1000)


def test_page_websocket_to_a_blocked_host_never_connects(browser, redirect_server, tcp_listener):
    base, _ = redirect_server
    port, accepted = tcp_listener

    def _block_listener(url: str) -> None:
        if f":{port}" in url:
            raise UnsafeUrlError("blocked")

    page = browser.new_page(service_workers="block")
    try:
        install_ssrf_guard(page, check=_block_listener)
        _open_websocket_and_wait(page, base, port)
    finally:
        page.close()
    assert accepted == []


def test_page_websocket_to_an_allowed_host_connects(browser, redirect_server, tcp_listener):
    # Control for the test above: proves the listener does see a connection
    # when the guard allows it, so an empty `accepted` there means "blocked",
    # not "the WebSocket never fired".
    base, _ = redirect_server
    port, accepted = tcp_listener
    page = browser.new_page(service_workers="block")
    try:
        install_ssrf_guard(page, check=lambda url: None)
        _open_websocket_and_wait(page, base, port)
    finally:
        page.close()
    assert accepted
