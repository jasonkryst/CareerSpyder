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
