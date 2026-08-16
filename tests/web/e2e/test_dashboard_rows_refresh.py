def test_refresh_button_swaps_table_content(live_server, page):
    page.goto(live_server + "/")

    page.route("**/rows*", lambda route: route.fulfill(
        status=200,
        content_type="text/html",
        body='<div id="history-rows" data-page="1"><div class="table-scroll"><table>'
             '<tr><th scope="col">Started</th></tr>'
             '<tr><td data-label="Started">MOCKED-ROW</td></tr>'
             '</table></div><nav aria-label="Pagination"><span>Page 1 of 1</span></nav></div>',
    ))

    page.click("#refresh-history")
    page.wait_for_selector("text=MOCKED-ROW")

    assert "MOCKED-ROW" in page.inner_text("#history-rows")


def test_status_region_announces_update_after_refresh(live_server, page):
    page.goto(live_server + "/")

    page.route("**/rows*", lambda route: route.fulfill(
        status=200,
        content_type="text/html",
        body='<div id="history-rows" data-page="1"><div class="table-scroll"><table></table></div>'
             '<nav aria-label="Pagination"><span>Page 1 of 1</span></nav></div>',
    ))

    page.click("#refresh-history")
    page.wait_for_function("document.getElementById('history-status').textContent === 'Updated'")


def test_auto_poll_starts_while_in_progress_and_stops_once_finished(live_server, page):
    call_count = {"n": 0}

    def handler(route):
        call_count["n"] += 1
        if call_count["n"] == 1:
            body = ('<div id="history-rows" data-page="1"><div class="table-scroll"><table>'
                     '<tr><th scope="col">Finished</th></tr>'
                     '<tr><td data-label="Finished">in progress</td></tr>'
                     '</table></div><nav aria-label="Pagination"><span>Page 1 of 1</span></nav></div>')
        else:
            body = ('<div id="history-rows" data-page="1"><div class="table-scroll"><table>'
                     '<tr><th scope="col">Finished</th></tr>'
                     '<tr><td data-label="Finished">2026-08-16T00:00:00+00:00</td></tr>'
                     '</table></div><nav aria-label="Pagination"><span>Page 1 of 1</span></nav></div>')
        route.fulfill(status=200, content_type="text/html", body=body)

    page.route("**/rows*", handler)
    page.goto(live_server + "/")

    page.click("#refresh-history")
    page.wait_for_function(
        "document.querySelector('td[data-label=\"Finished\"]')?.textContent.trim() === 'in progress'"
    )

    page.wait_for_function(
        "document.querySelector('td[data-label=\"Finished\"]')?.textContent.trim() !== 'in progress'",
        timeout=15000,
    )
    assert call_count["n"] >= 2


def test_manual_refresh_works_when_nothing_is_in_progress(live_server, page):
    page.goto(live_server + "/")

    page.route("**/rows*", lambda route: route.fulfill(
        status=200,
        content_type="text/html",
        body='<div id="history-rows" data-page="1"><div class="table-scroll"><table>'
             '<tr><th scope="col">Finished</th></tr>'
             '<tr><td data-label="Finished">2026-08-16T00:00:00+00:00</td></tr>'
             '</table></div><nav aria-label="Pagination"><span>Page 1 of 1</span></nav></div>',
    ))

    page.click("#refresh-history")
    page.wait_for_function("document.getElementById('history-status').textContent === 'Updated'")


def test_refresh_request_preserves_current_query_string(live_server, page):
    captured = {}

    def handler(route):
        captured["url"] = route.request.url
        route.fulfill(
            status=200, content_type="text/html",
            body='<div id="history-rows"><div class="table-scroll"><table></table></div>'
                 '<nav aria-label="Pagination"><span>Page 1 of 1</span></nav></div>',
        )

    page.route("**/rows*", handler)
    page.goto(live_server + "/?failures=only")

    page.click("#refresh-history")
    page.wait_for_function("document.getElementById('history-status').textContent === 'Updated'")

    assert "failures=only" in captured["url"]
