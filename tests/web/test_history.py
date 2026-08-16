from app import db


def test_history_lists_past_runs(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_job_count=3, failed_sources=["Bad Co"])

    resp = client.get("/history")

    assert resp.status_code == 200
    assert "3" in resp.text
    assert "Bad Co" in resp.text


def test_history_table_has_no_legacy_inline_attributes(client):
    resp = client.get("/history")

    assert 'border="1"' not in resp.text
    assert 'cellpadding="4"' not in resp.text


def test_history_table_has_scoped_headers_and_scroll_wrapper(client):
    resp = client.get("/history")

    assert 'scope="col"' in resp.text
    assert 'class="table-scroll"' in resp.text


def test_history_second_page_shows_older_runs(client):
    conn = client.app.state.conn
    for i in range(30):
        run_id = db.start_run(conn)
        db.finish_run(conn, run_id, new_job_count=i, failed_sources=[])

    page1 = client.get("/history?page=1")
    page2 = client.get("/history?page=2")

    assert "Page 1 of 2" in page1.text
    assert "Page 2 of 2" in page2.text


def test_history_invalid_page_param_clamps_instead_of_erroring(client):
    resp = client.get("/history?page=not-a-number")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_history_negative_page_param_clamps_to_first_page(client):
    resp = client.get("/history?page=-3")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_history_table_cells_have_data_labels(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_job_count=3, failed_sources=["Bad Co"])

    resp = client.get("/history")

    assert 'data-label="Started"' in resp.text
    assert 'data-label="Finished"' in resp.text
    assert 'data-label="New jobs"' in resp.text
    assert 'data-label="Failed sources"' in resp.text


def test_history_rows_endpoint_returns_fragment_without_page_chrome(client):
    resp = client.get("/history/rows")

    assert resp.status_code == 200
    assert 'id="history-rows"' in resp.text
    assert 'aria-label="Main"' not in resp.text
    assert "<html" not in resp.text


def test_history_rows_endpoint_paginates_like_history_page(client):
    conn = client.app.state.conn
    for i in range(30):
        run_id = db.start_run(conn)
        db.finish_run(conn, run_id, new_job_count=i, failed_sources=[])

    page1 = client.get("/history/rows?page=1")
    page2 = client.get("/history/rows?page=2")

    assert "Page 1 of 2" in page1.text
    assert "Page 2 of 2" in page2.text


def test_history_rows_endpoint_invalid_page_param_clamps(client):
    resp = client.get("/history/rows?page=not-a-number")

    assert resp.status_code == 200
    assert "Page 1 of 1" in resp.text


def test_history_rows_reflects_run_status_change(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)

    in_progress = client.get("/history/rows")
    assert 'data-label="Finished">in progress' in in_progress.text

    db.finish_run(conn, run_id, new_job_count=2, failed_sources=[])
    finished = client.get("/history/rows")
    assert 'data-label="Finished">in progress' not in finished.text


def test_history_page_includes_refresh_button_and_status_region(client):
    resp = client.get("/history")

    assert 'id="refresh-history"' in resp.text
    assert 'id="history-status"' in resp.text
    assert 'aria-live="polite"' in resp.text
    assert 'id="history-rows"' in resp.text
