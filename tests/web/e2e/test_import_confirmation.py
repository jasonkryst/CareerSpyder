import json


def test_confirming_dialog_allows_import_to_proceed(live_server, page):
    page.goto(live_server + "/settings/data")
    page.on("dialog", lambda dialog: dialog.accept())

    payload = json.dumps({"sources": []}).encode()
    page.set_input_files('input[name="file"]', {
        "name": "settings.json", "mimeType": "application/json", "buffer": payload,
    })
    page.click('#import-form button[type="submit"]')
    page.wait_for_url("**/settings/data?imported=0")


def test_dismissing_dialog_cancels_import(live_server, page):
    page.goto(live_server + "/settings/data")
    page.on("dialog", lambda dialog: dialog.dismiss())

    payload = json.dumps({"sources": []}).encode()
    page.set_input_files('input[name="file"]', {
        "name": "settings.json", "mimeType": "application/json", "buffer": payload,
    })
    page.click('#import-form button[type="submit"]')

    page.wait_for_timeout(300)
    assert page.url.endswith("/settings/data")
    assert "imported" not in page.url
