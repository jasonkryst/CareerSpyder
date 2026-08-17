import os

from app import db
from app.models import Job


def test_marking_a_job_applied_shows_toast_and_history(live_server, page):
    conn = db.init_db(os.environ["CAREERSPYDER_DB_PATH"])
    job = Job(key="e2e-status-job", title="E2E Status Job", url="https://example.com/job/e2e-status-job")
    run_id = db.start_run(conn)
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])

    page.goto(live_server + "/jobs")
    row = page.locator("tr", has_text="E2E Status Job")
    row.locator('select[name="status"]').select_option("applied")

    page.wait_for_selector(".toast")
    assert page.locator(".toast").inner_text().strip().startswith("Marked as Applied.")

    row = page.locator("tr", has_text="E2E Status Job")
    row.locator("summary", has_text="History").click()
    assert "Applied" in row.locator(".status-history").inner_text()
