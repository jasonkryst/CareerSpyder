def test_run_now_shows_rate_limit_flash_in_run_now_status(live_server, page):
    # Pre-exhaust the per-user rate limit bucket (3 attempts / 10 min, see
    # app/web/routes_dashboard.py) via direct POSTs through the browser's
    # authenticated session, so the UI-driven click below is guaranteed to be
    # rate-limited without depending on scrape timing.
    for _ in range(3):
        page.request.post(live_server + "/run-now")

    page.goto(live_server + "/")
    page.click("#run-now-form button[type=submit]")

    page.wait_for_function(
        "document.getElementById('run-now-status').textContent.indexOf("
        "'Too many runs started recently') !== -1"
    )
