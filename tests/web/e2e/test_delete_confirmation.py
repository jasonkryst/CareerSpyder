def test_dismissing_modal_keeps_the_source(live_server, page):
    page.goto(live_server + "/sources/new")
    page.fill('input[name="name"]', "Acme (Greenhouse)")
    page.select_option('select[name="type"]', "greenhouse")
    page.fill('input[name="board_token"]', "acme")
    page.click('button[type="submit"]')
    page.wait_for_url("**/sources")

    page.click('tr:has-text("Acme (Greenhouse)") button:has-text("Delete")')
    page.wait_for_selector("#confirm-modal[open]")
    page.click("#confirm-modal-cancel")

    page.wait_for_timeout(300)
    assert page.locator('td[data-label="Name"]', has_text="Acme (Greenhouse)").count() == 1


def test_confirming_modal_deletes_the_source(live_server, page):
    page.goto(live_server + "/sources/new")
    page.fill('input[name="name"]', "Beta (Greenhouse)")
    page.select_option('select[name="type"]', "greenhouse")
    page.fill('input[name="board_token"]', "beta")
    page.click('button[type="submit"]')
    page.wait_for_url("**/sources")

    page.click('tr:has-text("Beta (Greenhouse)") button:has-text("Delete")')
    page.wait_for_selector("#confirm-modal[open]")
    page.click("#confirm-modal-confirm")

    page.wait_for_timeout(300)
    assert page.locator('td[data-label="Name"]', has_text="Beta (Greenhouse)").count() == 0
