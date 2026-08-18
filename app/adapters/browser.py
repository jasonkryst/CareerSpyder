from playwright.sync_api import sync_playwright


def render_html(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            # Some sites block on the literal "HeadlessChrome" UA token (e.g. OSF
            # HealthCare's Jibe-hosted career site returns a bare 403 for it), so
            # spoof a normal Chrome UA rather than let Playwright's default through.
            probe = browser.new_page()
            user_agent = probe.evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome")
            probe.close()

            page = browser.new_page(user_agent=user_agent)
            page.goto(url, wait_until="networkidle", timeout=30000)
            return page.content()
        finally:
            browser.close()
