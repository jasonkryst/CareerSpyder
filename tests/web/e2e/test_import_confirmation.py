import json


def test_confirming_the_import_preview_writes_the_import(live_server, page):
    page.goto(live_server + "/settings/data")

    payload = json.dumps({"sources": []}).encode()
    page.set_input_files('input[name="file"]', {
        "name": "settings.json", "mimeType": "application/json", "buffer": payload,
    })
    page.click('#import-form button[type="submit"]')
    page.wait_for_selector('button:has-text("Confirm import")')
    page.click('button:has-text("Confirm import")')
    page.wait_for_url("**/settings/data?flash=*")


def test_canceling_the_import_preview_does_not_write(live_server, page):
    page.goto(live_server + "/settings/data")

    payload = json.dumps({"sources": []}).encode()
    page.set_input_files('input[name="file"]', {
        "name": "settings.json", "mimeType": "application/json", "buffer": payload,
    })
    page.click('#import-form button[type="submit"]')
    page.wait_for_selector('button:has-text("Confirm import")')
    page.click('a:has-text("Cancel")')

    page.wait_for_timeout(300)
    assert page.url.endswith("/settings/data")
    assert "flash" not in page.url
