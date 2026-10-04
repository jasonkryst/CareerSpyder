import os

from playwright.sync_api import sync_playwright

from app.security.ssrf_guard import assert_safe_url, install_ssrf_guard


def chromium_launch_kwargs() -> dict:
    """Playwright launches Chromium with its sandbox off by default.  Opt in
    with ``CHROMIUM_SANDBOX=1`` where the container runtime supports it
    (audit finding M8).  See SECURITY.md for details."""
    if os.environ.get("CHROMIUM_SANDBOX", "").lower() in ("1", "true"):
        return {"chromium_sandbox": True}
    return {}


def render_html(url: str) -> str:
    assert_safe_url(url)
    with sync_playwright() as p:
        browser = p.chromium.launch(**chromium_launch_kwargs())
        try:
            # Some sites block on the literal "HeadlessChrome" UA token (e.g. OSF
            # HealthCare's Jibe-hosted career site returns a bare 403 for it), so
            # spoof a normal Chrome UA rather than let Playwright's default through.
            probe = browser.new_page()
            user_agent = probe.evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome")
            probe.close()

            page = browser.new_page(user_agent=user_agent, service_workers="block")
            install_ssrf_guard(page)
            page.goto(url, wait_until="networkidle", timeout=30000)
            return page.content()
        finally:
            browser.close()
