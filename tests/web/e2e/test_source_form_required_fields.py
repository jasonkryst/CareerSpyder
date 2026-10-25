def test_board_token_field_is_visible_when_lever_is_selected(live_server, page):
    """Regression: board_token used to live only inside the greenhouse-only
    .type-fields container, so switching to Lever hid the only way to enter
    a board token."""
    page.goto(live_server + "/sources/new")

    page.select_option('select[name="type"]', "lever")

    assert page.locator('input[name="board_token"]').is_visible()


def test_required_attribute_toggles_with_selected_type(live_server, page):
    page.goto(live_server + "/sources/new")

    # Greenhouse is the default (first) option -- board_token is required.
    assert page.locator('input[name="board_token"]').get_attribute("required") is not None

    page.select_option('select[name="type"]', "workday")
    assert page.locator('input[name="board_token"]').get_attribute("required") is None
    assert page.locator('input[name="career_site_url"]').get_attribute("required") is not None

    page.select_option('select[name="type"]', "lever")
    assert page.locator('input[name="board_token"]').get_attribute("required") is not None
    assert page.locator('input[name="career_site_url"]').get_attribute("required") is None


def test_a_hidden_required_field_does_not_block_submission_of_a_different_type(live_server, page):
    """Regression for the bug this required-field toggling exists to avoid:
    before it, a required attribute left on a field hidden by a different
    type's selection silently blocked the whole form from submitting."""
    page.goto(live_server + "/sources/new")

    page.select_option('select[name="type"]', "healthcaresource")
    page.fill('input[name="name"]', "Acme HCS")
    page.fill('input[name="site_id"]', "acme")
    page.click('button.btn-primary')

    page.wait_for_url("**/sources")
    assert page.locator('td[data-label="Name"]', has_text="Acme HCS").count() == 1
