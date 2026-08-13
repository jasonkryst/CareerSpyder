# Infor Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `infor` as a sixth CareerSpyder source type so Infor Global HR job boards (e.g. Rush University Medical Center) can be scraped like any other source.

**Architecture:** A new `InforSource` config model plus a new `app/adapters/infor.py` that drives Playwright directly (not the shared `browser.render_html()` helper) to reach content nested in a same-origin iframe (`#parentIframe`), parse a page of `.inforCardstackCell` cards, and paginate up to a configurable `max_pages` via `button.nextPage`. The real Playwright/pagination mechanics are injectable and untested (matching `browser.render_html()`'s existing precedent); the parsing logic and pagination-loop control flow are fully unit tested with fixtures.

**Tech Stack:** Same as the rest of the project — Python 3.12, Pydantic v2, BeautifulSoup4, Playwright (sync API), pytest.

## Global Constraints

- Tests must not make live network calls or launch a real browser (existing project-wide constraint) — `infor.fetch()` takes an injectable `frame_fetcher` for this reason, same pattern as every other adapter's injectable I/O.
- No stable per-job identifier or URL exists on this platform (confirmed via live investigation, documented in the design spec) — `Job.key` is a hash-free composite of `company + title + location` (matching `generic_html`/`linkedin`/`indeed`'s existing pattern), and `Job.url` is the listing page itself, not a per-posting link. This is a deliberate, permanent limitation of the platform, not a bug to fix later.
- `max_pages` defaults to 3; page size is not configurable (fixed at the site's default of 10 to avoid SlickGrid's row virtualization).
- The job-content iframe is located via `#parentIframe` (a stable id/name, confirmed via live inspection) — never by positional index.
- Pagination uses `button.nextPage[title="Next"]`; its `disabled` DOM property signals no further pages.
- Design spec: `docs/superpowers/specs/2026-08-13-infor-adapter-design.md`.

---

### Task 1: `InforSource` config model

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `BaseSource` (existing).
- Produces: `InforSource` (pydantic model: `type: Literal["infor"]`, `url: str` non-empty, `max_pages: int = 3`), added to the `SourceConfig` discriminated union so `config.load_sources`/`save_sources`/etc. all handle it automatically.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py` (after `test_selectors_reject_empty_job_card`):

```python
def test_infor_rejects_empty_url():
    with pytest.raises(ValidationError):
        config.InforSource(name="Rush", type="infor", url="")


def test_infor_max_pages_defaults_to_three():
    source = config.InforSource(name="Rush", type="infor", url="https://rush.test/careers")
    assert source.max_pages == 3
```

Also add an `infor` entry to `test_load_sources_parses_each_type`'s fixture list and assertion:

```python
def test_load_sources_parses_each_type(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [
        {"id": "s1", "name": "Acme (Greenhouse)", "type": "greenhouse", "board_token": "acme"},
        {"id": "s2", "name": "Beta (Lever)", "type": "lever", "board_token": "beta"},
        {
            "id": "s3", "name": "Custom Co", "type": "generic_html",
            "url": "https://customco.test/careers",
            "selectors": {"job_card": ".job", "title": ".t", "link": "a"},
        },
        {"id": "s4", "name": "LinkedIn", "type": "linkedin", "url": "https://linkedin.test/jobs"},
        {"id": "s5", "name": "Indeed", "type": "indeed", "url": "https://indeed.test/jobs"},
        {"id": "s6", "name": "Rush (Infor)", "type": "infor", "url": "https://rush.test/careers", "max_pages": 5},
    ])

    sources = config.load_sources(str(path))

    assert [s.type for s in sources] == [
        "greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor",
    ]
    assert sources[0].board_token == "acme"
    assert sources[2].selectors.job_card == ".job"
    assert sources[5].max_pages == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: module 'app.config' has no attribute 'InforSource'`.

- [ ] **Step 3: Add `InforSource` to `app/config.py`**

Change:

```python
class IndeedSource(BaseSource):
    type: Literal["indeed"]
    url: str = Field(min_length=1)


SourceConfig = Annotated[
    GreenhouseSource | LeverSource | GenericHtmlSource | LinkedInSource | IndeedSource,
    Field(discriminator="type"),
]
```

to:

```python
class IndeedSource(BaseSource):
    type: Literal["indeed"]
    url: str = Field(min_length=1)


class InforSource(BaseSource):
    type: Literal["infor"]
    url: str = Field(min_length=1)
    max_pages: int = 3


SourceConfig = Annotated[
    GreenhouseSource | LeverSource | GenericHtmlSource | LinkedInSource | IndeedSource | InforSource,
    Field(discriminator="type"),
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: all pass (10 tests).

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add InforSource config model"
```

---

### Task 2: `infor` adapter — parsing logic and pagination loop

**Files:**
- Create: `app/adapters/infor.py`
- Create: `tests/adapters/test_infor.py`

**Interfaces:**
- Consumes: `Job` (existing), `InforSource` (Task 1).
- Produces: `infor.fetch(source: InforSource, frame_fetcher=default_frame_fetcher) -> list[Job]` — registered in Task 3's `ADAPTERS` dict, dispatched exactly like every other adapter.

**Context:** Real card HTML, confirmed via live inspection of the Rush board:

```html
<div class="inforCardstackCell">
  <span class="inforCardstackImg hotJobsSpan"></span>
  <span class="inforCardstackHeading">Anesthesia Tech 1</span>
  <div class="floatRight PostedDiv">
    <label class="inforCardstackLabel PostedLbl">Posted</label>
    <label class="inforCardstackValue">08/12/2026</label>
  </div>
  <br>
  <label class="inforCardstackLabel LocationLbl">Location</label>
  <label class="inforCardstackValue">US:IL:Chicago</label>
</div>
```

There are two `.inforCardstackValue` labels per card — the posted date is the one inside `.PostedDiv`; the location is the one that's a direct next-sibling of `.LocationLbl`.

- [ ] **Step 1: Create `tests/adapters/test_infor.py` with the failing tests**

```python
from app.adapters import infor
from app.config import InforSource

PAGE_1_HTML = """
<div class="inforCardstackCell">
  <span class="inforCardstackHeading">Anesthesia Tech 1</span>
  <div class="floatRight PostedDiv">
    <label class="inforCardstackLabel PostedLbl">Posted</label>
    <label class="inforCardstackValue">08/12/2026</label>
  </div>
  <br>
  <label class="inforCardstackLabel LocationLbl">Location</label>
  <label class="inforCardstackValue">US:IL:Chicago</label>
</div>
<div class="inforCardstackCell">
  <span class="inforCardstackHeading">Supply Chain MDM Analyst</span>
  <div class="floatRight PostedDiv">
    <label class="inforCardstackLabel PostedLbl">Posted</label>
    <label class="inforCardstackValue">08/11/2026</label>
  </div>
  <br>
  <label class="inforCardstackLabel LocationLbl">Location</label>
  <label class="inforCardstackValue">US:IL:Chicago</label>
</div>
"""

PAGE_2_HTML = """
<div class="inforCardstackCell">
  <span class="inforCardstackHeading">Physical Therapist</span>
  <div class="floatRight PostedDiv">
    <label class="inforCardstackLabel PostedLbl">Posted</label>
    <label class="inforCardstackValue">08/10/2026</label>
  </div>
  <br>
  <label class="inforCardstackLabel LocationLbl">Location</label>
  <label class="inforCardstackValue">US:IL:Oak Park</label>
</div>
"""

CARD_MISSING_POSTED_AND_LOCATION = """
<div class="inforCardstackCell">
  <span class="inforCardstackHeading">Bare Title Only</span>
</div>
"""


def make_source(max_pages=3):
    return InforSource(
        id="s1", name="Rush (Infor)", company="Rush University Medical Center",
        type="infor", url="https://rush.test/careers", max_pages=max_pages,
    )


def test_fetch_parses_single_page_of_cards():
    def fake_fetcher(url, page_number):
        assert url == "https://rush.test/careers"
        return PAGE_1_HTML if page_number == 1 else None

    jobs = infor.fetch(make_source(), frame_fetcher=fake_fetcher)

    assert len(jobs) == 2
    assert jobs[0].title == "Anesthesia Tech 1"
    assert jobs[0].posted_date == "08/12/2026"
    assert jobs[0].location == "US:IL:Chicago"
    assert jobs[0].company == "Rush University Medical Center"
    assert jobs[0].url == "https://rush.test/careers"
    assert jobs[0].source_name == "Rush (Infor)"
    assert jobs[1].title == "Supply Chain MDM Analyst"


def test_fetch_paginates_up_to_max_pages():
    calls = []

    def fake_fetcher(url, page_number):
        calls.append(page_number)
        if page_number == 1:
            return PAGE_1_HTML
        if page_number == 2:
            return PAGE_2_HTML
        return None  # would be page 3, but max_pages=2 stops us first

    jobs = infor.fetch(make_source(max_pages=2), frame_fetcher=fake_fetcher)

    assert calls == [1, 2]
    assert [j.title for j in jobs] == ["Anesthesia Tech 1", "Supply Chain MDM Analyst", "Physical Therapist"]


def test_fetch_stops_early_when_frame_fetcher_returns_none():
    def fake_fetcher(url, page_number):
        return PAGE_1_HTML if page_number == 1 else None

    jobs = infor.fetch(make_source(max_pages=5), frame_fetcher=fake_fetcher)

    assert len(jobs) == 2  # only page 1's cards, even though max_pages allows up to 5


def test_fetch_stops_when_a_page_has_zero_cards():
    def fake_fetcher(url, page_number):
        if page_number == 1:
            return PAGE_1_HTML
        return "<div>no cards here</div>"

    jobs = infor.fetch(make_source(max_pages=5), frame_fetcher=fake_fetcher)

    assert len(jobs) == 2


def test_card_missing_posted_and_location_still_yields_a_job_with_none_fields():
    def fake_fetcher(url, page_number):
        return CARD_MISSING_POSTED_AND_LOCATION if page_number == 1 else None

    jobs = infor.fetch(make_source(), frame_fetcher=fake_fetcher)

    assert len(jobs) == 1
    assert jobs[0].title == "Bare Title Only"
    assert jobs[0].posted_date is None
    assert jobs[0].location is None


def test_job_key_is_stable_across_identical_cards_and_differs_for_different_ones():
    def fake_fetcher(url, page_number):
        return PAGE_1_HTML if page_number == 1 else None

    jobs = infor.fetch(make_source(), frame_fetcher=fake_fetcher)

    assert jobs[0].key != jobs[1].key
    # Re-fetching the identical page must produce the identical key (dedup relies on this).
    jobs_again = infor.fetch(make_source(), frame_fetcher=fake_fetcher)
    assert jobs[0].key == jobs_again[0].key
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/adapters/test_infor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.infor'`.

- [ ] **Step 3: Write `app/adapters/infor.py`**

```python
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
```

(`default_frame_fetcher` is the real Playwright implementation — it is
exercised only by the manual smoke test in Task 5, never by `pytest`,
matching the existing precedent set by `app/adapters/browser.py`'s
`render_html()`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/adapters/test_infor.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/adapters/infor.py tests/adapters/test_infor.py
git commit -m "feat: add Infor adapter with paginated card parsing"
```

---

### Task 3: Register the adapter

**Files:**
- Modify: `app/adapters/__init__.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `infor.fetch` (Task 2).
- Produces: `ADAPTERS["infor"]` — the orchestrator and `/sources/test-preview` both dispatch through this dict already, so registering here is what makes `infor` sources actually runnable end-to-end.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py` (near the top, alongside other adapter-registry-shape assertions if any exist — otherwise as a new small test):

```python
def test_infor_adapter_is_registered():
    from app.adapters import ADAPTERS
    assert "infor" in ADAPTERS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py::test_infor_adapter_is_registered -v`
Expected: FAIL — `AssertionError`.

- [ ] **Step 3: Register `infor` in `app/adapters/__init__.py`**

Change:

```python
from collections.abc import Callable

from app.adapters import generic_html, greenhouse, indeed, lever, linkedin
from app.models import Job

ADAPTERS: dict[str, Callable[..., list[Job]]] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "generic_html": generic_html.fetch,
    "linkedin": linkedin.fetch,
    "indeed": indeed.fetch,
}
```

to:

```python
from collections.abc import Callable

from app.adapters import generic_html, greenhouse, indeed, infor, lever, linkedin
from app.models import Job

ADAPTERS: dict[str, Callable[..., list[Job]]] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "generic_html": generic_html.fetch,
    "linkedin": linkedin.fetch,
    "indeed": indeed.fetch,
    "infor": infor.fetch,
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_orchestrator.py -v`
Expected: all pass, including the new test.

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/adapters/__init__.py tests/test_orchestrator.py
git commit -m "feat: register infor adapter"
```

---

### Task 4: Web UI wiring — source form

**Files:**
- Modify: `app/web/source_form.py`
- Modify: `app/web/templates/source_form.html`
- Test: `tests/web/test_source_form_helper.py`
- Test: `tests/web/test_source_form.py`

**Interfaces:**
- Consumes: `InforSource` (Task 1).
- Produces: `/sources/new` and `/sources/{id}/edit` support `type=infor` end to end (add, edit, validation-error round-trip, and — automatically, since it dispatches through `ADAPTERS` generically — "Test this source").

**Context — a deliberate deviation from the existing pattern:** `generic_html`, `linkedin`, and `indeed` currently all share a *single* `name="url"` `<input>` that physically lives inside the `fields-generic_html` div; `fields-linkedin` and `fields-indeed` are empty divs that rely on that shared (and, once another type is selected, CSS-hidden) input still being present in the DOM and still submitting its value. That's an existing latent UX rough edge (a user who selects "linkedin" without ever having had `fields-generic_html` visible has no visible field to type a URL into) — real, but out of scope to fix here for types that already ship. Rather than inherit the same rough edge for a *new* type, `infor` gets a fully self-contained field block with its own uniquely-named `infor_url` input, so the URL field is always visible and editable whenever "infor" is selected, with no dependency on another type's hidden input.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_source_form_helper.py` (after `test_preserves_existing_id_when_provided`):

```python
def test_parses_infor_fields():
    form = {
        "type": "infor", "name": "Rush (Infor)", "company": "Rush University Medical Center",
        "infor_url": "https://rush.test/careers", "max_pages": "5",
        "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.type == "infor"
    assert source.url == "https://rush.test/careers"
    assert source.max_pages == 5


def test_infor_max_pages_defaults_when_field_blank():
    form = {
        "type": "infor", "name": "Rush (Infor)", "infor_url": "https://rush.test/careers",
        "max_pages": "", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.max_pages == 3
```

Add to `tests/web/test_source_form.py` (after `test_post_edit_updates_existing_source`):

```python
def test_post_new_infor_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "infor", "name": "Rush (Infor)", "company": "Rush University Medical Center",
        "infor_url": "https://rush.test/careers", "max_pages": "5",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["type"] == "infor"
    assert saved[0]["url"] == "https://rush.test/careers"
    assert saved[0]["max_pages"] == 5


def test_post_new_infor_source_with_empty_url_shows_error_and_does_not_save(client):
    resp = client.post("/sources/new", data={
        "type": "infor", "name": "Rush (Infor)", "infor_url": "",
        "include_keywords": "", "exclude_keywords": "",
    })

    assert resp.status_code == 400
    with open(client.app.state.sources_path) as f:
        assert json.load(f)["sources"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/web/test_source_form_helper.py tests/web/test_source_form.py -v -k infor`
Expected: FAIL — `pydantic_core.ValidationError` (unknown `type` discriminator "infor") or `KeyError`.

- [ ] **Step 3: Wire `InforSource` into `app/web/source_form.py`**

Change:

```python
from types import SimpleNamespace

from pydantic import BaseModel

from app.config import (
    GenericHtmlSource,
    GreenhouseSource,
    IndeedSource,
    LeverSource,
    LinkedInSource,
    Selectors,
)

TYPE_MODELS: dict[str, type[BaseModel]] = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "generic_html": GenericHtmlSource,
    "linkedin": LinkedInSource,
    "indeed": IndeedSource,
}
```

to:

```python
from types import SimpleNamespace

from pydantic import BaseModel

from app.config import (
    GenericHtmlSource,
    GreenhouseSource,
    IndeedSource,
    InforSource,
    LeverSource,
    LinkedInSource,
    Selectors,
)

TYPE_MODELS: dict[str, type[BaseModel]] = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "generic_html": GenericHtmlSource,
    "linkedin": LinkedInSource,
    "indeed": IndeedSource,
    "infor": InforSource,
}
```

Then change `source_from_form`'s type-branching body from:

```python
    source_type = form["type"]
    if source_type in ("greenhouse", "lever"):
        if "board_token" in form:
            common["board_token"] = _strip(form["board_token"])
    elif source_type == "generic_html":
        if "url" in form:
            common["url"] = _strip(form["url"])
        common["render_js"] = form.get("render_js") == "on"
        common["selectors"] = Selectors(
            job_card=_strip(form.get("selector_job_card", "")),
            title=_strip(form.get("selector_title", "")),
            link=_strip(form.get("selector_link", "")),
            location=_strip(form.get("selector_location", "")) or None,
        )
    else:
        if "url" in form:
            common["url"] = _strip(form["url"])

    model = TYPE_MODELS[source_type]
    return model.model_validate(common)
```

to:

```python
    source_type = form["type"]
    if source_type in ("greenhouse", "lever"):
        if "board_token" in form:
            common["board_token"] = _strip(form["board_token"])
    elif source_type == "generic_html":
        if "url" in form:
            common["url"] = _strip(form["url"])
        common["render_js"] = form.get("render_js") == "on"
        common["selectors"] = Selectors(
            job_card=_strip(form.get("selector_job_card", "")),
            title=_strip(form.get("selector_title", "")),
            link=_strip(form.get("selector_link", "")),
            location=_strip(form.get("selector_location", "")) or None,
        )
    elif source_type == "infor":
        if "infor_url" in form:
            common["url"] = _strip(form["infor_url"])
        if form.get("max_pages"):
            common["max_pages"] = int(form["max_pages"])
    else:
        if "url" in form:
            common["url"] = _strip(form["url"])

    model = TYPE_MODELS[source_type]
    return model.model_validate(common)
```

Then change `echo_source` from:

```python
def echo_source(form: dict):
    """Build a lenient, unvalidated view of submitted form data so the form
    template can be re-rendered with the user's input preserved after a
    validation error (instead of losing it)."""
    selectors = SimpleNamespace(
        job_card=form.get("selector_job_card", ""),
        title=form.get("selector_title", ""),
        link=form.get("selector_link", ""),
        location=form.get("selector_location") or None,
    )
    return SimpleNamespace(
        id=form.get("id", ""),
        name=form.get("name", ""),
        company=form.get("company") or None,
        type=form.get("type", ""),
        board_token=form.get("board_token", ""),
        url=form.get("url", ""),
        render_js=form.get("render_js") == "on",
        selectors=selectors,
        include_keywords=_keywords(form.get("include_keywords", "")),
        exclude_keywords=_keywords(form.get("exclude_keywords", "")),
    )
```

to:

```python
def echo_source(form: dict):
    """Build a lenient, unvalidated view of submitted form data so the form
    template can be re-rendered with the user's input preserved after a
    validation error (instead of losing it)."""
    selectors = SimpleNamespace(
        job_card=form.get("selector_job_card", ""),
        title=form.get("selector_title", ""),
        link=form.get("selector_link", ""),
        location=form.get("selector_location") or None,
    )
    url = form.get("infor_url", "") if form.get("type") == "infor" else form.get("url", "")
    return SimpleNamespace(
        id=form.get("id", ""),
        name=form.get("name", ""),
        company=form.get("company") or None,
        type=form.get("type", ""),
        board_token=form.get("board_token", ""),
        url=url,
        render_js=form.get("render_js") == "on",
        selectors=selectors,
        max_pages=form.get("max_pages", ""),
        include_keywords=_keywords(form.get("include_keywords", "")),
        exclude_keywords=_keywords(form.get("exclude_keywords", "")),
    )
```

- [ ] **Step 4: Add the `infor` type option and fields to `app/web/templates/source_form.html`**

Change:

```html
    <select name="type" onchange="showFieldsFor(this.value)">
      {% for t in ["greenhouse", "lever", "generic_html", "linkedin", "indeed"] %}
      <option value="{{ t }}" {% if source and source.type == t %}selected{% endif %}>{{ t }}</option>
      {% endfor %}
    </select>
```

to:

```html
    <select name="type" onchange="showFieldsFor(this.value)">
      {% for t in ["greenhouse", "lever", "generic_html", "linkedin", "indeed", "infor"] %}
      <option value="{{ t }}" {% if source and source.type == t %}selected{% endif %}>{{ t }}</option>
      {% endfor %}
    </select>
```

Change:

```html
  <div id="fields-linkedin" class="type-fields"></div>
  <div id="fields-indeed" class="type-fields"></div>
```

to:

```html
  <div id="fields-linkedin" class="type-fields"></div>
  <div id="fields-indeed" class="type-fields"></div>
  <div id="fields-infor" class="type-fields">
    <label>URL <input type="text" name="infor_url" value="{{ source.url if source and source.type == 'infor' else '' }}"></label><br>
    <label>Max pages <input type="number" name="max_pages" value="{{ source.max_pages if source and source.type == 'infor' else 3 }}"></label>
  </div>
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/web/test_source_form_helper.py tests/web/test_source_form.py -v`
Expected: all pass.

- [ ] **Step 6: Run the full suite to confirm no regression**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/web/source_form.py app/web/templates/source_form.html tests/web/test_source_form_helper.py tests/web/test_source_form.py
git commit -m "feat: add infor source type to the web UI form"
```

---

### Task 5: Manual smoke test and documentation

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: a verified-working `infor` source type, documented for users and future maintainers.

**Note for whoever executes this task:** Step 1 drives a real browser against a real, live third-party website (a real hospital system's careers page). Keep the request volume trivial (one source, `max_pages: 1`, a single manual run) — this is a one-time verification, not a load test, and the site is someone else's production infrastructure.

- [ ] **Step 1: Manual smoke test against the real Rush board**

1. Ensure `playwright install --with-deps chromium` has been run in this environment.
2. In a scratch Python shell or a throwaway script, run:
   ```python
   from app.adapters import infor
   from app.config import InforSource

   source = InforSource(
       name="Rush (Infor) smoke test",
       company="Rush University Medical Center",
       type="infor",
       url="https://rushprod-lm01.cloud.infor.com:1444/lmghr/CandidateSelfService/controller.servlet?context.dataarea=lmghr&context.session.key.HROrganization=10&context.session.key.JobBoard=RUSHEXTERNAL&context.session.key.noheader=true&rumc=#",
       max_pages=1,
   )
   jobs = infor.fetch(source)
   for j in jobs:
       print(j.title, "|", j.location, "|", j.posted_date)
   print(f"\n{len(jobs)} jobs found")
   ```
3. Expected: 10 jobs printed (page size 10), each with a non-empty title; most with a location and posted date populated (a small number of edge-case postings without one is acceptable, matching what the fixture tests already tolerate).
4. If it hangs or times out: increase the `timeout=15000`/`timeout=30000` values in `app/adapters/infor.py` — this is exactly the kind of real-world timing tuning the design spec flagged as unverifiable without a live run.
5. If it raises a Playwright "element not found" error on `#parentIframe` or `.slick-row`: the site's structure may have changed since this plan was written (2026-08-13) — re-run the DOM inspection steps documented in `docs/superpowers/specs/2026-08-13-infor-adapter-design.md` to find the current selectors.

- [ ] **Step 2: Add a Docker-compatible verification**

Run: `pytest -q` (full suite, one more time, to confirm the whole branch is green together)
Expected: all tests pass.

- [ ] **Step 3: Update `README.md`'s source type documentation**

In the "`sources.json`" section's field-reference table, change:

```markdown
| Type | Required fields | Notes |
|---|---|---|
| `greenhouse`, `lever` | `board_token` | The token in the ATS's board URL, e.g. `boards.greenhouse.io/<board_token>`. |
| `generic_html` | `url`, `selectors.job_card`, `selectors.title`, `selectors.link` | `selectors.location` is optional. Set `render_js: true` if the page needs JavaScript to populate listings (uses headless Chromium instead of a plain HTTP GET). |
| `linkedin`, `indeed` | `url` | Point at a job search results URL. Always uses headless Chromium — see the caveat below. |
```

to:

```markdown
| Type | Required fields | Notes |
|---|---|---|
| `greenhouse`, `lever` | `board_token` | The token in the ATS's board URL, e.g. `boards.greenhouse.io/<board_token>`. |
| `generic_html` | `url`, `selectors.job_card`, `selectors.title`, `selectors.link` | `selectors.location` is optional. Set `render_js: true` if the page needs JavaScript to populate listings (uses headless Chromium instead of a plain HTTP GET). |
| `linkedin`, `indeed` | `url` | Point at a job search results URL. Always uses headless Chromium — see the caveat below. |
| `infor` | `url` | For employers on Infor's Global HR / CandidateSelfService platform. `url` is the full listing page URL. `max_pages` (default 3) bounds how many pages of results are crawled per run — the board is sorted newest-first by default, so this captures the newest postings without a slow full-catalog crawl. There is no per-job link on this platform (confirmed via direct investigation): the digest links to the listing page itself, not the individual posting. |
```

- [ ] **Step 4: Add a CHANGELOG entry**

In `CHANGELOG.md`'s `[Unreleased]` → `### Added` section, add:

```markdown
- `infor` source type, for employers on Infor's Global HR /
  CandidateSelfService platform (e.g. Rush University Medical Center).
  Drives Playwright directly to reach job listings nested in a
  same-origin iframe and paginated via a JS grid — no public API or
  static HTML is available on this platform. No per-job link exists on
  this platform; the digest links to the listing page itself.
```

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: document the infor source type"
```

---

## Self-Review Notes

- **Spec coverage:** every section of `docs/superpowers/specs/2026-08-13-infor-adapter-design.md` maps to a task — config schema (Task 1), card HTML parsing + pagination loop + real Playwright fetcher (Task 2), `ADAPTERS` registration (Task 3), web UI wiring (Task 4), manual smoke test + docs (Task 5).
- **Placeholder scan:** none — every code block is complete, real content; the smoke-test script in Task 5 is a real, runnable script, not a description of one.
- **Type consistency:** `InforSource` (Task 1) is imported identically in `app/adapters/infor.py` (Task 2), `app/adapters/__init__.py` (Task 3), and `app/web/source_form.py` (Task 4). `infor.fetch`'s signature (`source: InforSource, frame_fetcher=default_frame_fetcher`) matches how it's registered in `ADAPTERS` (called positionally with just `source`, matching every other adapter's calling convention already used by `orchestrator.py` and `routes_sources.py`) and matches the fixture tests in Task 2.
- **Deliberate deviation flagged, not silently introduced:** Task 4's `infor_url` field name (rather than reusing the shared `url` name) is called out explicitly as a considered choice, with the pre-existing rough edge it avoids named directly, not fixed (out of scope) but not replicated either.
