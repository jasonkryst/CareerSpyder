import logging
import time
from collections.abc import Iterator

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.config import InforSource
from app.models import Job
from app.security.ssrf_guard import assert_safe_url, install_ssrf_guard

logger = logging.getLogger(__name__)

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

# "v2 grid has content": any child of the job list's grid container, so
# portals with different card markup still count as rendered.  Scoped to
# #jobListScreen because the page has several div.gridContent siblings.
# The actual card selectors (_V2_CARD, _V1_CARD) are applied by _parse_page.
_V2_READY = "#jobListScreen .gridContent > *"

# How long to wait for either board generation to render cards, and how many
# times to load the board before giving up (issue #153).
_READY_TIMEOUT_S = 30.0
_LOAD_ATTEMPTS = 2


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


def _board_kind(page) -> str | None:
    """Returns "v1" once Slickgrid rows exist in #parentIframe, "v2" once the
    list-view grid in the main body has cards, else None (not rendered yet).

    Lawson-hybrid portals (e.g. RUMC/Rush Oak Park) have a #jobListScreen
    shell *and* their real cards in the iframe, so neither marker can be used
    to rule the other out -- we poll for whichever shows up first.
    """
    if page.frame_locator("#parentIframe").locator(_V1_SLICK_ROW).count() > 0:
        return "v1"
    if page.locator(_V2_READY).count() > 0:
        return "v2"
    return None


def _wait_for_board(page) -> str:
    deadline = time.monotonic() + _READY_TIMEOUT_S
    while True:
        kind = _board_kind(page)
        if kind is not None:
            return kind
        if time.monotonic() >= deadline:
            raise PlaywrightTimeoutError(
                f"Infor board rendered no job cards within {_READY_TIMEOUT_S:.0f}s"
            )
        time.sleep(0.5)


def _open_board(browser, url: str):
    """Loads the board and waits for cards, retrying the load once: the
    iframe's first XHR is occasionally very slow (issue #153)."""
    for attempt in range(1, _LOAD_ATTEMPTS + 1):
        page = browser.new_page()
        install_ssrf_guard(page)
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            return page, _wait_for_board(page)
        except PlaywrightTimeoutError:
            page.close()
            if attempt == _LOAD_ATTEMPTS:
                raise
            logger.warning("infor: board at %s not ready, retrying load", url)
    raise AssertionError("unreachable")


def _iter_v1_pages(page, max_pages: int) -> Iterator[str]:
    # Cards live inside #parentIframe (Slickgrid card-stack), paged by a
    # next button that swaps the grid's contents in place.
    frame = page.frame_locator("#parentIframe")
    for page_number in range(1, max_pages + 1):
        if page_number > 1:
            next_button = frame.locator(_NEXT_SELECTOR)
            if next_button.count() == 0 or next_button.is_disabled():
                return
            previous_title = _first_title(frame)
            next_button.click()
            _wait_for_new_first_title(frame, previous_title)
        if frame.locator(_CARD_SELECTOR).count() == 0:
            return
        yield frame.locator("body").inner_html()


def _iter_v2_pages(page, max_pages: int) -> Iterator[str]:
    # Cards render in the main body; "load more" (#gridBottom) appends to the
    # same grid, so each yield is cumulative -- fetch() dedupes by key.
    for page_number in range(1, max_pages + 1):
        if page_number > 1:
            load_more = page.locator("#gridBottom")
            if load_more.count() == 0 or not load_more.is_visible():
                return
            prev_count = page.locator(_V2_READY).count()
            load_more.click()
            deadline = time.monotonic() + 15.0
            while page.locator(_V2_READY).count() <= prev_count:
                if time.monotonic() >= deadline:
                    return
                time.sleep(0.5)
        yield page.locator("#jobListScreen .gridContent").first.inner_html()


def default_page_iterator(url: str, max_pages: int) -> Iterator[str]:
    """Yields the HTML of each results page from ONE browser session.

    Earlier versions relaunched Chromium and replayed N-1 "next" clicks for
    every page N, so a 20-page board meant 20 cold loads -- and any one slow
    load failed the whole source (issue #153).
    """
    assert_safe_url(url)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page, kind = _open_board(browser, url)
            iter_pages = _iter_v1_pages if kind == "v1" else _iter_v2_pages
            yield from iter_pages(page, max_pages)
        finally:
            browser.close()


def fetch(source: InforSource, page_iterator=default_page_iterator) -> list[Job]:
    # Any failure propagates (source marked failed) rather than returning the
    # pages read so far: a partial result would make reconcile_jobs mark the
    # unread pages' jobs as removed.
    all_jobs: list[Job] = []
    pages = page_iterator(source.url, source.max_pages)
    try:
        for html in pages:
            page_jobs = _parse_page(html, source)
            if not page_jobs:
                break
            all_jobs.extend(page_jobs)
    finally:
        close = getattr(pages, "close", None)
        if close is not None:
            close()
    return list({job.key: job for job in all_jobs}.values())
