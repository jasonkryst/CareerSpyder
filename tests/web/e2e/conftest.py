import json
import os
import socket
import threading
import time

import pytest
import uvicorn
from playwright.sync_api import sync_playwright


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("e2e")
    sources_path = tmp_path / "sources.json"
    sources_path.write_text(json.dumps({"sources": []}))

    env_overrides = {
        "CAREERSPYDER_DB_PATH": str(tmp_path / "state.db"),
        "CAREERSPYDER_SOURCES_PATH": str(sources_path),
        "RUN_CRON": "0 8 * * *",
        "TZ": "UTC",
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "user",
        "EMAIL_FROM": "from@x.test",
        "EMAIL_TO": "to@x.test",
        "SMTP_PASSWORD": "secret",
    }
    previous = {k: os.environ.get(k) for k in env_overrides}
    os.environ.update(env_overrides)

    from app.web.main import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)
    for k, v in previous.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    # bypass_csp: the app's CSP (app/web/security_headers.py) blocks eval(),
    # which Playwright's own wait_for_function/expect helpers use internally
    # to run predicates in-page. Real browsers/users are unaffected -- this
    # only disables CSP enforcement inside this test-only page.
    p = browser.new_page(bypass_csp=True)
    yield p
    p.close()
