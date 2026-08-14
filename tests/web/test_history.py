from app import db


def test_history_lists_past_runs(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_job_count=3, failed_sources=["Bad Co"])

    resp = client.get("/history")

    assert resp.status_code == 200
    assert "3" in resp.text
    assert "Bad Co" in resp.text


def test_history_table_has_scoped_headers_and_scroll_wrapper(client):
    resp = client.get("/history")

    assert 'scope="col"' in resp.text
    assert 'class="table-scroll"' in resp.text
