"""#269: the advisory strength meter on /settings/account reports strength as
text in a live region (not colour alone), never blocks submit, and is
absent from the login page."""

TEXT = "#new_password-strength-text"


def test_meter_is_revealed_and_empty_until_typing(live_server, page):
    page.goto(live_server + "/settings/account")
    meter = page.locator('[data-password-strength="new_password"]')
    assert meter.is_visible()
    assert page.locator(TEXT).inner_text() == ""
    assert page.locator(TEXT).get_attribute("aria-live") == "polite"


def test_short_password_reports_characters_needed(live_server, page):
    page.goto(live_server + "/settings/account")
    page.fill("#new_password", "abc")
    text = page.locator(TEXT).inner_text()
    assert "Very weak" in text
    assert "5 more characters needed" in text


def test_repetitive_password_rates_low(live_server, page):
    page.goto(live_server + "/settings/account")
    page.fill("#new_password", "aaaaaaaaaaaa")
    text = page.locator(TEXT).inner_text()
    assert "Very weak" in text or "Weak" in text


def test_long_passphrase_rates_strong(live_server, page):
    page.goto(live_server + "/settings/account")
    page.fill("#new_password", "violet Lantern orbit 42 quietly")
    assert "strong" in page.locator(TEXT).inner_text().lower()  # Strong / Very strong
    level = page.locator('[data-password-strength="new_password"]').get_attribute("data-level")
    assert level in ("3", "4")


def test_clearing_the_field_clears_the_text(live_server, page):
    page.goto(live_server + "/settings/account")
    page.fill("#new_password", "something")
    page.fill("#new_password", "")
    assert page.locator(TEXT).inner_text() == ""


def test_meter_does_not_block_submit(live_server, page):
    # A weak-but-valid password still reaches the server; the server's own
    # policy decides (here: rejects it as common, with its message).
    page.goto(live_server + "/settings/account")
    page.fill("#current_password", "password123")
    page.fill("#new_password", "football")
    page.fill("#new_password_confirm", "football")
    with page.expect_navigation():
        page.click('button:has-text("Update password")')
    assert "most common passwords" in page.content()


def test_login_page_has_no_meter(browser, live_server):
    p = browser.new_page(bypass_csp=True)
    try:
        p.goto(live_server + "/login")
        p.fill('input[name="password"]', "anything at all")
        assert p.locator("[data-password-strength]").count() == 0
        assert p.locator(".pw-strength-text").count() == 0
    finally:
        p.close()
