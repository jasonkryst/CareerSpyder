import json
import os
import socket
import threading
import time
import uuid

import psycopg
import pytest
import uvicorn
from alembic.config import Config
from playwright.sync_api import sync_playwright

from alembic import command


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(tmp_path_factory, postgresql_proc):
    tmp_path = tmp_path_factory.mktemp("e2e")

    dbname = f"cs_e2e_{uuid.uuid4().hex[:12]}"
    host = postgresql_proc.host
    port = postgresql_proc.port
    user = postgresql_proc.user
    dsn = f"postgresql://{user}@{host}:{port}/{dbname}"

    admin = psycopg.connect(
        f"host={host} port={port} user={user} dbname=postgres", autocommit=True
    )
    admin.execute(f"CREATE DATABASE {dbname}")
    admin.close()

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", dsn.replace("postgresql://", "postgresql+psycopg://", 1))
    command.upgrade(cfg, "head")

    sources_path = tmp_path / "sources.json"
    sources_path.write_text(json.dumps({"sources": []}))

    env_overrides = {
        "DATABASE_URL": dsn,
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

    server_port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=server_port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)

    yield f"http://127.0.0.1:{server_port}"

    server.should_exit = True
    thread.join(timeout=5)
    for k, v in previous.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    admin = psycopg.connect(
        f"host={host} port={port} user={user} dbname=postgres", autocommit=True
    )
    admin.execute(f"DROP DATABASE IF EXISTS {dbname} WITH (FORCE)")
    admin.close()


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
