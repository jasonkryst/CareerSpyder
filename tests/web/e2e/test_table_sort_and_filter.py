def test_clicking_company_header_sorts_jobs_table(live_server, page):
    page.goto(live_server + "/jobs")
    page.click("th a:has-text('Company')")
    page.wait_for_url("**sort=company*")

    assert "sort=company" in page.url
    assert "dir=asc" in page.url


def test_clicking_company_header_twice_toggles_direction(live_server, page):
    page.goto(live_server + "/jobs?sort=company&dir=asc")
    page.click("th a:has-text('Company')")
    page.wait_for_url("**dir=desc*")

    assert "dir=desc" in page.url


def test_submitting_jobs_filter_form_narrows_url_params(live_server, page):
    page.goto(live_server + "/jobs")
    page.fill('input[name="company"]', "Acme")
    page.click(".filter-bar button[type=submit]")
    page.wait_for_url("**company=Acme*")

    assert "company=Acme" in page.url


def test_clicking_sources_name_header_sorts_and_toggles(live_server, page):
    # Unique, unlikely-to-collide names -- other e2e tests in this session
    # leave their own sources behind in the same shared sources.json, so
    # this only asserts the *relative* order of these two, not absolute position.
    page.goto(live_server + "/sources/new")
    page.fill('input[name="name"]', "ZZZ Sort Test Zeta")
    page.select_option('select[name="type"]', "greenhouse")
    page.fill('input[name="board_token"]', "zeta")
    page.click('button.btn-primary')
    page.wait_for_url("**/sources")

    page.goto(live_server + "/sources/new")
    page.fill('input[name="name"]', "ZZZ Sort Test Acme")
    page.select_option('select[name="type"]', "greenhouse")
    page.fill('input[name="board_token"]', "acme")
    page.click('button.btn-primary')
    page.wait_for_url("**/sources")

    page.click("th a:has-text('Name')")
    page.wait_for_url("**sort=name*")

    names = page.locator('td[data-label="Name"]').all_inner_texts()
    assert names.index("ZZZ Sort Test Acme") < names.index("ZZZ Sort Test Zeta")


def test_bulk_disable_sources_shows_toolbar_and_updates_badge(live_server, page):
    page.goto(live_server + "/sources/new")
    page.fill('input[name="name"]', "ZZZ Bulk Toggle Co")
    page.select_option('select[name="type"]', "greenhouse")
    page.fill('input[name="board_token"]', "bulktoggle")
    page.click("button.btn-primary")
    page.wait_for_url("**/sources")

    row = page.locator("tr", has=page.locator('td[data-label="Name"]', has_text="ZZZ Bulk Toggle Co"))
    assert row.locator("text=Enabled").count() == 1

    toolbar = page.locator("#bulk-toggle-form")
    assert toolbar.is_hidden()
    row.locator(".source-select").check()
    assert toolbar.is_visible()
    page.click('#bulk-toggle-form button[value="false"]')
    page.wait_for_url("**/sources*")

    row = page.locator("tr", has=page.locator('td[data-label="Name"]', has_text="ZZZ Bulk Toggle Co"))
    assert row.locator("text=Disabled").count() == 1
