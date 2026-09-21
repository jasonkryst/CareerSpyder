import os

import psycopg
from pydantic import TypeAdapter

from app import db
from app.config import SourceConfig
from app.models import Job

_ta = TypeAdapter(SourceConfig)


def _admin_user_id() -> str:
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    row = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    conn.close()
    return str(row[0])


def _seed_source(source_data: dict) -> None:
    user_id = _admin_user_id()
    source = _ta.validate_python(source_data)
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    db.add_source(conn, user_id, source)
    conn.close()


def _save_job(key, title, source_id="src-1", source_name="Acme Board"):
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    run_id = db.start_run(conn)
    db.save_jobs(conn, [Job(key=key, title=title, url=f"https://example.com/job/{key}",
                             source_name=source_name, source_id=source_id)], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])
    return conn


def test_marking_a_job_duplicate_shows_toast_and_dims_row(live_server, page):
    _save_job("e2e-dup-1", "E2E Duplicate Job")

    page.goto(live_server + "/jobs")
    row = page.locator("tr", has_text="E2E Duplicate Job")
    row.locator(".duplicate-btn").click()

    page.locator("#duplicate-modal").wait_for(state="visible")
    page.locator("#duplicate-save-btn").click()

    page.wait_for_selector(".toast")
    assert "duplicate" in page.locator(".toast").inner_text().lower()

    # Row stays in DOM (no reload), dimmed via filter-mismatch class
    row = page.locator("tr", has_text="E2E Duplicate Job")
    assert row.count() == 1
    assert "filter-mismatch" in (row.get_attribute("class") or "")


def test_duplicate_modal_accepts_reference_text(live_server, page):
    conn = _save_job("e2e-dup-2", "E2E Duplicate With Ref")

    page.goto(live_server + "/jobs")
    row = page.locator("tr", has_text="E2E Duplicate With Ref")
    row.locator(".duplicate-btn").click()

    page.locator("#duplicate-modal").wait_for(state="visible")
    page.locator("#duplicate-of-input").fill("Acme — Engineer (Greenhouse)")
    page.locator("#duplicate-save-btn").click()

    # The modal's submit is JS-intercepted (fetch, no navigation) -- the URL
    # never changes, so waiting on it doesn't wait for the request to finish.
    # Wait for the toast that only appears once the fetch resolves instead.
    page.wait_for_selector(".toast")

    rows = db.list_jobs(conn, duplicates="only")
    match = next((r for r in rows if r["key"] == "e2e-dup-2"), None)
    assert match is not None
    assert match["duplicate_of"] == "Acme — Engineer (Greenhouse)"


def test_clearing_duplicate_flag_restores_job(live_server, page):
    conn = _save_job("e2e-dup-3", "E2E Clearable Duplicate")
    db.set_job_duplicate(conn, "e2e-dup-3")

    page.goto(live_server + "/jobs?duplicates=only")
    row = page.locator("tr", has_text="E2E Clearable Duplicate")
    row.locator(".duplicate-btn").click()

    page.locator("#duplicate-modal").wait_for(state="visible")
    page.locator("#duplicate-clear-btn").click()

    page.wait_for_selector(".toast")
    page.goto(live_server + "/jobs")
    assert page.locator("tr", has_text="E2E Clearable Duplicate").count() == 1


def test_secondary_source_badge_appears_for_secondary_source_jobs(live_server, page):
    _seed_source({"id": "src-secondary", "name": "Indeed E2E", "type": "indeed",
                  "url": "https://indeed.test/jobs", "secondary": True,
                  "include_keywords": [], "exclude_keywords": []})

    _save_job("e2e-secondary-1", "E2E Secondary Job",
              source_id="src-secondary", source_name="Indeed E2E")

    page.goto(live_server + "/jobs")
    row = page.locator("tr", has_text="E2E Secondary Job")
    assert row.locator(".badge-secondary").count() == 1


def test_non_secondary_source_has_no_badge(live_server, page):
    _seed_source({"id": "src-primary", "name": "Greenhouse E2E", "type": "greenhouse",
                  "board_token": "acme", "secondary": False,
                  "include_keywords": [], "exclude_keywords": []})

    _save_job("e2e-primary-1", "E2E Primary Job",
              source_id="src-primary", source_name="Greenhouse E2E")

    page.goto(live_server + "/jobs")
    row = page.locator("tr", has_text="E2E Primary Job")
    assert row.locator(".badge-secondary").count() == 0
