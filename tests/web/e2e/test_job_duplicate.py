import json
import os

from app import db
from app.models import Job


def _save_job(key, title, source_id="src-1", source_name="Acme Board"):
    conn = db.init_db(os.environ["CAREERSPYDER_DB_PATH"])
    run_id = db.start_run(conn)
    db.save_jobs(conn, [Job(key=key, title=title, url=f"https://example.com/job/{key}",
                             source_name=source_name, source_id=source_id)], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])
    return conn


def test_marking_a_job_duplicate_hides_it_and_shows_toast(live_server, page):
    _save_job("e2e-dup-1", "E2E Duplicate Job")

    page.goto(live_server + "/jobs")
    row = page.locator("tr", has_text="E2E Duplicate Job")
    row.locator(".duplicate-btn").click()

    page.locator("#duplicate-modal").wait_for(state="visible")
    page.locator("#duplicate-save-btn").click()

    page.wait_for_selector(".toast")
    assert "duplicate" in page.locator(".toast").inner_text().lower()

    page.wait_for_url(lambda url: "/jobs" in url)
    assert page.locator("tr", has_text="E2E Duplicate Job").count() == 0


def test_duplicate_modal_accepts_reference_text(live_server, page):
    conn = _save_job("e2e-dup-2", "E2E Duplicate With Ref")

    page.goto(live_server + "/jobs")
    row = page.locator("tr", has_text="E2E Duplicate With Ref")
    row.locator(".duplicate-btn").click()

    page.locator("#duplicate-modal").wait_for(state="visible")
    page.locator("#duplicate-of-input").fill("Acme — Engineer (Greenhouse)")
    page.locator("#duplicate-save-btn").click()

    page.wait_for_url(lambda url: "/jobs" in url)

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

    page.wait_for_url(lambda url: "/jobs" in url)
    page.goto(live_server + "/jobs")
    assert page.locator("tr", has_text="E2E Clearable Duplicate").count() == 1


def test_secondary_source_badge_appears_for_secondary_source_jobs(live_server, page):
    sources_path = os.environ["CAREERSPYDER_SOURCES_PATH"]
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "src-secondary", "name": "Indeed E2E", "type": "indeed",
             "url": "https://indeed.test/jobs", "secondary": True,
             "include_keywords": [], "exclude_keywords": []},
        ]}, f)

    _save_job("e2e-secondary-1", "E2E Secondary Job",
              source_id="src-secondary", source_name="Indeed E2E")

    page.goto(live_server + "/jobs")
    row = page.locator("tr", has_text="E2E Secondary Job")
    assert row.locator(".badge-secondary").count() == 1


def test_non_secondary_source_has_no_badge(live_server, page):
    sources_path = os.environ["CAREERSPYDER_SOURCES_PATH"]
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "src-primary", "name": "Greenhouse E2E", "type": "greenhouse",
             "board_token": "acme", "secondary": False,
             "include_keywords": [], "exclude_keywords": []},
        ]}, f)

    _save_job("e2e-primary-1", "E2E Primary Job",
              source_id="src-primary", source_name="Greenhouse E2E")

    page.goto(live_server + "/jobs")
    row = page.locator("tr", has_text="E2E Primary Job")
    assert row.locator(".badge-secondary").count() == 0
