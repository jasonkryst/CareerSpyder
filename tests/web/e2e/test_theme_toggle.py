import pytest


@pytest.mark.parametrize("choice", ["dark", "light"])
def test_preferences_theme_radio_applies_and_persists(live_server, page, choice):
    page.goto(live_server + "/settings/preferences")

    page.check(f'input[name="theme"][value="{choice}"]')
    applied = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert applied == choice

    page.reload()
    persisted = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert persisted == choice
    assert page.is_checked(f'input[name="theme"][value="{choice}"]')


def test_preferences_system_choice_clears_explicit_override(live_server, page):
    page.goto(live_server + "/settings/preferences")

    page.check('input[name="theme"][value="dark"]')
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"

    page.check('input[name="theme"][value="system"]')
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") is None

    page.reload()
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") is None
    assert page.is_checked('input[name="theme"][value="system"]')
