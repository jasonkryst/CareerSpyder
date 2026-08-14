import time

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from app.config import InforSource
from app.models import Job


def _parse_page(html: str, source: InforSource) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select(".inforCardstackCell"):
        heading = card.select_one(".inforCardstackHeading")
        if heading is None:
            continue
        title = heading.get_text(strip=True)

        posted_date = None
        posted_div = card.select_one(".PostedDiv")
        if posted_div is not None:
            value = posted_div.select_one(".inforCardstackValue")
            if value is not None:
                posted_date = value.get_text(strip=True)

        location = None
        location_lbl = card.select_one(".LocationLbl")
        if location_lbl is not None:
            value = location_lbl.find_next_sibling(class_="inforCardstackValue")
            if value is not None:
                location = value.get_text(strip=True)

        jobs.append(Job(
            key=f"infor:{source.company}:{title}:{location}",
            title=title,
            url=source.url,
            company=source.company,
            location=location,
            posted_date=posted_date,
            source_name=source.name,
            source_id=source.id,
        ))
    return jobs


def _wait_for_new_first_title(frame, previous_title: str | None, timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        headings = frame.locator(".inforCardstackHeading")
        current = headings.first.text_content() if headings.count() > 0 else None
        if current != previous_title:
            return
        time.sleep(0.5)


def default_frame_fetcher(url: str, page_number: int) -> str | None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            frame = page.frame_locator("#parentIframe")
            frame.locator(".slick-row").first.wait_for(timeout=15000)

            for _ in range(page_number - 1):
                next_button = frame.locator("button.nextPage")
                if next_button.is_disabled():
                    return None
                previous_title = frame.locator(".inforCardstackHeading").first.text_content()
                next_button.click()
                _wait_for_new_first_title(frame, previous_title)

            if frame.locator(".inforCardstackCell").count() == 0:
                return None

            return frame.locator("body").inner_html()
        finally:
            browser.close()


def fetch(source: InforSource, frame_fetcher=default_frame_fetcher) -> list[Job]:
    all_jobs: list[Job] = []
    for page_number in range(1, source.max_pages + 1):
        html = frame_fetcher(source.url, page_number)
        if html is None:
            break
        page_jobs = _parse_page(html, source)
        if not page_jobs:
            break
        all_jobs.extend(page_jobs)
    return all_jobs
