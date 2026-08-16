import os

from app import db
from app.models import Job


def test_toast_appears_after_deleting_a_source_and_can_be_dismissed(live_server, page):
    page.goto(live_server + "/sources/new")
    page.fill('input[name="name"]', "Toast Test Source")
    page.select_option('select[name="type"]', "greenhouse")
    page.fill('input[name="board_token"]', "toast-test")
    page.click('button[type="submit"]')
    page.wait_for_url("**/sources")

    row = page.locator("tr", has_text="Toast Test Source")
    row.locator('form[action$="/delete"] button[type="submit"]').click()
    page.click("#confirm-modal-confirm")
    page.wait_for_selector(".toast")

    assert page.locator(".toast").inner_text().strip().startswith("Source deleted.")

    page.click(".toast-close")
    page.wait_for_selector(".toast", state="detached")


def test_toast_auto_dismisses_without_manual_close(live_server, page):
    page.goto(live_server + "/settings/email")
    page.fill('input[name="smtp_host"]', "smtp.example.com")
    page.fill('input[name="smtp_port"]', "587")
    page.fill('input[name="smtp_user"]', "user")
    page.fill('input[name="email_from"]', "from@x.test")
    page.click('button[type="submit"]')

    page.wait_for_selector(".toast")
    page.wait_for_selector(".toast", state="detached", timeout=8000)


def test_clicking_job_title_opens_a_new_tab_to_the_job_url(live_server, page):
    conn = db.init_db(os.environ["CAREERSPYDER_DB_PATH"])
    job = Job(key="e2e-external-link", title="E2E External Link Job",
              url="https://example.com/job/e2e-external-link")
    run_id = db.start_run(conn)
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])

    page.context.route("https://example.com/**", lambda route: route.fulfill(
        status=200, content_type="text/html", body="<html><body>stub</body></html>",
    ))

    page.goto(live_server + "/jobs")
    with page.context.expect_page() as new_page_info:
        page.click("text=E2E External Link Job")
    new_page = new_page_info.value
    new_page.wait_for_load_state()

    assert new_page.url == "https://example.com/job/e2e-external-link"
    assert new_page != page
    new_page.close()
