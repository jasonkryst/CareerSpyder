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
    page.click("details.filter-panel summary")  # the panel is collapsed by default (issue #254)
    page.fill('input[name="company"]', "Acme")
    page.click(".filter-bar button[type=submit]")
    page.wait_for_url("**company=Acme*")

    assert "company=Acme" in page.url


# --- Collapsible filter panel + active-filter chips (issue #254) ---

def test_jobs_filter_panel_collapsed_by_default_and_toggles_open_on_click(live_server, page):
    page.goto(live_server + "/jobs")

    panel = page.locator("details.filter-panel")
    assert panel.get_attribute("open") is None

    panel.locator("summary").click()
    assert panel.get_attribute("open") is not None

    panel.locator("summary").click()
    assert panel.get_attribute("open") is None


def test_jobs_filter_panel_opens_automatically_when_navigating_with_a_filter_applied(live_server, page):
    page.goto(live_server + "/jobs?company=Acme")

    panel = page.locator("details.filter-panel")
    assert panel.get_attribute("open") is not None
    assert page.locator(".active-filters .chip", has_text="Company: Acme").count() == 1


def test_removing_an_active_filter_chip_clears_just_that_filter(live_server, page):
    page.goto(live_server + "/jobs?company=Acme&search=engineer")

    page.locator(".active-filters .chip", has_text="Company: Acme").click()
    page.wait_for_load_state("networkidle")

    assert "company=" not in page.url
    assert "search=engineer" in page.url


def test_clear_filters_chip_removes_all_active_filters(live_server, page):
    page.goto(live_server + "/jobs?company=Acme&search=engineer")

    page.click(".active-filters .chip-clear")
    page.wait_for_load_state("networkidle")

    assert page.url.rstrip("/").endswith("/jobs")
    assert page.locator(".active-filters").count() == 0


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
