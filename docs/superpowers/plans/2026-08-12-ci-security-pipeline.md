# CI/Security Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GitHub Actions pipeline (lint, typecheck, tests, dependency audit, Docker build + container scan + smoke test, CodeQL SAST) plus Dependabot and repo-level security settings, so CareerSpyder's tests and security posture are verified automatically on every PR and push to `master` instead of manually.

**Architecture:** Three workflow files split by speed/purpose (`ci.yml` for fast always-on code-quality jobs, `docker.yml` for the slower image build+scan+smoke-test, `codeql.yml` for SAST with its own permission scope and weekly schedule), plus `.github/dependabot.yml` for automated dependency PRs. Before any gate goes live, the ~19 mypy errors and 9 ruff findings already present in `app/` get fixed so `mypy`/`ruff` land as genuinely green gates. The final task pushes the branch, opens a PR, proves each gate actually blocks on a deliberate break-and-revert, then applies the two repo-settings changes (secret scanning + push protection, branch protection with required checks).

**Tech Stack:** GitHub Actions, ruff, mypy, pip-audit, Trivy (`aquasecurity/trivy-action`), CodeQL (`github/codeql-action`), Dependabot. No new runtime dependencies — this only affects CI and dev tooling.

## Global Constraints

- Repo is `jasonkryst/CareerSpyder`, public — CodeQL, secret scanning, and Dependabot are free; no cost tradeoffs affect tool choice.
- Every workflow triggers on `pull_request` and `push` to `master`. `codeql.yml` additionally runs on a weekly `schedule` (`0 6 * * 1`, Monday 06:00 UTC) — the others only need to react to a diff.
- CI Python version is pinned to `3.12` (matches `Dockerfile`'s `python:3.12-slim`) — do not use a version matrix.
- `mypy` targets `app/` only, not `tests/` (configured via `files = ["app"]` in `pyproject.toml`).
- `ruff` uses `target-version = "py312"` with no custom `select` — its default rule set is what was scoped against this codebase.
- Trivy scans the exact image `docker compose build` produces (`careerspyder:latest`), severity `CRITICAL,HIGH`, `ignore-unfixed: "true"` (there is no point failing the build on a CVE with no available fix — verified empirically: as of this plan, the image has real CRITICAL/HIGH findings in OS packages with no fix yet, and zero once unfixed ones are excluded), `exit-code: "1"`.
- The Docker smoke test checks `/`, `/sources`, `/history`, `/settings` all return HTTP 200 against a container started with an empty `sources.json` and placeholder SMTP env vars (no real email send is attempted, matching the project's existing "digest sent only when there's something to report" behavior).
- All third-party and first-party GitHub Actions are pinned to a full commit SHA with a version comment (e.g. `uses: actions/checkout@<sha> # v7.0.1`), not a mutable tag — supply-chain hardening consistent with the "solid and secure" goal of this work.
- Branch protection (required status checks on `master`) is applied only after the workflows have run at least once on the implementation PR and their exact check names are confirmed — a required check that has never reported blocks merging until it does.
- Design spec: `docs/superpowers/specs/2026-08-12-ci-security-pipeline-design.md`. Tracking issue: `https://github.com/jasonkryst/CareerSpyder/issues/1`.

---

### Task 1: Dev tooling (ruff, mypy, pip-audit) + fix all current ruff findings

**Files:**
- Modify: `pyproject.toml`
- Modify: `app/db.py`, `app/models.py`, `app/config.py`, `app/web/routes_sources.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ruff check app tests` passes clean; `mypy` (using the new `[tool.mypy]` config) runs and reports a known, expected set of pre-existing errors (fixed in Tasks 2-4); `pip-audit` is installed and runnable.

- [ ] **Step 1: Add `ruff`, `mypy`, `pip-audit` to dev dependencies and add tool config**

In `pyproject.toml`, replace:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "httpx>=0.27",
]

[tool.setuptools.packages.find]
include = ["app*"]

[tool.setuptools]
include-package-data = true

[tool.setuptools.package-data]
"app.web" = ["templates/*.html"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

with:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "httpx>=0.27",
    "ruff>=0.6",
    "mypy>=1.10",
    "pip-audit>=2.7",
]

[tool.setuptools.packages.find]
include = ["app*"]

[tool.setuptools]
include-package-data = true

[tool.setuptools.package-data]
"app.web" = ["templates/*.html"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"

[tool.mypy]
python_version = "3.12"
files = ["app"]

[[tool.mypy.overrides]]
module = "apscheduler.*"
ignore_missing_imports = true
```

- [ ] **Step 2: Install the new dev tooling**

Run: `pip install -e ".[dev]"`
Expected: `ruff`, `mypy`, and `pip-audit` install without error alongside the existing dev deps.

- [ ] **Step 3: Run ruff to see the current findings**

Run: `ruff check app tests`
Expected: 9-10 findings (exact count may drift slightly with ruff's own version bumps, but the categories are: `UP045`/`UP007` `Optional[X]`/`Union[X, Y]` → `X | None`/`X | Y` modernization in `app/db.py`, `app/models.py`, `app/config.py`; one `BLE001` blind-except in `app/web/routes_sources.py`).

- [ ] **Step 4: Auto-fix the mechanical findings**

Run: `ruff check app tests --fix`
Expected: all `UP045`/`UP007` findings are fixed automatically across `app/db.py`, `app/models.py`, `app/config.py` (and anywhere else ruff finds them). One `BLE001` finding remains in `app/web/routes_sources.py` — that one needs a manual, justified suppression (Step 5), not an auto-fix, since blind-except is a real design choice there, not a mechanical modernization.

- [ ] **Step 5: Suppress the intentional blind-except with a justifying comment**

In `app/web/routes_sources.py`, the `/sources/test-preview` route currently has:

```python
    try:
        jobs = await run_in_threadpool(ADAPTERS[source.type], source)
    except Exception as exc:
        return {"error": str(exc)}
```

Change to:

```python
    try:
        # Adapters raise heterogeneous exceptions (requests, BeautifulSoup
        # selectors, Playwright) — this endpoint's job is to report any of
        # them back to the UI as a preview error, not to crash.
        jobs = await run_in_threadpool(ADAPTERS[source.type], source)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
```

(Note: the `jobs` variable gets a type annotation in Task 4, when the return type of `run_in_threadpool` needs help from an explicit `Callable` type on `ADAPTERS` — don't add one here, it'll conflict with Task 4's edit.)

- [ ] **Step 6: Verify ruff is clean**

Run: `ruff check app tests`
Expected: `All checks passed!`

- [ ] **Step 7: Confirm mypy runs (not yet clean — that's Tasks 2-4)**

Run: `mypy`
Expected: reports errors (around 19, across `app/db.py`, `app/web/routes_settings.py`, `app/web/source_form.py`, `app/adapters/indeed.py`, `app/adapters/generic_html.py`, `app/adapters/linkedin.py`, `app/web/routes_sources.py`, `app/orchestrator.py`, `app/scheduler.py`) — this confirms the new `[tool.mypy]` config in `pyproject.toml` is wired correctly (no `ModuleNotFoundError`, no config-parsing error) even though the errors themselves aren't fixed until later tasks. Do NOT try to fix any of them in this task.

- [ ] **Step 8: Run the full test suite to confirm no regression**

Run: `pytest -q`
Expected: all existing tests still pass (ruff's auto-fixes are non-behavioral type-annotation syntax changes only).

- [ ] **Step 9: Run pip-audit**

Run: `pip-audit`
Expected: `No known vulnerabilities found` (plus a "careerspyder ... could not be audited" skip line for the local package itself, which is expected and not an error).

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml app/db.py app/models.py app/config.py app/web/routes_sources.py
git commit -m "chore: add ruff/mypy/pip-audit dev tooling, fix current ruff findings"
```

---

### Task 2: Fix mypy errors in the adapter href-narrowing (indeed, generic_html, linkedin)

**Files:**
- Modify: `app/adapters/indeed.py`, `app/adapters/generic_html.py`, `app/adapters/linkedin.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: no behavior change — `mypy` no longer reports errors for these three files.

**Context:** BeautifulSoup's type stubs type `Tag.get(key, default)` as returning `str | AttributeValueList | None` regardless of the default's type, so mypy can't follow `.get("href", "").split(...)` or pass the result straight into `urljoin`. Coercing with `str(...)` is safe at runtime (the value is always a plain string for an `href` attribute in practice — verified by the existing fixture-based adapter tests) and satisfies mypy.

- [ ] **Step 1: Fix `app/adapters/indeed.py`**

Change:

```python
        href = urljoin(source.url, link_el.get("href", ""))
```

to:

```python
        href = urljoin(source.url, str(link_el.get("href", "")))
```

- [ ] **Step 2: Fix `app/adapters/generic_html.py`**

Change:

```python
        href = urljoin(source.url, link_el.get("href", ""))
```

to:

```python
        href = urljoin(source.url, str(link_el.get("href", "")))
```

- [ ] **Step 3: Fix `app/adapters/linkedin.py`**

Change:

```python
        href = link_el.get("href", "").split("?")[0]
```

to:

```python
        href = str(link_el.get("href", "")).split("?")[0]
```

- [ ] **Step 4: Run the existing adapter tests to confirm no regression**

Run: `pytest tests/adapters/test_indeed.py tests/adapters/test_generic_html.py tests/adapters/test_linkedin.py -v`
Expected: all pass (these tests already assert on `href`/`url` values with real fixture HTML, so a behavior change here would show up as a failure).

- [ ] **Step 5: Confirm mypy no longer flags these three files**

Run: `mypy`
Expected: no errors reported for `app/adapters/indeed.py`, `app/adapters/generic_html.py`, or `app/adapters/linkedin.py` (other files still have errors — fixed in Tasks 3-4).

- [ ] **Step 6: Commit**

```bash
git add app/adapters/indeed.py app/adapters/generic_html.py app/adapters/linkedin.py
git commit -m "fix: narrow bs4 attribute type in adapter href handling for mypy"
```

---

### Task 3: Fix mypy errors in db.py and scheduler.py (real behavioral gaps)

**Files:**
- Modify: `app/db.py`, `app/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `db.start_run` keeps its `-> int` contract with an explicit runtime guarantee instead of an unchecked `int | None`; `scheduler.run_and_notify` explicitly handles "no settings configured yet" instead of relying on the existing broad `except Exception` to catch an indexing error incidentally.

- [ ] **Step 1: Fix `app/db.py`'s `start_run`**

Change:

```python
def start_run(conn: sqlite3.Connection) -> int:
    cur = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (_now(),))
    conn.commit()
    return cur.lastrowid
```

to:

```python
def start_run(conn: sqlite3.Connection) -> int:
    cur = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (_now(),))
    conn.commit()
    assert cur.lastrowid is not None
    return cur.lastrowid
```

(`lastrowid` is typed `int | None` by the stdlib stubs since it's `None` for statements that don't insert a row — an `INSERT` into an autoincrement table always sets it, so the `assert` documents a real invariant rather than defensively working around a case that can occur here.)

- [ ] **Step 2: Write a failing test for the scheduler's missing-settings behavior**

In `tests/test_scheduler.py`, add (after the existing `test_run_and_notify_does_not_crash_when_smtp_password_unset` test, before `test_create_scheduler_registers_daily_cron_job`):

```python
def test_run_and_notify_skips_email_when_no_settings_configured(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    # No db.save_settings call, so db.get_settings(conn) returns None.
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"], "run_id": 1})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)  # must not raise

    mock_send.assert_not_called()
```

- [ ] **Step 3: Run the test to verify it currently passes for the wrong reason**

Run: `pytest tests/test_scheduler.py::test_run_and_notify_skips_email_when_no_settings_configured -v`
Expected: PASS — but only because the existing broad `except Exception: logger.exception(...)` around the email send happens to catch the `TypeError` from indexing `None`. This is the "passes for the wrong reason" case that Step 4 replaces with an explicit, correctly-typed check.

- [ ] **Step 4: Add an explicit None-check in `app/scheduler.py`**

Change:

```python
    settings = db.get_settings(conn)
    try:
        emailer.send_email(
```

to:

```python
    settings = db.get_settings(conn)
    if settings is None:
        logger.warning("Skipping digest email for run %s: no settings configured", summary.run_id)
        return
    try:
        emailer.send_email(
```

- [ ] **Step 5: Run the test again to verify it passes for the right reason**

Run: `pytest tests/test_scheduler.py -v`
Expected: all tests in the file pass, including the new one — now via the explicit early return, not the broad except.

- [ ] **Step 6: Run the full test suite to confirm no regression**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 7: Confirm mypy no longer flags these two files**

Run: `mypy`
Expected: no errors reported for `app/db.py` or `app/scheduler.py`.

- [ ] **Step 8: Commit**

```bash
git add app/db.py app/scheduler.py tests/test_scheduler.py
git commit -m "fix: guarantee start_run's lastrowid and handle unconfigured settings explicitly"
```

---

### Task 4: Fix mypy errors in the web/dispatch layer (routes_settings, source_form, adapters registry, routes_sources)

**Files:**
- Modify: `app/web/routes_settings.py`, `app/web/source_form.py`, `app/adapters/__init__.py`, `app/web/routes_sources.py`
- Test: `tests/web/test_settings.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `mypy` reports zero errors project-wide after this task (the full gate `ruff check app tests` + `mypy` is genuinely green from here on). `app.adapters.ADAPTERS` is typed `dict[str, Callable[..., list[Job]]]` — later code (including this task's own `routes_sources.py` edit) can rely on that type.

**Context:** Starlette types form field values as `str | UploadFile` (forms can carry file uploads), so `app/web/routes_settings.py`'s form handling needs to narrow to `str` before using values as SMTP settings — this is also a genuine (if minor) hardening: today, POSTing a file for e.g. `smtp_host` hits `int(form["smtp_port"])` on an `UploadFile` and 500s; after this fix it 400s cleanly, consistent with the rest of the source-form validation added in the prior review round. `TYPE_MODELS` and `ADAPTERS` are both "dispatch by string key" dicts whose inferred value types are too loose for mypy to follow through a call — explicit annotations fix both.

- [ ] **Step 1: Write a failing test for the settings form's file-upload guard**

In `tests/web/test_settings.py`, add (after `test_post_settings_saves_new_values`):

```python
def test_post_settings_rejects_file_upload_field(client):
    resp = client.post(
        "/settings",
        data={"smtp_port": "465", "smtp_user": "user2", "email_from": "from2@x.test", "email_to": "to2@x.test"},
        files={"smtp_host": ("evil.txt", b"not a hostname")},
    )

    assert resp.status_code == 400
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/web/test_settings.py::test_post_settings_rejects_file_upload_field -v`
Expected: FAIL — currently raises an unhandled `TypeError` from `int(form["smtp_port"])` receiving an `UploadFile`-adjacent value, which FastAPI turns into a 500, not the expected 400.

- [ ] **Step 3: Add the string-field guard and use it in `app/web/routes_settings.py`**

Change:

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db
from app.web.templating import templates

router = APIRouter()


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

to:

```python
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db
from app.web.templating import templates

router = APIRouter()


def _str_field(form: dict, key: str) -> str:
    value = form[key]
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{key} must be a text field")
    return value


@router.get("/settings", response_class=HTMLResponse)
def show_settings(request: Request):
    settings = db.get_settings(request.app.state.conn)
    return templates.TemplateResponse(request, "settings.html", {"settings": settings})


@router.post("/settings")
async def save_settings(request: Request):
    form = dict((await request.form()).items())
    db.save_settings(
        request.app.state.conn,
        _str_field(form, "smtp_host"), int(_str_field(form, "smtp_port")), _str_field(form, "smtp_user"),
        _str_field(form, "email_from"), _str_field(form, "email_to"),
    )
    return RedirectResponse(url="/settings", status_code=303)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/web/test_settings.py -v`
Expected: all tests in the file pass, including the new one.

- [ ] **Step 5: Fix `app/web/source_form.py`'s `TYPE_MODELS` dispatch typing**

Change:

```python
from types import SimpleNamespace

from app.config import (
    GenericHtmlSource,
    GreenhouseSource,
    IndeedSource,
    LeverSource,
    LinkedInSource,
    Selectors,
)

TYPE_MODELS = {
```

to:

```python
from types import SimpleNamespace

from pydantic import BaseModel

from app.config import (
    GenericHtmlSource,
    GreenhouseSource,
    IndeedSource,
    LeverSource,
    LinkedInSource,
    Selectors,
)

TYPE_MODELS: dict[str, type[BaseModel]] = {
```

(leave the rest of the dict body and the rest of the file unchanged.)

- [ ] **Step 6: Fix `app/adapters/__init__.py`'s `ADAPTERS` dispatch typing**

Change:

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

to:

```python
from collections.abc import Callable

from app.adapters import generic_html, greenhouse, indeed, lever, linkedin
from app.models import Job

ADAPTERS: dict[str, Callable[..., list[Job]]] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "generic_html": generic_html.fetch,
    "linkedin": linkedin.fetch,
    "indeed": indeed.fetch,
}
```

(`Callable[..., list[Job]]` rather than a precise per-adapter parameter signature: the five `fetch` functions have different parameter types/defaults for their first argument's subtype and their injectable-IO kwargs, and mypy's contravariant parameter checking would reject assigning any of them to a `Callable[[SourceConfig], list[Job]]`-typed dict value. `...` correctly expresses "called positionally with one arg, returns `list[Job]`" without mypy trying to unify five incompatible parameter lists.)

- [ ] **Step 7: Add the type annotation `run_in_threadpool` needs in `app/web/routes_sources.py`**

Change:

```python
    try:
        # Adapters raise heterogeneous exceptions (requests, BeautifulSoup
        # selectors, Playwright) — this endpoint's job is to report any of
        # them back to the UI as a preview error, not to crash.
        jobs = await run_in_threadpool(ADAPTERS[source.type], source)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
```

to:

```python
    try:
        # Adapters raise heterogeneous exceptions (requests, BeautifulSoup
        # selectors, Playwright) — this endpoint's job is to report any of
        # them back to the UI as a preview error, not to crash.
        jobs: list = await run_in_threadpool(ADAPTERS[source.type], source)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
```

- [ ] **Step 8: Run the full test suite to confirm no regression**

Run: `pytest -q`
Expected: all tests pass (73 total after Task 3's and this task's new tests).

- [ ] **Step 9: Confirm mypy is fully clean project-wide**

Run: `mypy`
Expected: `Success: no issues found in 24 source files`

- [ ] **Step 10: Confirm ruff is still clean**

Run: `ruff check app tests`
Expected: `All checks passed!`

- [ ] **Step 11: Commit**

```bash
git add app/web/routes_settings.py app/web/source_form.py app/adapters/__init__.py app/web/routes_sources.py tests/web/test_settings.py
git commit -m "fix: narrow dispatch-dict and form-field typing so mypy is fully clean"
```

---

### Task 5: `ci.yml` — lint, typecheck, test, dependency-audit workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the `ruff`/`mypy`/`pip-audit` config from Task 1, and the now-clean codebase from Tasks 1-4.
- Produces: a GitHub Actions workflow with four independent jobs — `lint`, `typecheck`, `test`, `dependency-audit` — each a required-status-check candidate by that exact job id.

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [master]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: ruff check app tests

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: mypy

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: pytest -q

  dependency-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: pip-audit
```

(Each job does its own checkout/setup/install rather than sharing a setup job — the install takes seconds, and independent jobs run in parallel and fail independently without a shared single point of failure.)

- [ ] **Step 2: Validate the workflow syntax with actionlint**

Run: `docker run --rm -v "$(pwd):/repo" -w /repo rhysd/actionlint:latest -color` (on Windows/Git Bash, prefix with `MSYS_NO_PATHCONV=1` and use `-w //repo` to avoid path mangling)
Expected: no output, exit code 0.

- [ ] **Step 3: Confirm each job's command already passes locally** (proves the workflow will go green once pushed, without waiting on Actions)

Run in sequence: `ruff check app tests`, `mypy`, `pytest -q`, `pip-audit`
Expected: all four pass — this was already confirmed at the end of Task 4, re-confirming here specifically because these are the literal commands the workflow runs.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint/typecheck/test/dependency-audit workflow"
```

---

### Task 6: `docker.yml` — build, Trivy scan, smoke test workflow

**Files:**
- Create: `.github/workflows/docker.yml`

**Interfaces:**
- Consumes: `Dockerfile` and `docker-compose.yml` (unchanged, from the v1 release).
- Produces: a GitHub Actions workflow with one job, `build-scan-smoketest`, that builds the exact image `docker compose` runs, scans it, and exercises all four web UI pages against a running container.

- [ ] **Step 1: Create `.github/workflows/docker.yml`**

```yaml
name: Docker

on:
  pull_request:
  push:
    branches: [master]

jobs:
  build-scan-smoketest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1

      - name: Build image
        run: docker compose build

      - name: Scan image for vulnerabilities
        uses: aquasecurity/trivy-action@a9c7b0f06e461e9d4b4d1711f154ee024b8d7ab8 # v0.36.0
        with:
          image-ref: careerspyder:latest
          severity: CRITICAL,HIGH
          ignore-unfixed: "true"
          exit-code: "1"
          format: table

      - name: Start container
        run: |
          mkdir -p config data
          echo '{"sources": []}' > config/sources.json
          cat > .env <<'EOF'
          SMTP_PASSWORD=ci-placeholder
          SMTP_HOST=localhost
          SMTP_PORT=587
          SMTP_USER=ci
          EMAIL_FROM=ci@example.test
          EMAIL_TO=ci@example.test
          RUN_HOUR=8
          TZ=UTC
          EOF
          docker compose up -d

      - name: Wait for app to respond
        run: |
          for _ in $(seq 1 30); do
            if curl -sf http://localhost:8080/ > /dev/null; then
              exit 0
            fi
            sleep 2
          done
          echo "App never became ready" >&2
          docker compose logs
          exit 1

      - name: Smoke test all pages
        run: |
          for path in / /sources /history /settings; do
            status=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8080$path")
            if [ "$status" != "200" ]; then
              echo "GET $path returned $status, expected 200" >&2
              docker compose logs
              exit 1
            fi
            echo "GET $path -> 200"
          done

      - name: Tear down
        if: always()
        run: docker compose down
```

(`docker compose build` — not a standalone `docker build`— because `docker-compose.yml` declares `image: careerspyder:latest`; building this way guarantees the Trivy scan and the smoke test both operate on the exact same image, with no separate/duplicate build.)

- [ ] **Step 2: Validate the workflow syntax with actionlint**

Run: `docker run --rm -v "$(pwd):/repo" -w /repo rhysd/actionlint:latest -color` (Windows/Git Bash: `MSYS_NO_PATHCONV=1 ... -w //repo`)
Expected: no output, exit code 0.

- [ ] **Step 3: Dry-run the build + scan locally**

Run: `docker compose build`, then `docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 careerspyder:latest`
Expected: build succeeds; Trivy exits 0 (as of this plan, zero CRITICAL/HIGH findings have an available fix — this was verified directly during planning; if a fix has since become available for one of the currently-unfixed findings, this step may now correctly fail, meaning the base image or an apt package needs a bump before continuing — do not suppress it further, update the affected package instead).

- [ ] **Step 4: Dry-run the smoke test locally**

```bash
mkdir -p config data
echo '{"sources": []}' > config/sources.json
cat > .env <<'EOF'
SMTP_PASSWORD=ci-placeholder
SMTP_HOST=localhost
SMTP_PORT=587
SMTP_USER=ci
EMAIL_FROM=ci@example.test
EMAIL_TO=ci@example.test
RUN_HOUR=8
TZ=UTC
EOF
docker compose up -d
```

Wait a few seconds, then check each page:

```bash
curl -s -o /dev/null -w "dashboard: %{http_code}\n" http://localhost:8080/
curl -s -o /dev/null -w "sources: %{http_code}\n" http://localhost:8080/sources
curl -s -o /dev/null -w "history: %{http_code}\n" http://localhost:8080/history
curl -s -o /dev/null -w "settings: %{http_code}\n" http://localhost:8080/settings
```

Expected: all four print `200`.

- [ ] **Step 5: Tear down and clean up the local dry-run artifacts**

```bash
docker compose down
rm -rf config data .env
```

Expected: container removed; `git status --short` shows no new untracked files from this dry run (`config/`, `data/`, `.env` are all gitignored, but removing them keeps the worktree tidy).

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/docker.yml
git commit -m "ci: add Docker build, Trivy scan, and smoke test workflow"
```

---

### Task 7: `codeql.yml` — CodeQL SAST workflow

**Files:**
- Create: `.github/workflows/codeql.yml`

**Interfaces:**
- Consumes: nothing project-specific — CodeQL's Python analysis needs no build step for this project (interpreted language, no compile stage).
- Produces: a GitHub Actions workflow, job id `analyze`, that uploads SARIF results to the repo's Security tab on every PR/push and on a weekly schedule.

- [ ] **Step 1: Create `.github/workflows/codeql.yml`**

```yaml
name: CodeQL

on:
  pull_request:
  push:
    branches: [master]
  schedule:
    - cron: "0 6 * * 1"

jobs:
  analyze:
    name: Analyze Python
    runs-on: ubuntu-latest
    permissions:
      security-events: write
      contents: read

    steps:
      - name: Checkout
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1

      - name: Initialize CodeQL
        uses: github/codeql-action/init@5595ccaf912efad79be6eef63a5619ff05969be3 # v4.37.6
        with:
          languages: python

      - name: Perform CodeQL Analysis
        uses: github/codeql-action/analyze@5595ccaf912efad79be6eef63a5619ff05969be3 # v4.37.6
```

- [ ] **Step 2: Validate the workflow syntax with actionlint**

Run: `docker run --rm -v "$(pwd):/repo" -w /repo rhysd/actionlint:latest -color` (Windows/Git Bash: `MSYS_NO_PATHCONV=1 ... -w //repo`)
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/codeql.yml
git commit -m "ci: add CodeQL SAST workflow for Python"
```

---

### Task 8: `.github/dependabot.yml` — automated dependency updates

**Files:**
- Create: `.github/dependabot.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: weekly automated PRs bumping vulnerable/outdated `pip` dependencies and GitHub Actions versions, each of which will run through `ci.yml`/`docker.yml`/`codeql.yml` like any other PR.

- [ ] **Step 1: Create `.github/dependabot.yml`**

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

- [ ] **Step 2: Validate YAML syntax**

Run: `python -c "import yaml, sys; yaml.safe_load(open('.github/dependabot.yml'))"` (requires `pyyaml`; if not already installed, `pip install pyyaml` first — it's a one-off syntax check, not a new project dependency, so don't add it to `pyproject.toml`)
Expected: no output, exit code 0 (parses without error).

- [ ] **Step 3: Commit**

```bash
git add .github/dependabot.yml
git commit -m "ci: add Dependabot config for pip and GitHub Actions updates"
```

---

### Task 9: Push, open PR, prove the gates work, apply repo security settings

**Files:** none (no new files — this task is entirely GitHub/repo operations).

**Interfaces:**
- Consumes: all workflows from Tasks 5-7, the clean lint/typecheck baseline from Tasks 1-4.
- Produces: an open (or merged, per whatever the human partner decides via `finishing-a-development-branch`) PR with all checks green; secret scanning + push protection enabled; branch protection on `master` requiring `lint`, `typecheck`, `test`, `dependency-audit`, `build-scan-smoketest`, and `Analyze Python` to pass before merge.

**Note for whoever executes this task:** this is the one task in this plan that touches live GitHub state (pushes commits, opens a PR, temporarily breaks things on purpose, changes repo-wide settings). Recommend executing this one directly in the controlling session rather than dispatching it to a subagent, and confirming with the human partner before actually flipping the branch-protection/secret-scanning settings (as opposed to just observing the PR's checks) — those affect every future PR against this repo, not just this one.

- [ ] **Step 1: Push the branch and open a PR**

```bash
git push -u origin worktree-ci-security-pipeline
gh pr create --repo jasonkryst/CareerSpyder --base master \
  --title "Add CI/security pipeline" \
  --body "Closes #1. Adds lint/typecheck/test/dependency-audit CI, Docker build+Trivy scan+smoke test, CodeQL SAST, Dependabot, and fixes the mypy/ruff findings surfaced while wiring this up. See docs/superpowers/specs/2026-08-12-ci-security-pipeline-design.md for the full design."
```

Expected: PR opens successfully; note the PR number for later steps.

- [ ] **Step 2: Watch the checks run**

Run: `gh pr checks <PR-number> --watch`
Expected: all of `lint`, `typecheck`, `test`, `dependency-audit`, `build-scan-smoketest`, and `Analyze Python` eventually report success. If any fails unexpectedly (not as part of the deliberate-break steps below), investigate and fix before continuing — do not proceed to branch protection with a red check.

- [ ] **Step 3: Deliberately break `pytest` to prove the `ci.yml` gate actually blocks**

In `tests/test_filters.py`, change the assertion in `test_include_keyword_is_case_insensitive_substring_match` from:

```python
    assert [j.title for j in result] == ["Backend Engineer"]
```

to an obviously wrong expected value:

```python
    assert [j.title for j in result] == ["Sales Rep"]
```

Commit and push:

```bash
git commit -am "test: deliberately break a test to verify CI catches it"
git push
```

Run: `gh pr checks <PR-number> --watch`
Expected: `test` fails; `lint`, `typecheck`, `dependency-audit`, `build-scan-smoketest`, and `Analyze Python` still succeed (proving the jobs are genuinely independent).

- [ ] **Step 4: Revert the deliberate break**

```bash
git revert --no-edit HEAD
git push
```

Expected: `test` (and everything else) goes green again.

- [ ] **Step 5: Deliberately break the Docker build to prove the `docker.yml` gate blocks**

In `Dockerfile`, change:

```dockerfile
COPY app app
```

to:

```dockerfile
COPY nonexistent-directory app
```

Commit and push:

```bash
git commit -am "chore: deliberately break Dockerfile to verify Docker CI catches it"
git push
```

Run: `gh pr checks <PR-number> --watch`
Expected: `build-scan-smoketest` fails at the build step; the `ci.yml` jobs and `Analyze Python` are unaffected.

- [ ] **Step 6: Revert the deliberate break**

```bash
git revert --no-edit HEAD
git push
```

Expected: all checks green again.

- [ ] **Step 7: Confirm the exact status check names GitHub reports**

Run: `gh api repos/jasonkryst/CareerSpyder/commits/<latest-sha>/check-runs --jq '.check_runs[].name'`
Expected: a list including `lint`, `typecheck`, `test`, `dependency-audit`, `build-scan-smoketest`, and `Analyze Python` (or whatever CodeQL's actual reported check name is — confirm it here rather than assuming, since CodeQL's check name is derived from the workflow/job names and can differ slightly from the job id).

- [ ] **Step 8: Enable secret scanning and push protection**

Confirm with the human partner, then run:

```bash
gh api -X PATCH repos/jasonkryst/CareerSpyder \
  -f security_and_analysis[secret_scanning][status]=enabled \
  -f security_and_analysis[secret_scanning_push_protection][status]=enabled
```

Expected: 200 response; verify via `gh api repos/jasonkryst/CareerSpyder --jq '.security_and_analysis'`.

- [ ] **Step 9: Apply branch protection on `master`**

Confirm with the human partner, then run (substituting the exact check names confirmed in Step 7):

```bash
gh api -X PUT repos/jasonkryst/CareerSpyder/branches/master/protection \
  -f required_status_checks[strict]=true \
  -f 'required_status_checks[contexts][]=lint' \
  -f 'required_status_checks[contexts][]=typecheck' \
  -f 'required_status_checks[contexts][]=test' \
  -f 'required_status_checks[contexts][]=dependency-audit' \
  -f 'required_status_checks[contexts][]=build-scan-smoketest' \
  -f 'required_status_checks[contexts][]=Analyze Python' \
  -f enforce_admins=true \
  -f required_pull_request_reviews=null \
  -f restrictions=null
```

Expected: 200 response; verify via `gh api repos/jasonkryst/CareerSpyder/branches/master/protection --jq '.required_status_checks.contexts'`.

- [ ] **Step 10: Update the tracking issue**

```bash
gh issue comment 1 --repo jasonkryst/CareerSpyder --body "Implemented in PR #<PR-number>. All checks (lint, typecheck, test, dependency-audit, Docker build+Trivy scan+smoke test, CodeQL) verified passing and verified to actually fail on a deliberate break. Secret scanning + push protection enabled; branch protection on master now requires all checks before merge."
```

- [ ] **Step 11: Hand off to `finishing-a-development-branch`**

This plan's job ends here — whether the PR gets merged now, later, or reviewed further is the human partner's call via the standard `finishing-a-development-branch` flow, not an automatic action of this task.

---

## Self-Review Notes

- **Spec coverage:** every section of `docs/superpowers/specs/2026-08-12-ci-security-pipeline-design.md` maps to a task — `ci.yml` (Task 5), `docker.yml` (Task 6), `codeql.yml` (Task 7), `dependabot.yml` (Task 8), repo settings (Task 9), the mypy/ruff pre-fix work called out in the spec's "Baseline findings" section (Tasks 1-4), and the spec's testing/verification plan (deliberate-break-and-revert, Task 9 Steps 3-6).
- **Refinement discovered during planning, not in the original spec:** the spec described the Trivy gate as "CRITICAL,HIGH ... fails the build" without addressing unfixed-CVE noise. Verified empirically while writing this plan (`docker run aquasec/trivy:latest image --severity CRITICAL,HIGH careerspyder:latest` showed real CRITICAL/HIGH findings in OS packages with no available fix yet; re-running with `--ignore-unfixed` showed zero). Added `ignore-unfixed: "true"` to the Trivy config (Global Constraints and Task 6) so the gate is always acting on something actionable — without it, `docker.yml` would fail on this PR's very first run for CVEs nobody can currently fix.
- **Placeholder scan:** none remaining — every code block is the actual, verified content (all mypy/ruff fixes and both new workflow files were applied and tested directly in the worktree during planning, then reverted for Tasks 1-4/5-8 to apply properly via their own TDD steps).
- **Type consistency:** `ADAPTERS: dict[str, Callable[..., list[Job]]]` (Task 4) is referenced identically in `app/web/routes_sources.py`'s `run_in_threadpool(ADAPTERS[source.type], source)` call (also Task 4) and in `app/orchestrator.py`'s existing `adapter = ADAPTERS[source.type]` (unchanged by this plan, already compiles clean against the new annotation — verified during planning).
