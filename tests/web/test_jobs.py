from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from app import db
from app.models import Job
from app.web.routes_jobs import _age_days


def make_job(key="k1", title="Engineer", url="https://x.test/1", company="Acme",
             location="Remote", source_name="Acme Board", source_id="src-1", summary="A great role."):
    return Job(key=key, title=title, url=url, company=company, location=location,
               source_name=source_name, source_id=source_id, summary=summary)


def test_age_days_uses_today_when_not_removed():
    first_seen = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    assert _age_days(first_seen, None) == 5


def test_age_days_uses_removed_at_when_present():
    first_seen = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    removed_at = datetime(2026, 1, 10, tzinfo=UTC).isoformat()
    assert _age_days(first_seen, removed_at) == 9


def test_jobs_page_empty_state(client):
    resp = client.get("/jobs")

    assert resp.status_code == 200
    assert "Jobs" in resp.text


def test_jobs_page_lists_active_job(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job()], db.start_run(conn))

    resp = client.get("/jobs")

    assert resp.status_code == 200
    assert "Acme" in resp.text
    assert "Acme Board" in resp.text
    assert "Engineer" in resp.text
    assert 'href="https://x.test/1"' in resp.text
    assert "A great role." in resp.text
    assert "Not sent" in resp.text


def test_jobs_page_shows_removed_date_and_class_for_a_removed_job(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k2", source_id="src-2")], db.start_run(conn))
    db.reconcile_jobs(conn, configured_source_ids=set(), succeeded_source_ids={"src-2"}, found_jobs=[])
    removed_at = db.list_jobs(conn)[0]["removed_at"]
    assert removed_at is not None

    resp = client.get("/jobs")

    assert removed_at in resp.text
    assert 'class="removed"' in resp.text


def test_jobs_page_shows_emailed_timestamp(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k3")], db.start_run(conn))
    db.mark_emailed(conn, ["k3"])
    emailed_at = db.list_jobs(conn)[0]["emailed_at"]

    resp = client.get("/jobs")

    assert emailed_at in resp.text


def test_jobs_page_title_link_opens_in_new_tab_with_icon(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job()], db.start_run(conn))

    resp = client.get("/jobs")

    assert 'target="_blank"' in resp.text
    assert 'rel="noopener noreferrer"' in resp.text
    assert "&#8599;" in resp.text
    assert "(opens in new tab)" in resp.text


def test_jobs_page_internal_nav_link_is_not_target_blank(client):
    resp = client.get("/jobs")

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    nav_jobs_link = soup.select_one('nav[aria-label="Main"] a[href="/jobs"]')

    assert nav_jobs_link is not None
    assert nav_jobs_link.get("target") is None


def test_jobs_page_second_page_shows_older_jobs(client):
    conn = client.app.state.conn
    jobs = [make_job(key=f"k{i}", title=f"Job {i}") for i in range(30)]
    db.save_jobs(conn, jobs, db.start_run(conn))

    page1 = client.get("/jobs?page=1")
    page2 = client.get("/jobs?page=2")

    assert "Page 1 of 2" in page1.text
    assert "Page 2 of 2" in page2.text


def test_jobs_page_invalid_page_param_clamps_instead_of_erroring(client):
    resp = client.get("/jobs?page=not-a-number")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_jobs_page_negative_page_param_clamps_to_first_page(client):
    resp = client.get("/jobs?page=-3")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_jobs_table_has_scoped_headers_and_scroll_wrapper(client):
    resp = client.get("/jobs")

    assert 'scope="col"' in resp.text
    assert 'class="table-scroll"' in resp.text


def test_jobs_page_neutralizes_a_javascript_url(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k4", url="javascript:alert(1)")], db.start_run(conn))

    resp = client.get("/jobs")

    assert 'href="javascript:alert(1)"' not in resp.text
    assert 'href="#"' in resp.text


def test_nav_includes_jobs_link(client):
    resp = client.get("/jobs")

    assert 'href="/jobs" aria-current="page"' in resp.text


def test_jobs_table_cells_have_data_labels(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job()], db.start_run(conn))

    resp = client.get("/jobs")

    for label in ("Company", "Search name", "Title", "Location", "Date found",
                  "Removed", "Age (days)", "Emailed", "Summary"):
        assert f'data-label="{label}"' in resp.text


def test_jobs_page_sort_by_company_orders_rows(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="a", company="Zeta")], run_id)
    db.save_jobs(conn, [make_job(key="b", company="Acme")], run_id)

    resp = client.get("/jobs?sort=company&dir=asc")

    assert resp.text.index("Acme") < resp.text.index("Zeta")


def test_jobs_page_filters_by_company(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="a", company="Acme")], run_id)
    db.save_jobs(conn, [make_job(key="b", company="Zeta")], run_id)

    resp = client.get("/jobs?company=Acme")

    assert "Acme" in resp.text
    assert "Zeta" not in resp.text


def test_jobs_page_filter_dropdown_lists_distinct_source_names(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="a", source_name="Acme Board")], db.start_run(conn))

    resp = client.get("/jobs")

    assert '<option value="Acme Board"' in resp.text


def test_jobs_page_invalid_sort_does_not_error(client):
    resp = client.get("/jobs?sort=nonsense")

    assert resp.status_code == 200


def test_jobs_page_empty_filter_matches_none_renders_empty_table(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="a", company="Acme")], db.start_run(conn))

    resp = client.get("/jobs?company=NoSuchCompany")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text
    assert 'data-label="Company">Acme' not in resp.text


def test_jobs_page_clear_filters_link_hidden_when_no_filter_active(client):
    resp = client.get("/jobs")
    assert "Clear filters" not in resp.text


def test_jobs_page_clear_filters_link_shown_when_filter_active(client):
    resp = client.get("/jobs?company=Acme")
    assert 'href="/jobs"' in resp.text
    assert "Clear filters" in resp.text


def test_jobs_page_sortable_headers_have_aria_sort_when_active(client):
    resp = client.get("/jobs?sort=company&dir=asc")
    assert 'aria-sort="ascending"' in resp.text


def test_jobs_page_removed_and_emailed_filters_narrow_results(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="a")], db.start_run(conn))
    db.mark_emailed(conn, ["a"])

    company_cell = 'data-label="Company">Acme'
    assert company_cell in client.get("/jobs?emailed=sent").text
    assert company_cell not in client.get("/jobs?emailed=not_sent").text
    assert company_cell in client.get("/jobs?removed=active").text
    assert company_cell not in client.get("/jobs?removed=removed").text


def test_jobs_page_filter_form_preserves_active_sort_via_hidden_fields(client):
    resp = client.get("/jobs?sort=company&dir=asc")

    assert '<input type="hidden" name="sort" value="company">' in resp.text
    assert '<input type="hidden" name="dir" value="asc">' in resp.text


def test_post_job_status_sets_status_and_redirects_with_flash(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    resp = client.post("/jobs/status", data={"key": "k1", "status": "applied"}, follow_redirects=False)

    assert resp.status_code == 303
    location = urlparse(resp.headers["location"])
    assert location.path == "/jobs"
    assert parse_qs(location.query)["flash"] == ["Marked as Applied."]
    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["status"] == "applied"


def test_post_job_status_clearing_redirects_with_cleared_message(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))
    db.set_job_status(conn, "k1", "applied")

    resp = client.post("/jobs/status", data={"key": "k1", "status": ""}, follow_redirects=False)

    location = urlparse(resp.headers["location"])
    assert parse_qs(location.query)["flash"] == ["Status cleared."]
    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["status"] is None


def test_post_job_status_invalid_status_returns_400(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="k1")], db.start_run(conn))

    resp = client.post("/jobs/status", data={"key": "k1", "status": "bogus"})

    assert resp.status_code == 400
    rows = {r["key"]: r for r in db.list_jobs(conn)}
    assert rows["k1"]["status"] is None


def test_post_job_status_unknown_key_returns_404(client):
    resp = client.post("/jobs/status", data={"key": "does-not-exist", "status": "applied"})

    assert resp.status_code == 404
