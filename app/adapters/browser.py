from playwright.sync_api import sync_playwright


def render_html(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            return page.content()
        finally:
            browser.close()
