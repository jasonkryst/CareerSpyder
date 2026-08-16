from app import db


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
    db.finish_run(conn, run_id, new_job_count=3, failed_sources=["Bad Co"])

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
    db.finish_run(conn, run_id, new_job_count=3, failed_sources=["Bad Co"])

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
