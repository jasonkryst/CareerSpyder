"""E2E tests for platform-detector auto-fill behavior on /sources/new.

These tests require a running Chromium instance (via the `page` fixture) and
verify JS-driven behavior that cannot be covered by unit tests.

NOTE: These tests hit the live /sources/detect-platform endpoint, which
makes outbound HTTP calls. They are marked skip by default in the test
suite; run them manually when verifying the auto-fill flow end-to-end:

    pytest tests/web/e2e/test_source_form_autofill.py -v
"""
import pytest


@pytest.mark.skip(reason="e2e auto-fill test — run manually with a live server")
def test_platform_detector_autofills_type_and_board_token(live_server, page):
    """Paste a Greenhouse URL → type dropdown and board_token pre-filled, Name focused."""
    page.goto(f"{live_server}/sources/new")
    page.fill("#detect-url", "https://boards.greenhouse.io/acme/jobs")
    page.click("#detect-btn")
    page.wait_for_selector("#detect-status:not(:empty)")

    assert page.input_value('select[name="type"]') == "greenhouse"
    assert page.input_value('[name="board_token"]') == "acme"
    assert "pre-filled" in page.text_content("#detect-status")
    # Name input should be focused
    assert page.evaluate("document.activeElement.name") == "name"


@pytest.mark.skip(reason="e2e auto-fill test — run manually with a live server")
def test_platform_detector_no_autofill_on_unknown_platform(live_server, page):
    """Unknown URL → type dropdown unchanged, 'Report as unsupported' shown."""
    page.goto(f"{live_server}/sources/new")
    original_type = page.input_value('select[name="type"]')
    page.fill("#detect-url", "https://custom-hand-rolled-careers.example.com/jobs")
    page.click("#detect-btn")
    page.wait_for_selector("#detect-status:not(:empty)")

    assert page.input_value('select[name="type"]') == original_type
    assert page.get_by_text("Report as unsupported").is_visible()
