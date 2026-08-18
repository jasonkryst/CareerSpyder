import os
from urllib.parse import quote

from app import db
from app.models import Job


def test_job_map_shows_a_marker_with_a_job_popup(live_server, page):
    conn = db.init_db(os.environ["CAREERSPYDER_DB_PATH"])
    job = Job(key="e2e-map-job", title="E2E Map Job", url="https://example.com/job/e2e-map-job",
              company="Acme", source_name="Acme Board", location="E2E Test City")
    run_id = db.start_run(conn)
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'E2E Test City', "
        "lat = 41.8, lng = -87.6 WHERE location = 'E2E Test City'"
    )
    conn.commit()

    # Filtered by location so this test's marker is isolated from other e2e tests sharing
    # the same session-scoped live_server/DB -- otherwise two nearby markers could cluster
    # into one bubble at the map's default low zoom, breaking the single-marker assumption.
    page.goto(live_server + "/jobs/map?location=" + quote("E2E Test City"))
    page.wait_for_selector(".leaflet-marker-icon")
    page.locator(".leaflet-marker-icon").click()

    page.wait_for_selector(".leaflet-popup")
    popup_text = page.locator(".leaflet-popup").inner_text()
    assert "E2E Map Job" in popup_text
    assert "Acme" in popup_text


def test_job_map_popup_escapes_a_title_containing_html_and_quote_characters(live_server, page):
    conn = db.init_db(os.environ["CAREERSPYDER_DB_PATH"])
    job = Job(key="e2e-map-xss-job", title='<img src=x onerror=alert(1)>"Weird" Title',
              url="https://example.com/job/e2e-map-xss-job", company="Acme",
              source_name="Acme Board", location="E2E XSS City")
    run_id = db.start_run(conn)
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', display_name = 'E2E XSS City', "
        "lat = 40.0, lng = -90.0 WHERE location = 'E2E XSS City'"
    )
    conn.commit()

    page.goto(live_server + "/jobs/map?location=" + quote("E2E XSS City"))
    page.wait_for_selector(".leaflet-marker-icon")
    page.locator(".leaflet-marker-icon").click()

    page.wait_for_selector(".leaflet-popup")
    popup = page.locator(".leaflet-popup")
    assert popup.locator("img").count() == 0
    assert '"Weird" Title' in popup.inner_text()
    link_href = popup.locator("li a").get_attribute("href")
    assert link_href == "https://example.com/job/e2e-map-xss-job"
