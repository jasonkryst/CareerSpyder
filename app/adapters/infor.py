import time

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from app.config import InforSource
from app.models import Job
from app.security.ssrf_guard import assert_safe_url, install_ssrf_guard

# CSS selectors for two known Infor job board UI generations.
# v1 = Slickgrid card-stack (older).  v2 = list-view SPA (newer, e.g. Rush post-2025).
_V1_CARD = ".inforCardstackCell"
_V2_CARD = "li[job-req]"
_CARD_SELECTOR = f"{_V2_CARD}, {_V1_CARD}"   # presence check (BeautifulSoup)
_NEXT_SELECTOR = "button.nextPage, a.nextPage"  # both UI generations use nextPage

# Slickgrid renders .slick-row containers before the card-cell content inside
# them is injected by the application JS.  Waiting for .slick-row is therefore
# reliable as the "grid has initialised" signal; waiting directly for
# .inforCardstackCell can race against the cell-render step and time out.
_V1_SLICK_ROW = ".slick-row"

# Generic "v2 grid has content" selector: waits for any child of gridContent
# rather than li[job-req] specifically, so portals with different card markup
# still work.  The actual card selectors (_V2_CARD, _V1_CARD) are tried by
# _parse_page / BeautifulSoup after the HTML is retrieved.
_V2_CONTENT_READY = "div.gridContent > *"


def _parse_v1_card(card, source: InforSource) -> Job | None:
    heading = card.select_one(".inforCardstackHeading")
    if heading is None:
        return None
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

    return Job(
        key=f"infor:{source.company}:{title}:{location}",
        title=title,
        url=source.url,
        company=source.company,
        location=location,
        posted_date=posted_date,
        source_name=source.name,
        source_id=source.id,
    )


def _parse_v2_card(card, source: InforSource) -> Job | None:
    heading = card.select_one("p.listview-heading")
    if heading is None:
        return None
    title = heading.get_text(strip=True)

    # Location: first span whose text has no colon (not a "Label: Value" pair).
    # Posted date: last span whose text contains a colon.
    # Category spans like "Department: Radiology" also have colons but appear
    # earlier in the DOM, so the last colon-span is reliably the posted date.
    location = None
    posted_date = None
    for span in card.select("span.listview-subheading"):
        text = span.get_text(strip=True)
        if not text:
            continue
        if ":" in text:
            posted_date = text
        elif location is None:
            location = text

    return Job(
        key=f"infor:{source.company}:{title}:{location}",
        title=title,
        url=source.url,
        company=source.company,
        location=location,
        posted_date=posted_date,
        source_name=source.name,
        source_id=source.id,
    )


def _parse_page(html: str, source: InforSource) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    # Prefer v2 list-view selectors; fall back to v1 card-stack.
    v2_cards = soup.select(_V2_CARD)
    if v2_cards:
        return [j for card in v2_cards if (j := _parse_v2_card(card, source)) is not None]
    return [j for card in soup.select(_V1_CARD) if (j := _parse_v1_card(card, source)) is not None]


def _title_changed(current: str | None, previous: str | None) -> bool:
    return current != previous


def _first_title(frame) -> str | None:
    """Returns the first job title visible in the frame, regardless of UI generation."""
    for selector in ("p.listview-heading", ".inforCardstackHeading"):
        loc = frame.locator(selector)
        if loc.count() > 0:
            return loc.first.text_content()
    return None


def _wait_for_new_first_title(frame, previous_title: str | None, timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _title_changed(_first_title(frame), previous_title):
            return
        time.sleep(0.5)


def default_frame_fetcher(url: str, page_number: int) -> str | None:
    assert_safe_url(url)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            install_ssrf_guard(page)
            page.goto(url, wait_until="networkidle", timeout=30000)

            # v2 portals (post-2025 Infor list-view SPA) render job cards
            # directly in div#jobListScreen → div.gridContent in the main page
            # body.  The iframe is absent or frozen at blank.html with no cards.
            #
            # Lawson-hybrid portals (e.g. RUMC/Rush Oak Park) also have
            # #jobListScreen in the outer shell but their actual job cards live
            # inside #parentIframe as a Slickgrid card-stack.
            #
            # networkidle fires before the iframe's own XHR completes, so an
            # instant count() probe on .slick-row returns 0 even on a healthy
            # Lawson-hybrid portal.  Instead, wait up to 5 s for the rows: if
            # they arrive it's a Lawson hybrid; if the wait times out the iframe
            # is a frozen blank.html and this is a true v2 portal.
            if page.locator("#jobListScreen").count() > 0:
                iframe_rows = False
                if page.locator("#parentIframe").count() > 0:
                    try:
                        page.frame_locator("#parentIframe").locator(_V1_SLICK_ROW).first.wait_for(
                            timeout=5000
                        )
                        iframe_rows = True
                    except Exception:
                        iframe_rows = False
                if not iframe_rows:
                    # True v2: wait for any child inside the job list's grid
                    # container.  Use the specific container to avoid strict-mode
                    # errors (the page has multiple div.gridContent siblings).
                    _v2_ready = "#jobListScreen .gridContent > *"
                    page.locator(_v2_ready).first.wait_for(timeout=30000)

                    for _ in range(page_number - 1):
                        load_more = page.locator("#gridBottom")
                        if load_more.count() == 0 or not load_more.is_visible():
                            return None
                        prev_count = page.locator(_v2_ready).count()
                        load_more.click()
                        deadline = time.monotonic() + 15.0
                        while time.monotonic() < deadline:
                            if page.locator(_v2_ready).count() > prev_count:
                                break
                            time.sleep(0.5)
                        else:
                            return None

                    if page.locator(_v2_ready).count() == 0:
                        return None
                    return page.locator("#jobListScreen .gridContent").first.inner_html()
                # else: Lawson hybrid — fall through to v1 iframe handling below.

            # v1: job cards inside #parentIframe (Slickgrid card-stack).
            # Wait for .slick-row (the Slickgrid row container) rather than the
            # card-cell selector: Slickgrid injects the row shells first, then
            # renders cell content asynchronously.  Waiting for the cell
            # selector can therefore time out even on a healthy portal.
            frame = page.frame_locator("#parentIframe")
            frame.locator(_V1_SLICK_ROW).first.wait_for(timeout=30000)

            for _ in range(page_number - 1):
                next_button = frame.locator(_NEXT_SELECTOR)
                if next_button.count() == 0 or next_button.is_disabled():
                    return None
                previous_title = _first_title(frame)
                next_button.click()
                _wait_for_new_first_title(frame, previous_title)

            if frame.locator(_CARD_SELECTOR).count() == 0:
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
