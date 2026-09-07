from unittest.mock import MagicMock, patch

from app.adapters import browser


def _make_playwright_mocks():
    probe = MagicMock()
    probe.evaluate.return_value = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "HeadlessChrome/120.0.0.0 Safari/537.36"
    )
    page = MagicMock()
    page.content.return_value = "<html>rendered</html>"

    chromium_browser = MagicMock()
    chromium_browser.new_page.side_effect = [probe, page]

    p = MagicMock()
    p.chromium.launch.return_value = chromium_browser

    sync_playwright_cm = MagicMock()
    sync_playwright_cm.__enter__.return_value = p
    sync_playwright_cm.__exit__.return_value = False

    return sync_playwright_cm, chromium_browser, probe, page


def test_render_html_replaces_headlesschrome_in_the_user_agent():
    sync_playwright_cm, chromium_browser, _probe, _page = _make_playwright_mocks()

    with patch("app.adapters.browser.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.browser.assert_safe_url"), \
         patch("app.adapters.browser.install_ssrf_guard"):
        browser.render_html("https://example.test/careers")

    _, kwargs = chromium_browser.new_page.call_args_list[1]
    assert "HeadlessChrome" not in kwargs["user_agent"]
    assert "Chrome/120.0.0.0" in kwargs["user_agent"]


def test_render_html_navigates_with_networkidle_and_a_30s_timeout():
    sync_playwright_cm, _chromium_browser, _probe, page = _make_playwright_mocks()

    with patch("app.adapters.browser.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.browser.assert_safe_url"), \
         patch("app.adapters.browser.install_ssrf_guard"):
        browser.render_html("https://example.test/careers")

    page.goto.assert_called_once_with("https://example.test/careers", wait_until="networkidle", timeout=30000)


def test_render_html_returns_the_page_content():
    sync_playwright_cm, _chromium_browser, _probe, _page = _make_playwright_mocks()

    with patch("app.adapters.browser.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.browser.assert_safe_url"), \
         patch("app.adapters.browser.install_ssrf_guard"):
        result = browser.render_html("https://example.test/careers")

    assert result == "<html>rendered</html>"


def test_render_html_closes_the_browser_even_if_goto_raises():
    sync_playwright_cm, chromium_browser, _probe, page = _make_playwright_mocks()
    page.goto.side_effect = RuntimeError("navigation failed")

    with patch("app.adapters.browser.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.browser.assert_safe_url"), \
         patch("app.adapters.browser.install_ssrf_guard"):
        try:
            browser.render_html("https://example.test/careers")
        except RuntimeError:
            pass

    chromium_browser.close.assert_called_once()


def test_render_html_validates_the_url_before_launching_a_browser():
    from app.security.ssrf_guard import UnsafeUrlError

    with patch("app.adapters.browser.assert_safe_url", side_effect=UnsafeUrlError("blocked")) as mock_assert, \
         patch("app.adapters.browser.sync_playwright") as mock_sync_playwright:
        try:
            browser.render_html("http://169.254.169.254/")
        except UnsafeUrlError:
            pass

    mock_assert.assert_called_once_with("http://169.254.169.254/")
    mock_sync_playwright.assert_not_called()


def test_render_html_installs_the_ssrf_guard_on_the_rendered_page():
    sync_playwright_cm, _chromium_browser, _probe, page = _make_playwright_mocks()

    with patch("app.adapters.browser.sync_playwright", return_value=sync_playwright_cm), \
         patch("app.adapters.browser.assert_safe_url"), \
         patch("app.adapters.browser.install_ssrf_guard") as mock_install:
        browser.render_html("https://example.test/careers")

    mock_install.assert_called_once_with(page)
