def test_clicking_the_version_opens_the_modal_with_release_notes(live_server, page):
    page.goto(live_server + "/")

    page.click("#whats-new-trigger")

    page.wait_for_selector("#whats-new-modal[open]")
    assert page.locator("#whats-new-modal-body").inner_text().strip() != ""


def test_closing_the_modal_hides_it_again(live_server, page):
    page.goto(live_server + "/")

    page.click("#whats-new-trigger")
    page.wait_for_selector("#whats-new-modal[open]")
    page.click("#whats-new-modal-close")

    page.wait_for_timeout(200)
    assert page.locator("#whats-new-modal[open]").count() == 0
