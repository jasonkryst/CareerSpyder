"""U6: when <dialog>/showModal isn't supported, confirm-modal.js falls back
to window.confirm() instead of silently losing the confirmation."""


def _create_source(page, live_server, name, token):
    page.goto(live_server + "/sources/new")
    page.fill('input[name="name"]', name)
    page.select_option('select[name="type"]', "greenhouse")
    page.fill('input[name="board_token"]', token)
    page.click('button.btn-primary')
    page.wait_for_url("**/sources")


def test_dismissing_the_native_confirm_keeps_the_source(live_server, page):
    page.add_init_script("delete HTMLDialogElement.prototype.showModal;")
    _create_source(page, live_server, "Fallback Keep", "fallback-keep")

    page.once("dialog", lambda d: d.dismiss())
    page.click('tr:has-text("Fallback Keep") button:has-text("Delete")')

    page.wait_for_timeout(300)
    assert page.locator('td[data-label="Name"]', has_text="Fallback Keep").count() == 1


def test_accepting_the_native_confirm_deletes_the_source(live_server, page):
    page.add_init_script("delete HTMLDialogElement.prototype.showModal;")
    _create_source(page, live_server, "Fallback Delete", "fallback-delete")

    page.once("dialog", lambda d: d.accept())
    with page.expect_navigation():
        page.click('tr:has-text("Fallback Delete") button:has-text("Delete")')

    assert page.locator('td[data-label="Name"]', has_text="Fallback Delete").count() == 0


def test_the_themed_dialog_is_not_shown_when_falling_back(live_server, page):
    page.add_init_script("delete HTMLDialogElement.prototype.showModal;")
    _create_source(page, live_server, "Fallback No Dialog", "fallback-no-dialog")

    page.once("dialog", lambda d: d.dismiss())
    page.click('tr:has-text("Fallback No Dialog") button:has-text("Delete")')

    page.wait_for_timeout(300)
    assert page.locator("#confirm-modal[open]").count() == 0
