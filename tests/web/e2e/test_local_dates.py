import os

from app import db
from app.models import Job


def test_jobs_page_date_found_is_reformatted_from_raw_iso(live_server, page):
    conn = db.init_db(os.environ["CAREERSPYDER_DB_PATH"])
    job = Job(key="e2e-local-dates", title="E2E Local Dates Job", url="https://example.com/job/e2e-local-dates")
    run_id = db.start_run(conn)
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])
    raw_iso = db.list_jobs(conn)[0]["first_seen_at"]

    page.goto(live_server + "/jobs")
    row = page.locator("tr", has_text="E2E Local Dates Job")
    cell_text = row.locator('td[data-label="Date found"]').inner_text()

    assert cell_text != raw_iso
    assert "T" not in cell_text


def test_dashboard_run_history_reformats_after_refresh(live_server, page):
    page.goto(live_server + "/")

    page.route("**/rows*", lambda route: route.fulfill(
        status=200,
        content_type="text/html",
        body='<div id="history-rows" data-page="1"><div class="table-scroll"><table>'
             '<tr><th scope="col">Started</th></tr>'
             '<tr><td data-label="Started"><time datetime="2026-08-16T00:00:00+00:00">'
             '2026-08-16T00:00:00+00:00</time></td></tr>'
             '</table></div><nav aria-label="Pagination"><span>Page 1 of 1</span></nav></div>',
    ))

    page.click("#refresh-history")
    page.wait_for_function(
        "document.querySelector('td[data-label=\"Started\"]')?.textContent.trim() "
        "!== '2026-08-16T00:00:00+00:00'"
    )

    cell_text = page.inner_text('td[data-label="Started"]')
    assert "T" not in cell_text
