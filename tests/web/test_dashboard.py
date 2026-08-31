from app import db
from app.models import FailedSource


def test_dashboard_loads_with_no_runs_yet(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "CareerSpyder" in resp.text


def test_dashboard_run_now_button_is_primary(client):
    resp = client.get("/")

    assert 'class="btn-primary"' in resp.text


def test_run_now_triggers_background_task_and_redirects(client):
    resp = client.post("/run-now", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_run_now_forces_a_run_regardless_of_configured_days(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.web.routes_dashboard.run_and_notify",
        lambda *args, **kwargs: calls.append(kwargs),
    )

    client.post("/run-now", follow_redirects=False)

    assert calls == [{"force": True}]


def test_dashboard_lists_past_runs(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_job_count=3, failed_sources=[FailedSource("Bad Co", url="https://bad.test/careers")])

    resp = client.get("/")

    assert resp.status_code == 200
    assert "3" in resp.text
    assert "Bad Co" in resp.text


def test_dashboard_table_has_no_legacy_inline_attributes(client):
    resp = client.get("/")

    assert 'border="1"' not in resp.text
    assert 'cellpadding="4"' not in resp.text


def test_dashboard_table_has_scoped_headers_and_scroll_wrapper(client):
    resp = client.get("/")

    assert 'scope="col"' in resp.text
    assert 'class="table-scroll"' in resp.text


def test_dashboard_second_page_shows_older_runs(client):
    conn = client.app.state.conn
    for i in range(30):
        run_id = db.start_run(conn)
        db.finish_run(conn, run_id, new_job_count=i, failed_sources=[])

    page1 = client.get("/?page=1")
    page2 = client.get("/?page=2")

    assert "Page 1 of 2" in page1.text
    assert "Page 2 of 2" in page2.text


def test_dashboard_invalid_page_param_clamps_instead_of_erroring(client):
    resp = client.get("/?page=not-a-number")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_dashboard_negative_page_param_clamps_to_first_page(client):
    resp = client.get("/?page=-3")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_dashboard_table_cells_have_data_labels(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_job_count=3, failed_sources=[FailedSource("Bad Co", url="https://bad.test/careers")])

    resp = client.get("/")

    assert 'data-label="Started"' in resp.text
    assert 'data-label="Finished"' in resp.text
    assert 'data-label="New jobs"' in resp.text
    assert 'data-label="Failed sources"' in resp.text


def test_rows_endpoint_returns_fragment_without_page_chrome(client):
    resp = client.get("/rows")

    assert resp.status_code == 200
    assert 'id="history-rows"' in resp.text
    assert 'aria-label="Main"' not in resp.text
    assert "<html" not in resp.text


def test_rows_endpoint_paginates_like_dashboard_page(client):
    conn = client.app.state.conn
    for i in range(30):
        run_id = db.start_run(conn)
        db.finish_run(conn, run_id, new_job_count=i, failed_sources=[])

    page1 = client.get("/rows?page=1")
    page2 = client.get("/rows?page=2")

    assert "Page 1 of 2" in page1.text
    assert "Page 2 of 2" in page2.text


def test_rows_endpoint_invalid_page_param_clamps(client):
    resp = client.get("/rows?page=not-a-number")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_rows_reflects_run_status_change(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)

    in_progress = client.get("/rows")
    assert 'data-label="Finished">in progress' in in_progress.text

    db.finish_run(conn, run_id, new_job_count=2, failed_sources=[])
    finished = client.get("/rows")
    assert 'data-label="Finished">in progress' not in finished.text


def test_dashboard_includes_refresh_button_and_status_region(client):
    resp = client.get("/")

    assert 'id="refresh-history"' in resp.text
    assert 'id="history-status"' in resp.text
    assert 'aria-live="polite"' in resp.text
    assert 'id="history-rows"' in resp.text
    assert 'id="run-now-form"' in resp.text


def test_dashboard_js_is_served(client):
    resp = client.get("/static/dashboard.js")

    assert resp.status_code == 200
    assert "history-rows" in resp.text


def test_history_routes_removed(client):
    assert client.get("/history").status_code == 404
    assert client.get("/history/rows").status_code == 404


def test_dashboard_sort_by_new_job_count_orders_rows(client):
    conn = client.app.state.conn
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=5, failed_sources=[])
    r2 = db.start_run(conn)
    db.finish_run(conn, r2, new_job_count=1, failed_sources=[])

    resp = client.get("/?sort=new_job_count&dir=asc")

    assert resp.text.index('data-label="New jobs">1') < resp.text.index('data-label="New jobs">5')


def test_dashboard_failures_filter_only_shows_failed_runs(client):
    conn = client.app.state.conn
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=0, failed_sources=[FailedSource("Bad Co", url="https://bad.test/careers")])
    r2 = db.start_run(conn)
    db.finish_run(conn, r2, new_job_count=0, failed_sources=[])

    resp = client.get("/?failures=only")

    assert "Bad Co" in resp.text
    assert "Page 1 of 1" in resp.text


def test_rows_endpoint_honors_sort_and_failures_params(client):
    conn = client.app.state.conn
    r1 = db.start_run(conn)
    db.finish_run(conn, r1, new_job_count=0, failed_sources=[FailedSource("Bad Co", url="https://bad.test/careers")])
    r2 = db.start_run(conn)
    db.finish_run(conn, r2, new_job_count=0, failed_sources=[])

    resp = client.get("/rows?failures=clean")

    assert "Bad Co" not in resp.text


def test_dashboard_invalid_sort_and_failures_do_not_error(client):
    resp = client.get("/?sort=nonsense&failures=nonsense")
    assert resp.status_code == 200


def test_dashboard_pagination_link_preserves_active_filter(client):
    conn = client.app.state.conn
    for i in range(30):
        run_id = db.start_run(conn)
        db.finish_run(conn, run_id, new_job_count=0, failed_sources=[])

    resp = client.get("/?failures=clean&page=1")

    assert "failures=clean" in resp.text


def test_dashboard_sort_headers_have_aria_sort_when_active(client):
    resp = client.get("/?sort=new_job_count&dir=asc")
    assert 'aria-sort="ascending"' in resp.text


def test_dashboard_filter_form_preserves_active_sort_via_hidden_fields(client):
    resp = client.get("/?sort=new_job_count&dir=asc")

    assert '<input type="hidden" name="sort" value="new_job_count">' in resp.text
    assert '<input type="hidden" name="dir" value="asc">' in resp.text


def test_dashboard_clear_filters_link_shown_when_filter_active(client):
    resp = client.get("/?failures=only")
    assert 'href="/"' in resp.text
    assert "Clear filters" in resp.text


def test_dashboard_clear_filters_link_hidden_when_no_filter_active(client):
    resp = client.get("/")
    assert "Clear filters" not in resp.text


def test_dashboard_js_uses_location_search_for_refresh(client):
    resp = client.get("/static/dashboard.js")
    assert "window.location.search" in resp.text
    assert "data-page" not in resp.text


def test_dashboard_wraps_started_at_in_a_time_element(client):
    conn = client.app.state.conn
    db.start_run(conn)
    started_at = db.list_runs(conn)[0]["started_at"]

    resp = client.get("/")

    assert f'<time datetime="{started_at}">{started_at}</time>' in resp.text


def test_dashboard_wraps_finished_at_in_a_time_element(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_job_count=0, failed_sources=[])
    finished_at = db.list_runs(conn)[0]["finished_at"]

    resp = client.get("/")

    assert f'<time datetime="{finished_at}">{finished_at}</time>' in resp.text


def test_dashboard_does_not_wrap_in_progress_placeholder_in_a_time_element(client):
    conn = client.app.state.conn
    db.start_run(conn)

    resp = client.get("/")

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    cell = soup.select_one('td[data-label="Finished"]')
    assert cell.get_text(strip=True) == "in progress"
    assert cell.find("time") is None


def test_dates_js_is_served(client):
    resp = client.get("/static/dates.js")

    assert resp.status_code == 200
    assert "time[datetime]" in resp.text


# --- Failed source link tests (issue #93) ---

def test_dashboard_failed_source_with_url_renders_as_link(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_job_count=0,
                  failed_sources=[FailedSource("Acme Jobs", url="https://acme.test/careers")])

    resp = client.get("/")

    assert 'href="https://acme.test/careers"' in resp.text
    assert "Acme Jobs" in resp.text
    assert 'target="_blank"' in resp.text


def test_dashboard_failed_source_without_url_renders_as_plain_text(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_job_count=0,
                  failed_sources=[FailedSource("Greenhouse Co", url=None)])

    resp = client.get("/")

    assert "Greenhouse Co" in resp.text
    assert 'href=' not in resp.text.split('data-label="Failed sources"')[1].split('</td>')[0]


def test_dashboard_failed_sources_rendered_as_list(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_job_count=0, failed_sources=[
        FailedSource("Source A", url="https://a.test"),
        FailedSource("Source B", url=None),
    ])

    resp = client.get("/")

    assert "<ul" in resp.text
    assert "Source A" in resp.text
    assert "Source B" in resp.text


def test_dashboard_failed_source_link_has_noopener(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_job_count=0,
                  failed_sources=[FailedSource("Corp Jobs", url="https://corp.test/jobs")])

    resp = client.get("/")

    assert 'rel="noopener noreferrer"' in resp.text


def test_dashboard_no_failed_sources_cell_is_empty(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_job_count=5, failed_sources=[])

    resp = client.get("/")

    assert resp.status_code == 200
    assert "<ul" not in resp.text


# --- URL check run row tests (issue #116) ---

def test_check_urls_post_creates_in_progress_run_row(client, monkeypatch):
    monkeypatch.setattr("app.web.routes_dashboard._run_url_check", lambda *a: None)

    client.post("/check-urls", follow_redirects=False)

    resp = client.get("/rows")
    assert 'data-label="Finished">in progress' in resp.text


def test_check_urls_post_redirects(client, monkeypatch):
    monkeypatch.setattr("app.web.routes_dashboard._run_url_check", lambda *a: None)

    resp = client.post("/check-urls", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_url_check_row_uses_urls_removed_data_label(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn, kind="url_check")
    db.finish_run(conn, run_id, new_job_count=3, failed_sources=[])

    resp = client.get("/")

    assert 'data-label="URLs removed"' in resp.text
    assert 'data-label="New jobs"' not in resp.text


def test_scrape_run_keeps_new_jobs_data_label(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn, kind="scrape")
    db.finish_run(conn, run_id, new_job_count=2, failed_sources=[])

    resp = client.get("/")

    assert 'data-label="New jobs"' in resp.text
    assert 'data-label="URLs removed"' not in resp.text


def test_url_check_row_shows_removed_count(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn, kind="url_check")
    db.finish_run(conn, run_id, new_job_count=7, failed_sources=[])

    resp = client.get("/")

    assert ">7<" in resp.text


def test_url_check_row_failed_sources_cell_is_empty(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn, kind="url_check")
    db.finish_run(conn, run_id, new_job_count=0, failed_sources=[])

    resp = client.get("/")

    assert "<ul" not in resp.text


def test_mixed_run_types_both_appear_in_dashboard(client):
    conn = client.app.state.conn
    scrape_id = db.start_run(conn, kind="scrape")
    db.finish_run(conn, scrape_id, new_job_count=5, failed_sources=[])
    check_id = db.start_run(conn, kind="url_check")
    db.finish_run(conn, check_id, new_job_count=2, failed_sources=[])

    resp = client.get("/")

    assert 'data-label="New jobs"' in resp.text
    assert 'data-label="URLs removed"' in resp.text


def test_dashboard_includes_check_urls_form_id(client):
    resp = client.get("/")

    assert 'id="check-urls-form"' in resp.text


def test_dashboard_js_intercepts_check_urls_form(client):
    resp = client.get("/static/dashboard.js")

    assert "check-urls-form" in resp.text
