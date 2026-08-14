def test_theme_toggle_switches_and_persists_across_reload(live_server, page):
    page.goto(live_server + "/")
    toggle = page.locator("#theme-toggle")

    toggle.click()
    first_theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert first_theme in ("dark", "light")
    expected_pressed = "true" if first_theme == "dark" else "false"
    assert toggle.get_attribute("aria-pressed") == expected_pressed

    toggle.click()
    second_theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert second_theme != first_theme
    assert second_theme in ("dark", "light")

    page.reload()
    persisted_theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert persisted_theme == second_theme
