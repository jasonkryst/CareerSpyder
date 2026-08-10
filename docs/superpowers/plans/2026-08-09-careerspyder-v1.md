# CareerSpyder v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build CareerSpyder v1 — a self-hosted Docker app that scrapes configured job sources daily, emails a digest of new postings, and provides a basic web UI for viewing results and managing sources/settings.

**Architecture:** A single FastAPI process (Uvicorn) runs both the web UI and an in-process APScheduler background job. A per-source-type adapter layer (Greenhouse/Lever APIs, generic HTML+CSS-selectors, best-effort Playwright for LinkedIn/Indeed) normalizes results into `Job` objects. An orchestrator runs all sources, dedupes against SQLite, and records run history. A digest builder + SMTP emailer notify on new jobs or failures.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, Jinja2, Pydantic v2, APScheduler, requests, BeautifulSoup4, Playwright (sync API), sqlite3 (stdlib), pytest, httpx (for FastAPI TestClient).

## Global Constraints

- Deployment target: single long-lived Docker container via a Portainer stack on a Proxmox Docker host; scheduling is internal (APScheduler) — no external cron dependency.
- No authentication in the web UI for v1 (trusted home network only).
- `SMTP_PASSWORD` is a container env var only — never written to SQLite, never shown or editable in the UI.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `EMAIL_FROM`, `EMAIL_TO` env vars seed the `settings` table only on first boot (if the table is empty); after that, `/settings` is the source of truth.
- Tests must not make live network calls or launch a real browser — adapters accept injectable fetch/render functions so tests use fixtures/mocks.
- Email digest is sent only if there is at least one new job OR at least one failed source for the run; otherwise nothing is sent.
- Web UI is server-rendered (FastAPI + Jinja2), no SPA/build step, exposed on port `8080`.
- `/app/config/sources.json` is the single source of truth for sources; edits (via UI or by hand) are picked up on the next run without a rebuild. Each source has a generated `id` field (used by the UI for edit/delete) in addition to the fields shown in the design spec.
- Design spec: `docs/superpowers/specs/2026-08-09-careerspyder-design.md`

---

### Task 1: Project scaffolding & dependencies

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Produces: an installable `app` package and a working `pytest` command for all later tasks.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "careerspyder"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
    "pydantic>=2.6",
    "apscheduler>=3.10",
    "requests>=2.31",
    "beautifulsoup4>=4.12",
    "playwright>=1.42",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "httpx>=0.27",
]

[tool.setuptools.packages.find]
include = ["app*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty package markers**

`app/__init__.py`: empty file.
`tests/__init__.py`: empty file.

- [ ] **Step 3: Create `tests/conftest.py` with a shared temp-dir fixture**

```python
import pytest


@pytest.fixture
def tmp_db_path(tmp_path):
    return str(tmp_path / "state.db")
```

- [ ] **Step 4: Install and verify pytest runs**

Run: `pip install -e ".[dev]" && pytest`
Expected: "no tests ran" (0 collected, exit code 0) — confirms the environment is wired correctly.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml app/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore: project scaffolding"
```

---

### Task 2: Job model + SQLite db module

**Files:**
- Create: `app/models.py`
- Create: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `Job` dataclass (`key, title, url, company, location, posted_date, source_name`); `db.init_db(path) -> sqlite3.Connection`; `db.get_new_jobs(conn, jobs) -> list[Job]`; `db.save_jobs(conn, jobs, run_id) -> None`; `db.start_run(conn) -> int`; `db.finish_run(conn, run_id, new_job_count, failed_sources) -> None`; `db.list_runs(conn, limit=50) -> list[dict]`; `db.get_settings(conn) -> dict | None`; `db.save_settings(conn, smtp_host, smtp_port, smtp_user, email_from, email_to) -> None`; `db.seed_settings_if_empty(conn, ...same args...) -> None`.

- [ ] **Step 1: Write `app/models.py`**

```python
from dataclasses import dataclass
from typing import Optional


@dataclass
class Job:
    key: str
    title: str
    url: str
    company: Optional[str] = None
    location: Optional[str] = None
    posted_date: Optional[str] = None
    source_name: str = ""
```

- [ ] **Step 2: Write the failing test for dedup + run tracking**

`tests/test_db.py`:

```python
from app import db
from app.models import Job


def make_job(key="k1", title="Engineer"):
    return Job(key=key, title=title, url="https://x.test/1", company="Acme",
               location="Remote", posted_date=None, source_name="Acme Board")


def test_new_job_then_seen_on_second_run(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    job = make_job()

    assert db.get_new_jobs(conn, [job]) == [job]
    run_id = db.start_run(conn)
    db.save_jobs(conn, [job], run_id)
    db.finish_run(conn, run_id, new_job_count=1, failed_sources=[])

    assert db.get_new_jobs(conn, [job]) == []


def test_list_runs_returns_most_recent_first(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    run1 = db.start_run(conn)
    db.finish_run(conn, run1, new_job_count=0, failed_sources=["Bad Co"])
    run2 = db.start_run(conn)
    db.finish_run(conn, run2, new_job_count=2, failed_sources=[])

    runs = db.list_runs(conn)

    assert [r["id"] for r in runs] == [run2, run1]
    assert runs[1]["failed_sources"] == ["Bad Co"]


def test_settings_seed_only_when_empty(tmp_db_path):
    conn = db.init_db(tmp_db_path)

    db.seed_settings_if_empty(conn, "smtp.example.com", 587, "user", "from@x.test", "to@x.test")
    db.seed_settings_if_empty(conn, "ignored.example.com", 25, "ignored", "i@x.test", "i2@x.test")

    settings = db.get_settings(conn)
    assert settings["smtp_host"] == "smtp.example.com"


def test_save_settings_overwrites(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_settings(conn, "a.example.com", 587, "u1", "f@x.test", "t@x.test")
    db.save_settings(conn, "b.example.com", 465, "u2", "f2@x.test", "t2@x.test")

    settings = db.get_settings(conn)
    assert settings == {
        "smtp_host": "b.example.com", "smtp_port": 465, "smtp_user": "u2",
        "email_from": "f2@x.test", "email_to": "t2@x.test",
    }
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError` (no `app.db` module yet).

- [ ] **Step 4: Write `app/db.py`**

```python
import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from app.models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    url TEXT NOT NULL,
    posted_date TEXT,
    source_name TEXT NOT NULL,
    first_seen_run_id INTEGER,
    first_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    new_job_count INTEGER NOT NULL DEFAULT 0,
    failed_sources TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    smtp_host TEXT,
    smtp_port INTEGER,
    smtp_user TEXT,
    email_from TEXT,
    email_to TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def get_new_jobs(conn: sqlite3.Connection, jobs: list[Job]) -> list[Job]:
    if not jobs:
        return []
    placeholders = ",".join("?" * len(jobs))
    keys = [j.key for j in jobs]
    rows = conn.execute(f"SELECT key FROM jobs WHERE key IN ({placeholders})", keys).fetchall()
    known = {r[0] for r in rows}
    return [j for j in jobs if j.key not in known]


def save_jobs(conn: sqlite3.Connection, jobs: list[Job], run_id: int) -> None:
    if not jobs:
        return
    now = _now()
    conn.executemany(
        "INSERT OR IGNORE INTO jobs "
        "(key, title, company, location, url, posted_date, source_name, first_seen_run_id, first_seen_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (j.key, j.title, j.company, j.location, j.url, j.posted_date, j.source_name, run_id, now)
            for j in jobs
        ],
    )
    conn.commit()


def start_run(conn: sqlite3.Connection) -> int:
    cur = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (_now(),))
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, new_job_count: int, failed_sources: list[str]) -> None:
    conn.execute(
        "UPDATE runs SET finished_at = ?, new_job_count = ?, failed_sources = ? WHERE id = ?",
        (_now(), new_job_count, json.dumps(failed_sources), run_id),
    )
    conn.commit()


def list_runs(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT id, started_at, finished_at, new_job_count, failed_sources "
        "FROM runs ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "id": r[0], "started_at": r[1], "finished_at": r[2],
            "new_job_count": r[3], "failed_sources": json.loads(r[4]),
        }
        for r in rows
    ]


def get_settings(conn: sqlite3.Connection) -> Optional[dict]:
    row = conn.execute(
        "SELECT smtp_host, smtp_port, smtp_user, email_from, email_to FROM settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    return {
        "smtp_host": row[0], "smtp_port": row[1], "smtp_user": row[2],
        "email_from": row[3], "email_to": row[4],
    }


def save_settings(conn: sqlite3.Connection, smtp_host: str, smtp_port: int, smtp_user: str,
                   email_from: str, email_to: str) -> None:
    conn.execute(
        "INSERT INTO settings (id, smtp_host, smtp_port, smtp_user, email_from, email_to) "
        "VALUES (1, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "smtp_host=excluded.smtp_host, smtp_port=excluded.smtp_port, smtp_user=excluded.smtp_user, "
        "email_from=excluded.email_from, email_to=excluded.email_to",
        (smtp_host, smtp_port, smtp_user, email_from, email_to),
    )
    conn.commit()


def seed_settings_if_empty(conn: sqlite3.Connection, smtp_host: str, smtp_port: int, smtp_user: str,
                            email_from: str, email_to: str) -> None:
    if get_settings(conn) is None:
        save_settings(conn, smtp_host, smtp_port, smtp_user, email_from, email_to)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add app/models.py app/db.py tests/test_db.py
git commit -m "feat: add Job model and SQLite dedup/runs/settings store"
```

---

### Task 3: Config loader & validation

**Files:**
- Create: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `GreenhouseSource`, `LeverSource`, `GenericHtmlSource`, `LinkedInSource`, `IndeedSource` (all Pydantic models with `id: str`, `name: str`, `company: str | None`, `include_keywords: list[str]`, `exclude_keywords: list[str]`, `type: Literal[...]`); `SourceConfig` (discriminated union of the above); `config.load_sources(path) -> list[SourceConfig]`; `config.save_sources(path, sources) -> None`; `config.add_source(path, source) -> None`; `config.update_source(path, source_id, updated) -> None`; `config.delete_source(path, source_id) -> None`; `config.get_source(path, source_id) -> SourceConfig` (raises `KeyError` if missing).

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:

```python
import json

import pytest

from app import config


def write_sources(path, sources_list):
    path.write_text(json.dumps({"sources": sources_list}))


def test_load_sources_parses_each_type(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [
        {"id": "s1", "name": "Acme (Greenhouse)", "type": "greenhouse", "board_token": "acme"},
        {"id": "s2", "name": "Beta (Lever)", "type": "lever", "board_token": "beta"},
        {
            "id": "s3", "name": "Custom Co", "type": "generic_html",
            "url": "https://customco.test/careers",
            "selectors": {"job_card": ".job", "title": ".t", "link": "a"},
        },
        {"id": "s4", "name": "LinkedIn", "type": "linkedin", "url": "https://linkedin.test/jobs"},
        {"id": "s5", "name": "Indeed", "type": "indeed", "url": "https://indeed.test/jobs"},
    ])

    sources = config.load_sources(str(path))

    assert [s.type for s in sources] == ["greenhouse", "lever", "generic_html", "linkedin", "indeed"]
    assert sources[0].board_token == "acme"
    assert sources[2].selectors.job_card == ".job"


def test_add_update_delete_round_trip(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [])

    new_source = config.GreenhouseSource(id="s1", name="Acme", type="greenhouse", board_token="acme")
    config.add_source(str(path), new_source)
    assert [s.id for s in config.load_sources(str(path))] == ["s1"]

    updated = config.GreenhouseSource(id="s1", name="Acme Renamed", type="greenhouse", board_token="acme")
    config.update_source(str(path), "s1", updated)
    assert config.get_source(str(path), "s1").name == "Acme Renamed"

    config.delete_source(str(path), "s1")
    assert config.load_sources(str(path)) == []


def test_update_missing_source_raises(tmp_path):
    path = tmp_path / "sources.json"
    write_sources(path, [])
    updated = config.GreenhouseSource(id="missing", name="X", type="greenhouse", board_token="x")

    with pytest.raises(KeyError):
        config.update_source(str(path), "missing", updated)


def test_source_id_defaults_when_omitted():
    source = config.GreenhouseSource(name="Acme", type="greenhouse", board_token="acme")
    assert source.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`.

- [ ] **Step 3: Write `app/config.py`**

```python
import json
import uuid
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


class BaseSource(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    company: Optional[str] = None
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)


class GreenhouseSource(BaseSource):
    type: Literal["greenhouse"]
    board_token: str


class LeverSource(BaseSource):
    type: Literal["lever"]
    board_token: str


class Selectors(BaseModel):
    job_card: str
    title: str
    link: str
    location: Optional[str] = None


class GenericHtmlSource(BaseSource):
    type: Literal["generic_html"]
    url: str
    render_js: bool = False
    selectors: Selectors


class LinkedInSource(BaseSource):
    type: Literal["linkedin"]
    url: str


class IndeedSource(BaseSource):
    type: Literal["indeed"]
    url: str


SourceConfig = Annotated[
    Union[GreenhouseSource, LeverSource, GenericHtmlSource, LinkedInSource, IndeedSource],
    Field(discriminator="type"),
]


class SourcesFile(BaseModel):
    sources: list[SourceConfig]


def load_sources(path: str) -> list[SourceConfig]:
    with open(path) as f:
        data = json.load(f)
    return SourcesFile.model_validate(data).sources


def save_sources(path: str, sources: list) -> None:
    payload = {"sources": [s.model_dump() for s in sources]}
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


def add_source(path: str, source) -> None:
    sources = load_sources(path)
    sources.append(source)
    save_sources(path, sources)


def update_source(path: str, source_id: str, updated) -> None:
    sources = load_sources(path)
    for i, s in enumerate(sources):
        if s.id == source_id:
            sources[i] = updated
            save_sources(path, sources)
            return
    raise KeyError(source_id)


def delete_source(path: str, source_id: str) -> None:
    sources = load_sources(path)
    remaining = [s for s in sources if s.id != source_id]
    if len(remaining) == len(sources):
        raise KeyError(source_id)
    save_sources(path, remaining)


def get_source(path: str, source_id: str):
    for s in load_sources(path):
        if s.id == source_id:
            return s
    raise KeyError(source_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add sources.json config schema and CRUD helpers"
```

---

### Task 4: Keyword filters

**Files:**
- Create: `app/filters.py`
- Test: `tests/test_filters.py`

**Interfaces:**
- Consumes: `Job` (Task 2).
- Produces: `filters.apply_keyword_filters(jobs: list[Job], include: list[str], exclude: list[str]) -> list[Job]`.

- [ ] **Step 1: Write the failing test**

`tests/test_filters.py`:

```python
from app.filters import apply_keyword_filters
from app.models import Job


def job(title):
    return Job(key=title, title=title, url="https://x.test", source_name="s")


def test_no_filters_returns_all():
    jobs = [job("Backend Engineer"), job("Sales Rep")]
    assert apply_keyword_filters(jobs, [], []) == jobs


def test_include_keyword_is_case_insensitive_substring_match():
    jobs = [job("Backend Engineer"), job("Sales Rep")]
    result = apply_keyword_filters(jobs, ["engineer"], [])
    assert [j.title for j in result] == ["Backend Engineer"]


def test_exclude_keyword_removes_matches():
    jobs = [job("Senior Backend Engineer"), job("Backend Engineer")]
    result = apply_keyword_filters(jobs, [], ["senior"])
    assert [j.title for j in result] == ["Backend Engineer"]


def test_include_and_exclude_combine():
    jobs = [job("Senior Backend Engineer"), job("Backend Engineer"), job("Sales Rep")]
    result = apply_keyword_filters(jobs, ["engineer"], ["senior"])
    assert [j.title for j in result] == ["Backend Engineer"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_filters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.filters'`.

- [ ] **Step 3: Write `app/filters.py`**

```python
from app.models import Job


def apply_keyword_filters(jobs: list[Job], include: list[str], exclude: list[str]) -> list[Job]:
    result = jobs
    if include:
        needles = [k.lower() for k in include]
        result = [j for j in result if any(n in j.title.lower() for n in needles)]
    if exclude:
        needles = [k.lower() for k in exclude]
        result = [j for j in result if not any(n in j.title.lower() for n in needles)]
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_filters.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/filters.py tests/test_filters.py
git commit -m "feat: add include/exclude keyword filtering"
```

---

### Task 5: Adapter base + Greenhouse adapter

**Files:**
- Create: `app/adapters/__init__.py`
- Create: `app/adapters/greenhouse.py`
- Test: `tests/adapters/test_greenhouse.py`
- Test: `tests/adapters/__init__.py`

**Interfaces:**
- Consumes: `Job` (Task 2), `GreenhouseSource` (Task 3).
- Produces: `greenhouse.fetch(source: GreenhouseSource, http_get=requests.get) -> list[Job]`. Every adapter built in later tasks follows this same signature shape: `fetch(source, **injectable_io) -> list[Job]`.

- [ ] **Step 1: Create `tests/adapters/__init__.py`** (empty file)

- [ ] **Step 2: Write the failing test**

`tests/adapters/test_greenhouse.py`:

```python
from app.adapters import greenhouse
from app.config import GreenhouseSource


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_maps_greenhouse_jobs_to_job_objects():
    payload = {
        "jobs": [
            {
                "id": 123,
                "title": "Backend Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                "location": {"name": "Remote"},
                "updated_at": "2026-08-01T00:00:00Z",
            }
        ]
    }
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return FakeResponse(payload)

    source = GreenhouseSource(id="s1", name="Acme (Greenhouse)", company="Acme",
                               type="greenhouse", board_token="acme")

    jobs = greenhouse.fetch(source, http_get=fake_get)

    assert calls == ["https://boards-api.greenhouse.io/v1/boards/acme/jobs"]
    assert len(jobs) == 1
    assert jobs[0].key == "greenhouse:123"
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].url == "https://boards.greenhouse.io/acme/jobs/123"
    assert jobs[0].company == "Acme"
    assert jobs[0].location == "Remote"
    assert jobs[0].source_name == "Acme (Greenhouse)"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/adapters/test_greenhouse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters'`.

- [ ] **Step 4: Write `app/adapters/__init__.py`** (empty file for now — registry is added in Task 10)

- [ ] **Step 5: Write `app/adapters/greenhouse.py`**

```python
import requests

from app.config import GreenhouseSource
from app.models import Job


def fetch(source: GreenhouseSource, http_get=requests.get) -> list[Job]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{source.board_token}/jobs"
    resp = http_get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    jobs = []
    for item in data.get("jobs", []):
        jobs.append(Job(
            key=f"greenhouse:{item['id']}",
            title=item["title"],
            url=item["absolute_url"],
            company=source.company,
            location=(item.get("location") or {}).get("name"),
            posted_date=item.get("updated_at"),
            source_name=source.name,
        ))
    return jobs
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/adapters/test_greenhouse.py -v`
Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add app/adapters/__init__.py app/adapters/greenhouse.py tests/adapters/__init__.py tests/adapters/test_greenhouse.py
git commit -m "feat: add Greenhouse adapter"
```

---

### Task 6: Lever adapter

**Files:**
- Create: `app/adapters/lever.py`
- Test: `tests/adapters/test_lever.py`

**Interfaces:**
- Consumes: `Job` (Task 2), `LeverSource` (Task 3).
- Produces: `lever.fetch(source: LeverSource, http_get=requests.get) -> list[Job]`.

- [ ] **Step 1: Write the failing test**

`tests/adapters/test_lever.py`:

```python
from app.adapters import lever
from app.config import LeverSource


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_maps_lever_postings_to_job_objects():
    payload = [
        {
            "id": "abc-123",
            "text": "Platform Engineer",
            "hostedUrl": "https://jobs.lever.co/beta/abc-123",
            "categories": {"location": "Austin, TX"},
            "createdAt": 1750000000000,
        }
    ]
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return FakeResponse(payload)

    source = LeverSource(id="s1", name="Beta (Lever)", company="Beta Inc",
                          type="lever", board_token="beta")

    jobs = lever.fetch(source, http_get=fake_get)

    assert calls == ["https://api.lever.co/v0/postings/beta?mode=json"]
    assert len(jobs) == 1
    assert jobs[0].key == "lever:abc-123"
    assert jobs[0].title == "Platform Engineer"
    assert jobs[0].url == "https://jobs.lever.co/beta/abc-123"
    assert jobs[0].location == "Austin, TX"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_lever.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.lever'`.

- [ ] **Step 3: Write `app/adapters/lever.py`**

```python
import requests

from app.config import LeverSource
from app.models import Job


def fetch(source: LeverSource, http_get=requests.get) -> list[Job]:
    url = f"https://api.lever.co/v0/postings/{source.board_token}?mode=json"
    resp = http_get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    jobs = []
    for item in data:
        jobs.append(Job(
            key=f"lever:{item['id']}",
            title=item["text"],
            url=item["hostedUrl"],
            company=source.company,
            location=(item.get("categories") or {}).get("location"),
            posted_date=str(item.get("createdAt")) if item.get("createdAt") else None,
            source_name=source.name,
        ))
    return jobs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/adapters/test_lever.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add app/adapters/lever.py tests/adapters/test_lever.py
git commit -m "feat: add Lever adapter"
```

---

### Task 7: Browser render helper + generic_html adapter

**Files:**
- Create: `app/adapters/browser.py`
- Create: `app/adapters/generic_html.py`
- Test: `tests/adapters/test_generic_html.py`

**Interfaces:**
- Consumes: `Job` (Task 2), `GenericHtmlSource` (Task 3).
- Produces: `browser.render_html(url: str) -> str` (real Playwright implementation, not unit-tested directly — see manual smoke test in Task 20); `generic_html.fetch(source: GenericHtmlSource, http_get=requests.get, html_renderer=browser.render_html) -> list[Job]`.

- [ ] **Step 1: Write the failing test**

`tests/adapters/test_generic_html.py`:

```python
from app.adapters import generic_html
from app.config import GenericHtmlSource, Selectors


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


HTML = """
<html><body>
  <div class="job">
    <span class="t">Backend Engineer</span>
    <a href="https://customco.test/jobs/1">apply</a>
    <span class="loc">Remote</span>
  </div>
  <div class="job">
    <span class="t">Sales Rep</span>
    <a href="https://customco.test/jobs/2">apply</a>
    <span class="loc">NYC</span>
  </div>
</body></html>
"""


def selectors():
    return Selectors(job_card=".job", title=".t", link="a", location=".loc")


def test_fetch_static_page_uses_http_get():
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return FakeResponse(HTML)

    source = GenericHtmlSource(id="s1", name="Custom Co", company="Custom Co", type="generic_html",
                                url="https://customco.test/careers", render_js=False, selectors=selectors())

    jobs = generic_html.fetch(source, http_get=fake_get)

    assert calls == ["https://customco.test/careers"]
    assert len(jobs) == 2
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].url == "https://customco.test/jobs/1"
    assert jobs[0].location == "Remote"
    assert jobs[0].source_name == "Custom Co"


def test_fetch_render_js_uses_html_renderer_instead_of_http_get():
    renderer_calls = []

    def fake_renderer(url):
        renderer_calls.append(url)
        return HTML

    def fake_get(url, timeout):
        raise AssertionError("http_get should not be called when render_js is True")

    source = GenericHtmlSource(id="s1", name="Custom Co", company="Custom Co", type="generic_html",
                                url="https://customco.test/careers", render_js=True, selectors=selectors())

    jobs = generic_html.fetch(source, http_get=fake_get, html_renderer=fake_renderer)

    assert renderer_calls == ["https://customco.test/careers"]
    assert len(jobs) == 2


def test_missing_title_or_link_is_skipped_not_crashed():
    html = '<div class="job"><span class="t">No Link</span></div>'

    def fake_get(url, timeout):
        return FakeResponse(html)

    source = GenericHtmlSource(id="s1", name="Custom Co", type="generic_html",
                                url="https://customco.test/careers", selectors=selectors())

    jobs = generic_html.fetch(source, http_get=fake_get)

    assert jobs == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_generic_html.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.generic_html'`.

- [ ] **Step 3: Write `app/adapters/browser.py`**

```python
from playwright.sync_api import sync_playwright


def render_html(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            return page.content()
        finally:
            browser.close()
```

- [ ] **Step 4: Write `app/adapters/generic_html.py`**

```python
import requests
from bs4 import BeautifulSoup

from app.adapters.browser import render_html
from app.config import GenericHtmlSource
from app.models import Job


def fetch(source: GenericHtmlSource, http_get=requests.get, html_renderer=render_html) -> list[Job]:
    if source.render_js:
        html = html_renderer(source.url)
    else:
        resp = http_get(source.url, timeout=15)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select(source.selectors.job_card):
        title_el = card.select_one(source.selectors.title)
        link_el = card.select_one(source.selectors.link)
        if title_el is None or link_el is None:
            continue
        location_el = card.select_one(source.selectors.location) if source.selectors.location else None
        href = link_el.get("href", "")
        title = title_el.get_text(strip=True)
        jobs.append(Job(
            key=f"html:{source.company}:{title}:{href}",
            title=title,
            url=href,
            company=source.company,
            location=location_el.get_text(strip=True) if location_el else None,
            posted_date=None,
            source_name=source.name,
        ))
    return jobs
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/adapters/test_generic_html.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add app/adapters/browser.py app/adapters/generic_html.py tests/adapters/test_generic_html.py
git commit -m "feat: add Playwright render helper and generic_html adapter"
```

---

### Task 8: LinkedIn adapter (best-effort)

**Files:**
- Create: `app/adapters/linkedin.py`
- Test: `tests/adapters/test_linkedin.py`

**Interfaces:**
- Consumes: `Job` (Task 2), `LinkedInSource` (Task 3), `browser.render_html` (Task 7, injectable as `html_renderer`).
- Produces: `linkedin.fetch(source: LinkedInSource, html_renderer=browser.render_html) -> list[Job]`.

- [ ] **Step 1: Write the failing test**

`tests/adapters/test_linkedin.py`:

```python
from app.adapters import linkedin
from app.config import LinkedInSource

HTML = """
<html><body>
  <div class="base-card">
    <h3 class="base-search-card__title">Backend Engineer</h3>
    <h4 class="base-search-card__subtitle">Acme Corp</h4>
    <span class="job-search-card__location">Remote</span>
    <a class="base-card__full-link" href="https://linkedin.test/jobs/view/111?refId=abc">view</a>
  </div>
</body></html>
"""


def test_fetch_parses_linkedin_cards():
    calls = []

    def fake_renderer(url):
        calls.append(url)
        return HTML

    source = LinkedInSource(id="s1", name="LinkedIn - Backend Remote", type="linkedin",
                             url="https://linkedin.test/jobs/search/?keywords=backend")

    jobs = linkedin.fetch(source, html_renderer=fake_renderer)

    assert calls == ["https://linkedin.test/jobs/search/?keywords=backend"]
    assert len(jobs) == 1
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].company == "Acme Corp"
    assert jobs[0].location == "Remote"
    assert jobs[0].url == "https://linkedin.test/jobs/view/111"
    assert jobs[0].key == "linkedin:https://linkedin.test/jobs/view/111"


def test_fetch_returns_empty_list_when_no_cards_match():
    def fake_renderer(url):
        return "<html><body>no jobs here</body></html>"

    source = LinkedInSource(id="s1", name="LinkedIn", type="linkedin", url="https://linkedin.test/jobs")

    assert linkedin.fetch(source, html_renderer=fake_renderer) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_linkedin.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.linkedin'`.

- [ ] **Step 3: Write `app/adapters/linkedin.py`**

```python
from bs4 import BeautifulSoup

from app.adapters.browser import render_html
from app.config import LinkedInSource
from app.models import Job


def fetch(source: LinkedInSource, html_renderer=render_html) -> list[Job]:
    html = html_renderer(source.url)
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("div.base-card"):
        title_el = card.select_one("h3.base-search-card__title")
        link_el = card.select_one("a.base-card__full-link")
        if title_el is None or link_el is None:
            continue
        company_el = card.select_one("h4.base-search-card__subtitle")
        location_el = card.select_one("span.job-search-card__location")
        href = link_el.get("href", "").split("?")[0]
        jobs.append(Job(
            key=f"linkedin:{href}",
            title=title_el.get_text(strip=True),
            url=href,
            company=company_el.get_text(strip=True) if company_el else None,
            location=location_el.get_text(strip=True) if location_el else None,
            posted_date=None,
            source_name=source.name,
        ))
    return jobs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/adapters/test_linkedin.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/adapters/linkedin.py tests/adapters/test_linkedin.py
git commit -m "feat: add best-effort LinkedIn adapter"
```

---

### Task 9: Indeed adapter (best-effort)

**Files:**
- Create: `app/adapters/indeed.py`
- Test: `tests/adapters/test_indeed.py`

**Interfaces:**
- Consumes: `Job` (Task 2), `IndeedSource` (Task 3), `browser.render_html` (Task 7, injectable as `html_renderer`).
- Produces: `indeed.fetch(source: IndeedSource, html_renderer=browser.render_html) -> list[Job]`.

- [ ] **Step 1: Write the failing test**

`tests/adapters/test_indeed.py`:

```python
from app.adapters import indeed
from app.config import IndeedSource

HTML = """
<html><body>
  <div class="job_seen_beacon">
    <h2 class="jobTitle"><a href="/rc/clk?jk=xyz"><span>Backend Engineer</span></a></h2>
    <span class="companyName">Acme Corp</span>
    <div class="companyLocation">Remote</div>
  </div>
</body></html>
"""


def test_fetch_parses_indeed_cards():
    calls = []

    def fake_renderer(url):
        calls.append(url)
        return HTML

    source = IndeedSource(id="s1", name="Indeed - Backend", type="indeed",
                           url="https://indeed.test/jobs?q=backend")

    jobs = indeed.fetch(source, html_renderer=fake_renderer)

    assert calls == ["https://indeed.test/jobs?q=backend"]
    assert len(jobs) == 1
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].company == "Acme Corp"
    assert jobs[0].location == "Remote"
    assert jobs[0].url == "/rc/clk?jk=xyz"
    assert jobs[0].key == "indeed:/rc/clk?jk=xyz"


def test_fetch_returns_empty_list_when_no_cards_match():
    def fake_renderer(url):
        return "<html><body>no jobs here</body></html>"

    source = IndeedSource(id="s1", name="Indeed", type="indeed", url="https://indeed.test/jobs")

    assert indeed.fetch(source, html_renderer=fake_renderer) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_indeed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.indeed'`.

- [ ] **Step 3: Write `app/adapters/indeed.py`**

```python
from bs4 import BeautifulSoup

from app.adapters.browser import render_html
from app.config import IndeedSource
from app.models import Job


def fetch(source: IndeedSource, html_renderer=render_html) -> list[Job]:
    html = html_renderer(source.url)
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("div.job_seen_beacon"):
        title_el = card.select_one("h2.jobTitle span")
        link_el = card.select_one("h2.jobTitle a")
        if title_el is None or link_el is None:
            continue
        company_el = card.select_one("span.companyName")
        location_el = card.select_one("div.companyLocation")
        href = link_el.get("href", "")
        jobs.append(Job(
            key=f"indeed:{href}",
            title=title_el.get_text(strip=True),
            url=href,
            company=company_el.get_text(strip=True) if company_el else None,
            location=location_el.get_text(strip=True) if location_el else None,
            posted_date=None,
            source_name=source.name,
        ))
    return jobs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/adapters/test_indeed.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/adapters/indeed.py tests/adapters/test_indeed.py
git commit -m "feat: add best-effort Indeed adapter"
```

---

### Task 10: Adapter registry + Orchestrator

**Files:**
- Modify: `app/adapters/__init__.py`
- Create: `app/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `db` module (Task 2), `filters.apply_keyword_filters` (Task 4), `SourceConfig` (Task 3), all adapter `fetch` functions (Tasks 5, 6, 7, 8, 9).
- Produces: `ADAPTERS: dict[str, Callable]` mapping `type` string to that type's `fetch` function; `orchestrator.RunSummary` (dataclass: `run_id: int, new_jobs: list[Job], failed_sources: list[str]`); `orchestrator.run_once(conn, sources: list[SourceConfig]) -> RunSummary`.

- [ ] **Step 1: Write the failing test**

`tests/test_orchestrator.py`:

```python
from unittest.mock import patch

from app import db, orchestrator
from app.config import GreenhouseSource, LeverSource
from app.models import Job


def test_run_once_collects_new_jobs_and_isolates_failures(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    good_source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good")
    bad_source = LeverSource(id="s2", name="Bad Co", type="lever", board_token="bad")

    def fake_greenhouse_fetch(source):
        return [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1", source_name=source.name)]

    def fake_lever_fetch(source):
        raise RuntimeError("site is down")

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_greenhouse_fetch, "lever": fake_lever_fetch}):
        summary = orchestrator.run_once(conn, [good_source, bad_source])

    assert [j.key for j in summary.new_jobs] == ["gh:1"]
    assert summary.failed_sources == ["Bad Co"]

    runs = db.list_runs(conn)
    assert runs[0]["id"] == summary.run_id
    assert runs[0]["new_job_count"] == 1
    assert runs[0]["failed_sources"] == ["Bad Co"]


def test_run_once_does_not_report_previously_seen_jobs_as_new(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good")

    def fake_fetch(source):
        return [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1", source_name=source.name)]

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch}):
        first = orchestrator.run_once(conn, [source])
        second = orchestrator.run_once(conn, [source])

    assert len(first.new_jobs) == 1
    assert len(second.new_jobs) == 0


def test_run_once_applies_keyword_filters(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good",
                               include_keywords=["engineer"])

    def fake_fetch(source):
        return [
            Job(key="gh:1", title="Backend Engineer", url="https://x.test/1", source_name=source.name),
            Job(key="gh:2", title="Sales Rep", url="https://x.test/2", source_name=source.name),
        ]

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch}):
        summary = orchestrator.run_once(conn, [source])

    assert [j.key for j in summary.new_jobs] == ["gh:1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.orchestrator'`.

- [ ] **Step 3: Write the adapter registry into `app/adapters/__init__.py`**

```python
from app.adapters import generic_html, greenhouse, indeed, lever, linkedin

ADAPTERS = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "generic_html": generic_html.fetch,
    "linkedin": linkedin.fetch,
    "indeed": indeed.fetch,
}
```

- [ ] **Step 4: Write `app/orchestrator.py`**

```python
import logging
import sqlite3
from dataclasses import dataclass

from app import db
from app.adapters import ADAPTERS
from app.config import SourceConfig
from app.filters import apply_keyword_filters
from app.models import Job

logger = logging.getLogger(__name__)


@dataclass
class RunSummary:
    run_id: int
    new_jobs: list[Job]
    failed_sources: list[str]


def run_once(conn: sqlite3.Connection, sources: list[SourceConfig]) -> RunSummary:
    run_id = db.start_run(conn)
    all_jobs: list[Job] = []
    failed_sources: list[str] = []

    for source in sources:
        adapter = ADAPTERS[source.type]
        try:
            found = adapter(source)
        except Exception:
            logger.exception("Source %r failed", source.name)
            failed_sources.append(source.name)
            continue
        all_jobs.extend(apply_keyword_filters(found, source.include_keywords, source.exclude_keywords))

    new_jobs = db.get_new_jobs(conn, all_jobs)
    db.save_jobs(conn, new_jobs, run_id)
    db.finish_run(conn, run_id, len(new_jobs), failed_sources)
    return RunSummary(run_id=run_id, new_jobs=new_jobs, failed_sources=failed_sources)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add app/adapters/__init__.py app/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add adapter registry and orchestrator with per-source failure isolation"
```

---

### Task 11: Digest builder

**Files:**
- Create: `app/digest.py`
- Test: `tests/test_digest.py`

**Interfaces:**
- Consumes: `Job` (Task 2).
- Produces: `Digest` dataclass (`subject: str, html_body: str`); `digest.build_digest(new_jobs: list[Job], failed_sources: list[str]) -> Digest | None`.

- [ ] **Step 1: Write the failing test**

`tests/test_digest.py`:

```python
from app.digest import build_digest
from app.models import Job


def test_returns_none_when_nothing_new_and_no_failures():
    assert build_digest([], []) is None


def test_groups_new_jobs_by_company():
    jobs = [
        Job(key="1", title="Backend Engineer", url="https://x.test/1", company="Acme", source_name="s"),
        Job(key="2", title="Frontend Engineer", url="https://x.test/2", company="Beta", source_name="s"),
    ]

    result = build_digest(jobs, [])

    assert "2 new job" in result.subject
    assert "Acme" in result.html_body
    assert "Beta" in result.html_body
    assert "Backend Engineer" in result.html_body
    assert "https://x.test/1" in result.html_body


def test_includes_failed_sources_section():
    result = build_digest([], ["Bad Co"])

    assert result is not None
    assert "Bad Co" in result.html_body
    assert "failed" in result.subject.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_digest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.digest'`.

- [ ] **Step 3: Write `app/digest.py`**

```python
from dataclasses import dataclass
from html import escape
from urllib.parse import urlparse

from app.models import Job

_SAFE_URL_SCHEMES = {"http", "https"}


@dataclass
class Digest:
    subject: str
    html_body: str


def _safe_href(url: str) -> str:
    try:
        scheme = urlparse(url).scheme.lower()
    except ValueError:
        return "#"
    if scheme and scheme not in _SAFE_URL_SCHEMES:
        return "#"
    return escape(url, quote=True)


def build_digest(new_jobs: list[Job], failed_sources: list[str]) -> Digest | None:
    if not new_jobs and not failed_sources:
        return None

    subject = f"CareerSpyder: {len(new_jobs)} new job(s)" if new_jobs else "CareerSpyder: run had failed sources"

    parts: list[str] = []
    if new_jobs:
        by_company: dict[str, list[Job]] = {}
        for job in new_jobs:
            by_company.setdefault(job.company or "Unknown", []).append(job)
        for company, jobs in by_company.items():
            parts.append(f"<h3>{escape(company)}</h3><ul>")
            for job in jobs:
                location = f" — {escape(job.location)}" if job.location else ""
                href = _safe_href(job.url)
                title = escape(job.title)
                parts.append(f'<li><a href="{href}">{title}</a>{location}</li>')
            parts.append("</ul>")

    if failed_sources:
        parts.append("<h3>Sources that failed this run</h3><ul>")
        for name in failed_sources:
            parts.append(f"<li>{escape(name)}</li>")
        parts.append("</ul>")

    return Digest(subject=subject, html_body="".join(parts))
```

Job titles, company names, and URLs come from scraped third-party sites and end up
in an emailed HTML body — all text is HTML-escaped and `href` values are restricted
to `http`/`https` schemes (anything else, e.g. `javascript:`, becomes `#`) to
prevent HTML/attribute injection.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_digest.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/digest.py tests/test_digest.py
git commit -m "feat: add digest builder for new jobs and failures"
```

---

### Task 12: Emailer

**Files:**
- Create: `app/emailer.py`
- Test: `tests/test_emailer.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `emailer.send_email(smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str, email_from: str, email_to: str, subject: str, html_body: str) -> None`.

- [ ] **Step 1: Write the failing test**

`tests/test_emailer.py`:

```python
from unittest.mock import MagicMock, patch

from app.emailer import send_email


def test_send_email_logs_in_and_sends_via_starttls():
    with patch("app.emailer.smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        send_email(
            smtp_host="smtp.example.com", smtp_port=587, smtp_user="user",
            smtp_password="secret", email_from="from@x.test", email_to="to@x.test",
            subject="Subject", html_body="<p>Body</p>",
        )

        mock_smtp_cls.assert_called_once_with("smtp.example.com", 587)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user", "secret")
        assert mock_server.sendmail.call_count == 1
        args = mock_server.sendmail.call_args[0]
        assert args[0] == "from@x.test"
        assert args[1] == ["to@x.test"]
        assert "Subject" in args[2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_emailer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.emailer'`.

- [ ] **Step 3: Write `app/emailer.py`**

```python
import smtplib
from email.mime.text import MIMEText


def send_email(smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str,
                email_from: str, email_to: str, subject: str, html_body: str) -> None:
    msg = MIMEText(html_body, "html")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(email_from, [email_to], msg.as_string())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_emailer.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add app/emailer.py tests/test_emailer.py
git commit -m "feat: add SMTP emailer"
```

---

### Task 13: Scheduler

**Files:**
- Create: `app/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `db` (Task 2), `config.load_sources` (Task 3), `orchestrator.run_once` (Task 10), `digest.build_digest` (Task 11), `emailer.send_email` (Task 12).
- Produces: `scheduler.run_and_notify(conn, sources_path: str) -> None`; `scheduler.create_scheduler(conn, sources_path: str, run_hour: int, tz: str) -> BackgroundScheduler`.

- [ ] **Step 1: Write the failing test**

`tests/test_scheduler.py`:

```python
import os
from unittest.mock import patch

from app import db, scheduler
from app.digest import Digest


def test_run_and_notify_sends_email_when_digest_present(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    db.save_settings(conn, "smtp.example.com", 587, "user", "from@x.test", "to@x.test")
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"]})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary) as mock_run_once, \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")) as mock_digest, \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_run_once.assert_called_once()
    mock_digest.assert_called_once_with([], ["Bad Co"])
    mock_send.assert_called_once_with(
        "smtp.example.com", 587, "user", "secret", "from@x.test", "to@x.test", "Subj", "<p>Body</p>",
    )


def test_run_and_notify_skips_email_when_digest_is_none(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    db.save_settings(conn, "smtp.example.com", 587, "user", "from@x.test", "to@x.test")
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": []})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=None), \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_send.assert_not_called()


def test_create_scheduler_registers_daily_cron_job(tmp_db_path, tmp_path):
    conn = db.init_db(tmp_db_path)
    sources_path = str(tmp_path / "sources.json")

    sched = scheduler.create_scheduler(conn, sources_path, run_hour=8, tz="UTC")
    try:
        jobs = sched.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == "daily_run"
    finally:
        sched.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scheduler'`.

- [ ] **Step 3: Write `app/scheduler.py`**

```python
import os

from apscheduler.schedulers.background import BackgroundScheduler

from app import config, db, digest, emailer, orchestrator


def run_and_notify(conn, sources_path: str) -> None:
    sources = config.load_sources(sources_path)
    summary = orchestrator.run_once(conn, sources)
    d = digest.build_digest(summary.new_jobs, summary.failed_sources)
    if d is None:
        return
    settings = db.get_settings(conn)
    emailer.send_email(
        settings["smtp_host"], settings["smtp_port"], settings["smtp_user"],
        os.environ["SMTP_PASSWORD"], settings["email_from"], settings["email_to"],
        d.subject, d.html_body,
    )


def create_scheduler(conn, sources_path: str, run_hour: int, tz: str) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=tz)
    sched.add_job(run_and_notify, "cron", hour=run_hour, args=[conn, sources_path], id="daily_run")
    sched.start()
    return sched
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scheduler.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "feat: add daily scheduler and run-and-notify wiring"
```

---

### Task 14: FastAPI skeleton + startup wiring + Dashboard route

**Files:**
- Create: `app/web/__init__.py`
- Create: `app/web/main.py`
- Create: `app/web/routes_dashboard.py`
- Create: `app/web/templates/base.html`
- Create: `app/web/templates/dashboard.html`
- Test: `tests/web/__init__.py`
- Test: `tests/web/conftest.py`
- Test: `tests/web/test_dashboard.py`

**Interfaces:**
- Consumes: `db.init_db`, `db.seed_settings_if_empty`, `db.list_runs` (Task 2), `scheduler.create_scheduler`, `scheduler.run_and_notify` (Task 13).
- Produces: `app.web.main.app` (FastAPI instance); every later route task imports and extends this `app` via `app.include_router(...)`. Request-scoped state: `request.app.state.conn` (sqlite3.Connection), `request.app.state.sources_path` (str), `request.app.state.scheduler` (BackgroundScheduler).

- [ ] **Step 1: Create `app/web/__init__.py` and `tests/web/__init__.py`** (empty files)

- [ ] **Step 2: Write `tests/web/conftest.py`**

```python
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREERSPYDER_DB_PATH", str(tmp_path / "state.db"))
    sources_path = tmp_path / "sources.json"
    sources_path.write_text(json.dumps({"sources": []}))
    monkeypatch.setenv("CAREERSPYDER_SOURCES_PATH", str(sources_path))
    monkeypatch.setenv("RUN_HOUR", "8")
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("EMAIL_FROM", "from@x.test")
    monkeypatch.setenv("EMAIL_TO", "to@x.test")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")

    from app.web.main import app

    with TestClient(app) as test_client:
        yield test_client
```

- [ ] **Step 3: Write the failing test**

`tests/web/test_dashboard.py`:

```python
def test_dashboard_loads_with_no_runs_yet(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "CareerSpyder" in resp.text


def test_run_now_triggers_background_task_and_redirects(client):
    resp = client.post("/run-now", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/web/test_dashboard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.web.main'`.

- [ ] **Step 5: Write `app/web/templates/base.html`**

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>CareerSpyder</title>
</head>
<body>
  <nav>
    <a href="/">Dashboard</a> |
    <a href="/history">History</a> |
    <a href="/sources">Sources</a> |
    <a href="/settings">Settings</a>
  </nav>
  <hr>
  {% block content %}{% endblock %}
</body>
</html>
```

- [ ] **Step 6: Write `app/web/templates/dashboard.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>CareerSpyder</h1>
<form method="post" action="/run-now">
  <button type="submit">Run now</button>
</form>
{% if last_run %}
  <p>Last run: {{ last_run.started_at }} — {{ last_run.new_job_count }} new job(s)</p>
  {% if last_run.failed_sources %}
    <p>Failed sources: {{ last_run.failed_sources | join(", ") }}</p>
  {% endif %}
{% else %}
  <p>No runs yet.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 7: Write `app/web/routes_dashboard.py`**

```python
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import db
from app.scheduler import run_and_notify

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    runs = db.list_runs(request.app.state.conn, limit=1)
    last_run = runs[0] if runs else None
    return templates.TemplateResponse(request, "dashboard.html", {"last_run": last_run})


@router.post("/run-now")
def run_now(request: Request, background_tasks: BackgroundTasks):
    background_tasks.add_task(run_and_notify, request.app.state.conn, request.app.state.sources_path)
    return RedirectResponse(url="/", status_code=303)
```

- [ ] **Step 8: Write `app/web/main.py`**

```python
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db
from app.scheduler import create_scheduler
from app.web.routes_dashboard import router as dashboard_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("CAREERSPYDER_DB_PATH", "/app/data/state.db")
    sources_path = os.environ.get("CAREERSPYDER_SOURCES_PATH", "/app/config/sources.json")
    run_hour = int(os.environ.get("RUN_HOUR", "8"))
    tz = os.environ.get("TZ", "UTC")

    conn = db.init_db(db_path)
    db.seed_settings_if_empty(
        conn,
        os.environ.get("SMTP_HOST", ""),
        int(os.environ.get("SMTP_PORT", "587")),
        os.environ.get("SMTP_USER", ""),
        os.environ.get("EMAIL_FROM", ""),
        os.environ.get("EMAIL_TO", ""),
    )

    app.state.conn = conn
    app.state.sources_path = sources_path
    app.state.scheduler = create_scheduler(conn, sources_path, run_hour, tz)

    yield

    app.state.scheduler.shutdown()
    conn.close()


app = FastAPI(title="CareerSpyder", lifespan=lifespan)
app.include_router(dashboard_router)
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/web/test_dashboard.py -v`
Expected: 2 passed.

- [ ] **Step 10: Commit**

```bash
git add app/web tests/web/__init__.py tests/web/conftest.py tests/web/test_dashboard.py
git commit -m "feat: add FastAPI app skeleton, startup wiring, and dashboard route"
```

---

### Task 15: History route

**Files:**
- Modify: `app/web/main.py`
- Create: `app/web/routes_history.py`
- Create: `app/web/templates/history.html`
- Test: `tests/web/test_history.py`

**Interfaces:**
- Consumes: `db.list_runs` (Task 2), `app.web.main.app` (Task 14).
- Produces: `GET /history` route.

- [ ] **Step 1: Write the failing test**

`tests/web/test_history.py`:

```python
from app import db


def test_history_lists_past_runs(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_job_count=3, failed_sources=["Bad Co"])

    resp = client.get("/history")

    assert resp.status_code == 200
    assert "3" in resp.text
    assert "Bad Co" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_history.py -v`
Expected: FAIL with 404 (route doesn't exist yet) — assertion `resp.status_code == 200` fails.

- [ ] **Step 3: Write `app/web/templates/history.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Run history</h1>
<table border="1" cellpadding="4">
  <tr><th>Started</th><th>Finished</th><th>New jobs</th><th>Failed sources</th></tr>
  {% for run in runs %}
  <tr>
    <td>{{ run.started_at }}</td>
    <td>{{ run.finished_at or "in progress" }}</td>
    <td>{{ run.new_job_count }}</td>
    <td>{{ run.failed_sources | join(", ") }}</td>
  </tr>
  {% endfor %}
</table>
{% endblock %}
```

- [ ] **Step 4: Write `app/web/routes_history.py`**

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import db

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/history", response_class=HTMLResponse)
def history(request: Request):
    runs = db.list_runs(request.app.state.conn, limit=50)
    return templates.TemplateResponse(request, "history.html", {"runs": runs})
```

- [ ] **Step 5: Wire the router into `app/web/main.py`**

Add near the top: `from app.web.routes_history import router as history_router`
Add after `app.include_router(dashboard_router)`: `app.include_router(history_router)`

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/web/test_history.py -v`
Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add app/web/main.py app/web/routes_history.py app/web/templates/history.html tests/web/test_history.py
git commit -m "feat: add run history page"
```

---

### Task 16: Sources list route + delete

**Files:**
- Modify: `app/web/main.py`
- Create: `app/web/routes_sources.py`
- Create: `app/web/templates/sources_list.html`
- Test: `tests/web/test_sources_list.py`

**Interfaces:**
- Consumes: `config.load_sources`, `config.delete_source` (Task 3), `app.web.main.app` (Task 14).
- Produces: `GET /sources`, `POST /sources/{source_id}/delete` routes. Establishes `app/web/routes_sources.py` as the module Task 17 and Task 18 extend with add/edit/test-preview routes.

- [ ] **Step 1: Write the failing test**

`tests/web/test_sources_list.py`:

```python
import json


def test_sources_list_shows_configured_sources(client):
    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme (Greenhouse)", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.get("/sources")

    assert resp.status_code == 200
    assert "Acme (Greenhouse)" in resp.text


def test_delete_source_removes_it(client):
    sources_path = client.app.state.sources_path
    with open(sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme (Greenhouse)", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.post("/sources/s1/delete", follow_redirects=False)

    assert resp.status_code == 303
    with open(sources_path) as f:
        assert json.load(f)["sources"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_sources_list.py -v`
Expected: FAIL with 404 on `/sources`.

- [ ] **Step 3: Write `app/web/templates/sources_list.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Sources</h1>
<a href="/sources/new">Add source</a>
<table border="1" cellpadding="4">
  <tr><th>Name</th><th>Type</th><th>Company</th><th></th><th></th></tr>
  {% for s in sources %}
  <tr>
    <td>{{ s.name }}</td>
    <td>{{ s.type }}</td>
    <td>{{ s.company or "" }}</td>
    <td><a href="/sources/{{ s.id }}/edit">Edit</a></td>
    <td>
      <form method="post" action="/sources/{{ s.id }}/delete" style="display:inline">
        <button type="submit">Delete</button>
      </form>
    </td>
  </tr>
  {% endfor %}
</table>
{% endblock %}
```

- [ ] **Step 4: Write `app/web/routes_sources.py`**

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import config

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/sources", response_class=HTMLResponse)
def list_sources(request: Request):
    sources = config.load_sources(request.app.state.sources_path)
    return templates.TemplateResponse(request, "sources_list.html", {"sources": sources})


@router.post("/sources/{source_id}/delete")
def delete_source(request: Request, source_id: str):
    config.delete_source(request.app.state.sources_path, source_id)
    return RedirectResponse(url="/sources", status_code=303)
```

- [ ] **Step 5: Wire the router into `app/web/main.py`**

Add near the top: `from app.web.routes_sources import router as sources_router`
Add after `app.include_router(history_router)`: `app.include_router(sources_router)`

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/web/test_sources_list.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add app/web/main.py app/web/routes_sources.py app/web/templates/sources_list.html tests/web/test_sources_list.py
git commit -m "feat: add sources list page with delete action"
```

---

### Task 17: Source add/edit form + save

**Files:**
- Modify: `app/web/routes_sources.py`
- Create: `app/web/source_form.py`
- Create: `app/web/templates/source_form.html`
- Test: `tests/web/test_source_form.py`
- Test: `tests/web/test_source_form_helper.py`

**Interfaces:**
- Consumes: `SourceConfig` types (Task 3), `config.add_source`, `config.update_source`, `config.get_source` (Task 3), `app.web.routes_sources.router` (Task 16).
- Produces: `source_form.source_from_form(form: dict) -> SourceConfig` (raises `pydantic.ValidationError` on bad input — used again by Task 18's preview endpoint); `GET /sources/new`, `GET /sources/{source_id}/edit`, `POST /sources/new`, `POST /sources/{source_id}/edit` routes.

- [ ] **Step 1: Write the failing test for the form-parsing helper**

`tests/web/test_source_form_helper.py`:

```python
import pytest
from pydantic import ValidationError

from app.web.source_form import source_from_form


def test_parses_greenhouse_fields():
    form = {
        "type": "greenhouse", "name": "Acme", "company": "Acme Corp",
        "board_token": "acme", "include_keywords": "engineer, backend", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.type == "greenhouse"
    assert source.board_token == "acme"
    assert source.include_keywords == ["engineer", "backend"]


def test_parses_generic_html_fields_with_selectors():
    form = {
        "type": "generic_html", "name": "Custom Co", "company": "Custom Co",
        "url": "https://customco.test/careers", "render_js": "on",
        "selector_job_card": ".job", "selector_title": ".t", "selector_link": "a",
        "selector_location": ".loc", "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.type == "generic_html"
    assert source.render_js is True
    assert source.selectors.job_card == ".job"


def test_raises_on_missing_required_field():
    form = {"type": "greenhouse", "name": "Acme", "include_keywords": "", "exclude_keywords": ""}
    with pytest.raises(ValidationError):
        source_from_form(form)


def test_preserves_existing_id_when_provided():
    form = {
        "id": "s1", "type": "lever", "name": "Beta", "board_token": "beta",
        "include_keywords": "", "exclude_keywords": "",
    }
    source = source_from_form(form)
    assert source.id == "s1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_source_form_helper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.web.source_form'`.

- [ ] **Step 3: Write `app/web/source_form.py`**

```python
from app.config import (
    GenericHtmlSource,
    GreenhouseSource,
    IndeedSource,
    LeverSource,
    LinkedInSource,
    Selectors,
)

TYPE_MODELS = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "generic_html": GenericHtmlSource,
    "linkedin": LinkedInSource,
    "indeed": IndeedSource,
}


def _keywords(raw: str) -> list[str]:
    return [k.strip() for k in raw.split(",") if k.strip()]


def source_from_form(form: dict):
    common = {
        "name": form["name"],
        "company": form.get("company") or None,
        "include_keywords": _keywords(form.get("include_keywords", "")),
        "exclude_keywords": _keywords(form.get("exclude_keywords", "")),
        "type": form["type"],
    }
    if form.get("id"):
        common["id"] = form["id"]

    source_type = form["type"]
    if source_type in ("greenhouse", "lever"):
        if "board_token" in form:
            common["board_token"] = form["board_token"]
    elif source_type == "generic_html":
        if "url" in form:
            common["url"] = form["url"]
        common["render_js"] = form.get("render_js") == "on"
        common["selectors"] = Selectors(
            job_card=form.get("selector_job_card", ""),
            title=form.get("selector_title", ""),
            link=form.get("selector_link", ""),
            location=form.get("selector_location") or None,
        )
    else:
        if "url" in form:
            common["url"] = form["url"]

    model = TYPE_MODELS[source_type]
    return model.model_validate(common)
```

Type-specific fields are only added to `common` when present in the submitted form
(`if "board_token" in form: ...` rather than `form["board_token"]`) so a genuinely
missing required field surfaces as a pydantic `ValidationError` from
`model_validate` — not a bare `KeyError` from the dict lookup itself.

- [ ] **Step 4: Run form-helper tests to verify they pass**

Run: `pytest tests/web/test_source_form_helper.py -v`
Expected: 4 passed.

- [ ] **Step 5: Write the failing route test**

`tests/web/test_source_form.py`:

```python
import json


def test_new_source_form_renders(client):
    resp = client.get("/sources/new")
    assert resp.status_code == 200
    assert "Add source" in resp.text


def test_post_new_source_saves_and_redirects(client):
    resp = client.post("/sources/new", data={
        "type": "greenhouse", "name": "Acme", "company": "Acme Corp", "board_token": "acme",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/sources"
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["name"] == "Acme"
    assert saved[0]["board_token"] == "acme"


def test_edit_form_prefills_existing_values(client):
    with open(client.app.state.sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.get("/sources/s1/edit")

    assert resp.status_code == 200
    assert 'value="Acme"' in resp.text


def test_post_edit_updates_existing_source(client):
    with open(client.app.state.sources_path, "w") as f:
        json.dump({"sources": [
            {"id": "s1", "name": "Acme", "type": "greenhouse", "board_token": "acme"},
        ]}, f)

    resp = client.post("/sources/s1/edit", data={
        "id": "s1", "type": "greenhouse", "name": "Acme Renamed", "board_token": "acme",
        "include_keywords": "", "exclude_keywords": "",
    }, follow_redirects=False)

    assert resp.status_code == 303
    with open(client.app.state.sources_path) as f:
        saved = json.load(f)["sources"]
    assert saved[0]["name"] == "Acme Renamed"
    assert saved[0]["id"] == "s1"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/web/test_source_form.py -v`
Expected: FAIL with 404 on `/sources/new`.

- [ ] **Step 7: Write `app/web/templates/source_form.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>{{ "Edit source" if source else "Add source" }}</h1>
<form method="post" action="{{ action }}">
  {% if source %}<input type="hidden" name="id" value="{{ source.id }}">{% endif %}
  <label>Name <input type="text" name="name" value="{{ source.name if source else '' }}"></label><br>
  <label>Company <input type="text" name="company" value="{{ source.company if source else '' }}"></label><br>
  <label>Type
    <select name="type" onchange="showFieldsFor(this.value)">
      {% for t in ["greenhouse", "lever", "generic_html", "linkedin", "indeed"] %}
      <option value="{{ t }}" {% if source and source.type == t %}selected{% endif %}>{{ t }}</option>
      {% endfor %}
    </select>
  </label><br>

  <div id="fields-greenhouse" class="type-fields">
    <label>Board token <input type="text" name="board_token" value="{{ source.board_token if source and source.type in ['greenhouse', 'lever'] else '' }}"></label>
  </div>
  <div id="fields-lever" class="type-fields"></div>
  <div id="fields-generic_html" class="type-fields">
    <label>URL <input type="text" name="url" value="{{ source.url if source and source.type in ['generic_html', 'linkedin', 'indeed'] else '' }}"></label><br>
    <label>Render JS <input type="checkbox" name="render_js" {% if source and source.type == 'generic_html' and source.render_js %}checked{% endif %}></label><br>
    <label>Job card selector <input type="text" name="selector_job_card" value="{{ source.selectors.job_card if source and source.type == 'generic_html' else '' }}"></label><br>
    <label>Title selector <input type="text" name="selector_title" value="{{ source.selectors.title if source and source.type == 'generic_html' else '' }}"></label><br>
    <label>Link selector <input type="text" name="selector_link" value="{{ source.selectors.link if source and source.type == 'generic_html' else '' }}"></label><br>
    <label>Location selector <input type="text" name="selector_location" value="{{ source.selectors.location if source and source.type == 'generic_html' and source.selectors.location else '' }}"></label>
  </div>
  <div id="fields-linkedin" class="type-fields"></div>
  <div id="fields-indeed" class="type-fields"></div>

  <label>Include keywords (comma separated) <input type="text" name="include_keywords" value="{{ source.include_keywords | join(', ') if source else '' }}"></label><br>
  <label>Exclude keywords (comma separated) <input type="text" name="exclude_keywords" value="{{ source.exclude_keywords | join(', ') if source else '' }}"></label><br>

  <button type="button" onclick="testSource()">Test this source</button>
  <div id="test-results"></div>
  <button type="submit">Save</button>
</form>

<script>
function showFieldsFor(type) {
  document.querySelectorAll(".type-fields").forEach(el => el.style.display = "none");
  const el = document.getElementById("fields-" + type);
  if (el) el.style.display = "block";
}
showFieldsFor(document.querySelector('select[name="type"]').value);

async function testSource() {
  const form = document.querySelector("form");
  const data = new FormData(form);
  const resp = await fetch("/sources/test-preview", { method: "POST", body: data });
  const result = await resp.json();
  const el = document.getElementById("test-results");
  el.textContent = "";
  if (result.error) {
    el.textContent = "Error: " + result.error;
    return;
  }
  const list = document.createElement("ul");
  result.jobs.forEach(j => {
    const item = document.createElement("li");
    item.textContent = j.title + " - " + j.url;
    list.appendChild(item);
  });
  el.appendChild(list);
}
</script>
{% endblock %}
```

Preview results come from a live scrape of a source you're still editing — the same
untrusted-data caveat as the email digest applies. Results are inserted via
`textContent`/DOM APIs rather than `innerHTML` with template-literal interpolation,
so a scraped title or URL can't inject markup into the admin's own browser.

- [ ] **Step 8: Add form routes to `app/web/routes_sources.py`**

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app import config
from app.web.source_form import source_from_form

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/sources", response_class=HTMLResponse)
def list_sources(request: Request):
    sources = config.load_sources(request.app.state.sources_path)
    return templates.TemplateResponse(request, "sources_list.html", {"sources": sources})


@router.post("/sources/{source_id}/delete")
def delete_source(request: Request, source_id: str):
    config.delete_source(request.app.state.sources_path, source_id)
    return RedirectResponse(url="/sources", status_code=303)


@router.get("/sources/new", response_class=HTMLResponse)
def new_source_form(request: Request):
    return templates.TemplateResponse(request, "source_form.html", {"source": None, "action": "/sources/new"})


@router.post("/sources/new")
async def create_source(request: Request):
    form = dict((await request.form()).items())
    source = source_from_form(form)
    config.add_source(request.app.state.sources_path, source)
    return RedirectResponse(url="/sources", status_code=303)


@router.get("/sources/{source_id}/edit", response_class=HTMLResponse)
def edit_source_form(request: Request, source_id: str):
    source = config.get_source(request.app.state.sources_path, source_id)
    return templates.TemplateResponse(
        request, "source_form.html", {"source": source, "action": f"/sources/{source_id}/edit"}
    )


@router.post("/sources/{source_id}/edit")
async def update_source(request: Request, source_id: str):
    form = dict((await request.form()).items())
    source = source_from_form(form)
    config.update_source(request.app.state.sources_path, source_id, source)
    return RedirectResponse(url="/sources", status_code=303)
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/web/test_source_form.py tests/web/test_sources_list.py -v`
Expected: 6 passed.

- [ ] **Step 10: Commit**

```bash
git add app/web/routes_sources.py app/web/source_form.py app/web/templates/source_form.html tests/web/test_source_form.py tests/web/test_source_form_helper.py
git commit -m "feat: add structured source add/edit form"
```

---

### Task 18: "Test this source" preview endpoint

**Files:**
- Modify: `app/web/routes_sources.py`
- Test: `tests/web/test_source_preview.py`

**Interfaces:**
- Consumes: `source_form.source_from_form` (Task 17), `ADAPTERS` (Task 10).
- Produces: `POST /sources/test-preview` route returning JSON `{"jobs": [{"title": ..., "url": ...}, ...]}` or `{"error": "..."}`.

- [ ] **Step 1: Write the failing test**

`tests/web/test_source_preview.py`:

```python
from unittest.mock import patch

from app.models import Job


def test_preview_returns_jobs_from_adapter(client):
    fake_jobs = [Job(key="k1", title="Backend Engineer", url="https://x.test/1", source_name="Acme")]

    with patch("app.web.routes_sources.ADAPTERS", {"greenhouse": lambda source: fake_jobs}):
        resp = client.post("/sources/test-preview", data={
            "type": "greenhouse", "name": "Acme", "board_token": "acme",
            "include_keywords": "", "exclude_keywords": "",
        })

    assert resp.status_code == 200
    body = resp.json()
    assert body["jobs"] == [{"title": "Backend Engineer", "url": "https://x.test/1"}]


def test_preview_returns_error_on_adapter_failure(client):
    def failing_adapter(source):
        raise RuntimeError("boom")

    with patch("app.web.routes_sources.ADAPTERS", {"greenhouse": failing_adapter}):
        resp = client.post("/sources/test-preview", data={
            "type": "greenhouse", "name": "Acme", "board_token": "acme",
            "include_keywords": "", "exclude_keywords": "",
        })

    assert resp.status_code == 200
    assert resp.json()["error"] == "boom"


def test_preview_returns_error_on_invalid_form(client):
    resp = client.post("/sources/test-preview", data={"type": "greenhouse", "name": "Acme"})
    assert resp.status_code == 200
    assert "error" in resp.json()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_source_preview.py -v`
Expected: FAIL with 404 on `/sources/test-preview`.

- [ ] **Step 3: Add the preview route to `app/web/routes_sources.py`**

Add import near the top: `from app.adapters import ADAPTERS`

Add at the end of the file:

```python
@router.post("/sources/test-preview")
async def test_source_preview(request: Request):
    form = dict((await request.form()).items())
    try:
        source = source_from_form(form)
    except ValidationError as exc:
        return {"error": str(exc)}
    try:
        jobs = ADAPTERS[source.type](source)
    except Exception as exc:
        return {"error": str(exc)}
    return {"jobs": [{"title": j.title, "url": j.url} for j in jobs]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/web/test_source_preview.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/web/routes_sources.py tests/web/test_source_preview.py
git commit -m "feat: add test-preview endpoint for validating a source before saving"
```

---

### Task 19: Settings route

**Files:**
- Modify: `app/web/main.py`
- Create: `app/web/routes_settings.py`
- Create: `app/web/templates/settings.html`
- Test: `tests/web/test_settings.py`

**Interfaces:**
- Consumes: `db.get_settings`, `db.save_settings` (Task 2), `app.web.main.app` (Task 14).
- Produces: `GET /settings`, `POST /settings` routes.

- [ ] **Step 1: Write the failing test**

`tests/web/test_settings.py`:

```python
def test_settings_page_shows_current_values(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert 'value="smtp.example.com"' in resp.text


def test_settings_page_does_not_expose_password_field(client):
    resp = client.get("/settings")
    assert 'name="smtp_password"' not in resp.text
    assert 'name="password"' not in resp.text


def test_post_settings_saves_new_values(client):
    resp = client.post("/settings", data={
        "smtp_host": "smtp2.example.com", "smtp_port": "465",
        "smtp_user": "user2", "email_from": "from2@x.test", "email_to": "to2@x.test",
    }, follow_redirects=False)

    assert resp.status_code == 303

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["smtp_host"] == "smtp2.example.com"
    assert settings["smtp_port"] == 465
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_settings.py -v`
Expected: FAIL with 404 on `/settings`.

- [ ] **Step 3: Write `app/web/templates/settings.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Email settings</h1>
<p>SMTP password is set via the <code>SMTP_PASSWORD</code> environment variable and is not editable here.</p>
<form method="post" action="/settings">
  <label>SMTP host <input type="text" name="smtp_host" value="{{ settings.smtp_host }}"></label><br>
  <label>SMTP port <input type="number" name="smtp_port" value="{{ settings.smtp_port }}"></label><br>
  <label>SMTP user <input type="text" name="smtp_user" value="{{ settings.smtp_user }}"></label><br>
  <label>From address <input type="text" name="email_from" value="{{ settings.email_from }}"></label><br>
  <label>To address <input type="text" name="email_to" value="{{ settings.email_to }}"></label><br>
  <button type="submit">Save</button>
</form>
{% endblock %}
```

- [ ] **Step 4: Write `app/web/routes_settings.py`**

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import db

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/settings", response_class=HTMLResponse)
def show_settings(request: Request):
    settings = db.get_settings(request.app.state.conn)
    return templates.TemplateResponse(request, "settings.html", {"settings": settings})


@router.post("/settings")
async def save_settings(request: Request):
    form = dict((await request.form()).items())
    db.save_settings(
        request.app.state.conn,
        form["smtp_host"], int(form["smtp_port"]), form["smtp_user"],
        form["email_from"], form["email_to"],
    )
    return RedirectResponse(url="/settings", status_code=303)
```

- [ ] **Step 5: Wire the router into `app/web/main.py`**

Add near the top: `from app.web.routes_settings import router as settings_router`
Add after `app.include_router(sources_router)`: `app.include_router(settings_router)`

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/web/test_settings.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add app/web/main.py app/web/routes_settings.py app/web/templates/settings.html tests/web/test_settings.py
git commit -m "feat: add email settings page (SMTP password stays env-var only)"
```

---

### Task 20: Docker packaging + manual smoke test

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: the full `app` package built in Tasks 1-19.
- Produces: a runnable container image exposing port `8080`, with `/app/config` and `/app/data` as volumes.

- [ ] **Step 1: Write `.dockerignore`**

```
.git
.pytest_cache
**/__pycache__
tests
docs
*.md
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .
RUN playwright install --with-deps chromium

COPY app app

RUN mkdir -p /app/config /app/data

EXPOSE 8080
CMD ["uvicorn", "app.web.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
services:
  careerspyder:
    build: .
    image: careerspyder:latest
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      SMTP_PASSWORD: ${SMTP_PASSWORD}
      SMTP_HOST: ${SMTP_HOST:-}
      SMTP_PORT: ${SMTP_PORT:-587}
      SMTP_USER: ${SMTP_USER:-}
      EMAIL_FROM: ${EMAIL_FROM:-}
      EMAIL_TO: ${EMAIL_TO:-}
      RUN_HOUR: ${RUN_HOUR:-8}
      TZ: ${TZ:-UTC}
      CAREERSPYDER_DB_PATH: /app/data/state.db
      CAREERSPYDER_SOURCES_PATH: /app/config/sources.json
    volumes:
      - ./config:/app/config
      - ./data:/app/data
```

- [ ] **Step 4: Build the image**

Run: `docker build -t careerspyder:latest .`
Expected: image builds successfully (this step also installs Playwright's Chromium, so it will take a few minutes the first time).

- [ ] **Step 5: Run the full automated test suite one more time before deploying**

Run: `pytest`
Expected: all tests from Tasks 1-19 pass.

- [ ] **Step 6: Manual smoke test**

1. Create `./config/sources.json` locally with one real Greenhouse source (pick any public `board_token` from a company you know uses Greenhouse) and one real `generic_html` source pointing at a careers page you control the selectors for.
2. Set `SMTP_PASSWORD` (and the other `SMTP_*`/`EMAIL_*` vars) in a local `.env` file.
3. Run: `docker compose up`
4. Open `http://localhost:8080/` in a browser, click "Run now".
5. Confirm the dashboard shows new jobs found (or failed sources, if a selector is wrong), `/history` shows the run, `/sources` lists your entries, and — if new jobs were found — a real email digest arrives.

- [ ] **Step 7: Commit**

```bash
git add Dockerfile docker-compose.yml .dockerignore
git commit -m "chore: add Docker packaging for Portainer/Proxmox deployment"
```

---

## Self-Review Notes

- **Spec coverage:** every section of `docs/superpowers/specs/2026-08-09-careerspyder-design.md` maps to a task — architecture/components (Tasks 2-14), config schema (Task 3), web UI pages (Tasks 14-19), deployment (Task 20), error handling (Task 10's per-source isolation + logging), secrets split (Task 19), testing plan (fixture-based adapter tests in Tasks 5-9, dedup/run tests in Task 2, orchestrator integration test in Task 10, manual smoke test in Task 20).
- **Placeholder scan:** none remaining — all test bodies contain real assertions.
- **Type consistency:** `Job`, `SourceConfig` (and its 5 variants), `RunSummary`, `Digest`, and `ADAPTERS` are defined once (Tasks 2, 3, 10, 11) and referenced identically by name in every later task.
