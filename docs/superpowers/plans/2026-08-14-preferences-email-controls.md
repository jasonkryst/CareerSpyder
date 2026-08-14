# Preferences Email Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users control, from the Preferences tab, which days of the week CareerSpyder checks for jobs and emails a digest, whether a job is resent in later digests while still listed (vs. emailed once, ever), and add support for multiple digest recipients.

**Architecture:** Three new/changed `settings` columns (`email_days`, `resend_jobs`, and a repurposed multi-value `email_to`) drive a runtime gate inside the existing daily APScheduler cron job (`app/scheduler.py::run_and_notify`) — no APScheduler rescheduling. The Preferences page moves from a client-only theme radio group to a mixed page: Theme stays instant/client-side, while the three new controls are a standard server-rendered form. Recipient rows are managed with a small vanilla-JS file, matching this repo's existing `static/theme.js` pattern (no build step, no new dependency).

**Tech Stack:** FastAPI, Jinja2, SQLite (`sqlite3` stdlib), APScheduler, vanilla CSS/JS, pytest + `TestClient`.

## Global Constraints

- No new runtime dependencies (spec: `docs/superpowers/specs/2026-08-14-preferences-email-controls-design.md`).
- No migration framework — new `settings` columns are added via guarded `ALTER TABLE ... ADD COLUMN` at `init_db` time, safe to run against both fresh and pre-existing databases.
- Default `email_days` is all seven days and default `resend_jobs` is off, so every existing deployment keeps today's "runs every day, sends each job once" behavior with zero action required.
- The daily APScheduler cron trigger keeps firing every day at `run_hour`; day-of-week selection is enforced inside the job body (`run_and_notify`), not via APScheduler's `day_of_week` trigger param.
- When `settings` has never been configured (`db.get_settings` returns `None`), behavior must match today exactly: the scan still runs (so job history stays current), only the email is skipped, with the same log message and placement as before this change.
- Email address validation is blank-filtering only — no format validation — matching this codebase's existing precedent for free-text list fields (`include_keywords`/`exclude_keywords` in `app/web/source_form.py`).
- Run `pytest -q` after every task; it must pass with 0 failures before moving on.

---

### Task 1: Settings data model + Email tab adjustment

**Files:**
- Modify: `app/db.py`
- Modify: `app/web/routes_settings.py` (only the existing `POST /settings/email` handler)
- Modify: `app/web/templates/settings_email.html`
- Test: `tests/test_db.py`
- Test: `tests/web/test_settings.py` (only the existing Email-tab tests)

**Interfaces:**
- Produces (relied on by every later task):
  - `db.get_settings(conn) -> dict | None` — keys `smtp_host`, `smtp_port`, `smtp_user`, `email_from`, `email_to` (str), `email_days` (comma-separated day codes, e.g. `"mon,tue,wed,thu,fri,sat,sun"`), `resend_jobs` (bool).
  - `db.save_settings(conn, smtp_host: str, smtp_port: int, smtp_user: str, email_from: str) -> None` — SMTP transport fields only, no longer touches `email_to`.
  - `db.save_preferences(conn, email_days: str, resend_jobs: bool, email_to: str) -> None` — new.
  - `db.seed_settings_if_empty(conn, smtp_host, smtp_port, smtp_user, email_from, email_to) -> None` — signature unchanged.

- [ ] **Step 1: Write the failing tests**

Replace `test_save_settings_overwrites` and add new tests to `tests/test_db.py`:

```python
def test_save_settings_overwrites(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_settings(conn, "a.example.com", 587, "u1", "f@x.test")
    db.save_settings(conn, "b.example.com", 465, "u2", "f2@x.test")

    settings = db.get_settings(conn)
    assert settings["smtp_host"] == "b.example.com"
    assert settings["smtp_port"] == 465
    assert settings["smtp_user"] == "u2"
    assert settings["email_from"] == "f2@x.test"


def test_save_settings_does_not_touch_preference_columns(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_preferences(conn, "mon,wed,fri", True, "a@x.test,b@x.test")

    db.save_settings(conn, "a.example.com", 587, "u1", "f@x.test")

    settings = db.get_settings(conn)
    assert settings["email_days"] == "mon,wed,fri"
    assert settings["resend_jobs"] is True
    assert settings["email_to"] == "a@x.test,b@x.test"


def test_save_preferences_overwrites(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_preferences(conn, "mon,tue,wed,thu,fri,sat,sun", False, "a@x.test")
    db.save_preferences(conn, "mon,wed,fri", True, "a@x.test,b@x.test")

    settings = db.get_settings(conn)
    assert settings["email_days"] == "mon,wed,fri"
    assert settings["resend_jobs"] is True
    assert settings["email_to"] == "a@x.test,b@x.test"


def test_save_preferences_does_not_touch_smtp_columns(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.save_settings(conn, "a.example.com", 587, "u1", "f@x.test")

    db.save_preferences(conn, "mon", False, "a@x.test")

    settings = db.get_settings(conn)
    assert settings["smtp_host"] == "a.example.com"
    assert settings["smtp_port"] == 587
    assert settings["smtp_user"] == "u1"
    assert settings["email_from"] == "f@x.test"


def test_get_settings_defaults_days_and_resend_after_seeding(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    db.seed_settings_if_empty(conn, "smtp.example.com", 587, "user", "from@x.test", "to@x.test")

    settings = db.get_settings(conn)
    assert settings["email_days"] == "mon,tue,wed,thu,fri,sat,sun"
    assert settings["resend_jobs"] is False
    assert settings["email_to"] == "to@x.test"


def test_init_db_adds_new_columns_to_a_pre_existing_database(tmp_db_path):
    import sqlite3

    conn = sqlite3.connect(tmp_db_path)
    conn.execute(
        "CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK (id = 1), "
        "smtp_host TEXT, smtp_port INTEGER, smtp_user TEXT, email_from TEXT, email_to TEXT)"
    )
    conn.execute(
        "INSERT INTO settings (id, smtp_host, smtp_port, smtp_user, email_from, email_to) "
        "VALUES (1, 'old.example.com', 587, 'olduser', 'old@x.test', 'oldto@x.test')"
    )
    conn.commit()
    conn.close()

    conn = db.init_db(tmp_db_path)

    settings = db.get_settings(conn)
    assert settings["smtp_host"] == "old.example.com"
    assert settings["email_to"] == "oldto@x.test"
    assert settings["email_days"] == "mon,tue,wed,thu,fri,sat,sun"
    assert settings["resend_jobs"] is False


def test_init_db_is_idempotent_on_an_already_migrated_database(tmp_db_path):
    db.init_db(tmp_db_path)

    conn = db.init_db(tmp_db_path)  # must not raise on the second call

    assert db.get_settings(conn) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — `db.save_settings` still requires an `email_to` positional arg, `db.save_preferences` doesn't exist yet, and `email_days`/`resend_jobs` aren't in `get_settings`'s output.

- [ ] **Step 3: Update `app/db.py`**

Replace the `get_settings`/`save_settings`/`seed_settings_if_empty` block (current lines 116-144) with:

```python
def _add_column_if_missing(conn: sqlite3.Connection, ddl: str) -> None:
    try:
        conn.execute(f"ALTER TABLE settings ADD COLUMN {ddl}")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc):
            raise


def get_settings(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT smtp_host, smtp_port, smtp_user, email_from, email_to, email_days, resend_jobs "
        "FROM settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    return {
        "smtp_host": row[0], "smtp_port": row[1], "smtp_user": row[2],
        "email_from": row[3], "email_to": row[4],
        "email_days": row[5], "resend_jobs": bool(row[6]),
    }


def save_settings(conn: sqlite3.Connection, smtp_host: str, smtp_port: int, smtp_user: str,
                   email_from: str) -> None:
    conn.execute(
        "INSERT INTO settings (id, smtp_host, smtp_port, smtp_user, email_from) "
        "VALUES (1, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "smtp_host=excluded.smtp_host, smtp_port=excluded.smtp_port, smtp_user=excluded.smtp_user, "
        "email_from=excluded.email_from",
        (smtp_host, smtp_port, smtp_user, email_from),
    )
    conn.commit()


def save_preferences(conn: sqlite3.Connection, email_days: str, resend_jobs: bool, email_to: str) -> None:
    conn.execute(
        "INSERT INTO settings (id, email_days, resend_jobs, email_to) "
        "VALUES (1, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "email_days=excluded.email_days, resend_jobs=excluded.resend_jobs, email_to=excluded.email_to",
        (email_days, int(resend_jobs), email_to),
    )
    conn.commit()


def seed_settings_if_empty(conn: sqlite3.Connection, smtp_host: str, smtp_port: int, smtp_user: str,
                            email_from: str, email_to: str) -> None:
    if get_settings(conn) is None:
        conn.execute(
            "INSERT INTO settings (id, smtp_host, smtp_port, smtp_user, email_from, email_to) "
            "VALUES (1, ?, ?, ?, ?, ?)",
            (smtp_host, smtp_port, smtp_user, email_from, email_to),
        )
        conn.commit()
```

Then update `init_db` (current lines 43-47) to run the two guarded `ALTER TABLE` calls after creating the schema:

```python
def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA)
    _add_column_if_missing(conn, "email_days TEXT NOT NULL DEFAULT 'mon,tue,wed,thu,fri,sat,sun'")
    _add_column_if_missing(conn, "resend_jobs INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    return conn
```

`SCHEMA`'s `CREATE TABLE IF NOT EXISTS settings (...)` block itself is unchanged — the two new columns are always added via the guarded `ALTER TABLE` calls, whether the table is brand new or pre-existing, so there's only one code path to reason about.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS, all tests including the new ones.

- [ ] **Step 5: Update the Email tab to stop handling `email_to`**

In `app/web/routes_settings.py`, change the `save_settings` route handler (current lines 32-40):

```python
@router.post("/settings/email")
async def save_settings(request: Request):
    form = dict((await request.form()).items())
    db.save_settings(
        request.app.state.conn,
        _str_field(form, "smtp_host"), int(_str_field(form, "smtp_port")), _str_field(form, "smtp_user"),
        _str_field(form, "email_from"),
    )
    return RedirectResponse(url="/settings/email", status_code=303)
```

In `app/web/templates/settings_email.html`, delete the "To address" line:

```html
  <label>To address <input type="text" name="email_to" value="{{ settings.email_to }}"></label>
```

- [ ] **Step 6: Update the existing Email-tab tests**

In `tests/web/test_settings.py`:

Change `test_post_settings_saves_new_values`'s posted data (drop `email_to`):

```python
def test_post_settings_saves_new_values(client):
    resp = client.post("/settings/email", data={
        "smtp_host": "smtp2.example.com", "smtp_port": "465",
        "smtp_user": "user2", "email_from": "from2@x.test",
    }, follow_redirects=False)

    assert resp.status_code == 303

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["smtp_host"] == "smtp2.example.com"
    assert settings["smtp_port"] == 465
```

Change `test_post_settings_rejects_file_upload_field`'s posted data (drop `email_to`):

```python
def test_post_settings_rejects_file_upload_field(client):
    resp = client.post(
        "/settings/email",
        data={"smtp_port": "465", "smtp_user": "user2", "email_from": "from2@x.test"},
        files={"smtp_host": ("evil.txt", b"not a hostname")},
    )

    assert resp.status_code == 400
```

Add a new test confirming the field is gone from the page:

```python
def test_settings_email_page_has_no_recipient_field(client):
    resp = client.get("/settings/email")

    assert 'name="email_to"' not in resp.text
```

- [ ] **Step 7: Run the full test suite and commit**

Run: `pytest -q`
Expected: PASS, 0 failures.

```bash
git add app/db.py app/web/routes_settings.py app/web/templates/settings_email.html tests/test_db.py tests/web/test_settings.py
git commit -m "feat: split settings into SMTP config and preferences, add days/resend columns"
```

---

### Task 2: Multi-recipient email sending

**Files:**
- Modify: `app/emailer.py`
- Test: `tests/test_emailer.py`

**Interfaces:**
- Produces: `send_email(smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str, email_from: str, email_to: list[str], subject: str, html_body: str) -> None`.

- [ ] **Step 1: Write the failing tests**

Update the existing test and add a new one in `tests/test_emailer.py`:

```python
from unittest.mock import MagicMock, patch

from app.emailer import send_email


def test_send_email_logs_in_and_sends_via_starttls():
    with patch("app.emailer.smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        send_email(
            smtp_host="smtp.example.com", smtp_port=587, smtp_user="user",
            smtp_password="secret", email_from="from@x.test", email_to=["to@x.test"],
            subject="Subject", html_body="<p>Body</p>",
        )

        mock_smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=30)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user", "secret")
        assert mock_server.sendmail.call_count == 1
        args = mock_server.sendmail.call_args[0]
        assert args[0] == "from@x.test"
        assert args[1] == ["to@x.test"]
        assert "Subject" in args[2]


def test_send_email_with_multiple_recipients_joins_header_and_sends_to_all():
    with patch("app.emailer.smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        send_email(
            smtp_host="smtp.example.com", smtp_port=587, smtp_user="user",
            smtp_password="secret", email_from="from@x.test",
            email_to=["a@x.test", "b@x.test"],
            subject="Subject", html_body="<p>Body</p>",
        )

        args = mock_server.sendmail.call_args[0]
        assert args[1] == ["a@x.test", "b@x.test"]
        assert "To: a@x.test, b@x.test" in args[2]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_emailer.py -v`
Expected: FAIL — `send_email` still sets `msg["To"]` to the raw string arg and wraps it in `[email_to]` for `sendmail`, so passing a list breaks both.

- [ ] **Step 3: Update `app/emailer.py`**

```python
import smtplib
from email.mime.text import MIMEText


def send_email(smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str,
                email_from: str, email_to: list[str], subject: str, html_body: str) -> None:
    msg = MIMEText(html_body, "html")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = ", ".join(email_to)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(email_from, email_to, msg.as_string())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_emailer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/emailer.py tests/test_emailer.py
git commit -m "feat: support multiple recipients in send_email"
```

---

### Task 3: Orchestrator exposes all currently-found jobs

**Files:**
- Modify: `app/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Produces: `RunSummary(run_id: int, new_jobs: list[Job], found_jobs: list[Job], failed_sources: list[str])` — `found_jobs` is every job found this run after keyword filtering and cross-source dedup, *before* the "already in the `jobs` table" check; `new_jobs` keeps its existing meaning unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py`:

```python
def test_run_once_found_jobs_includes_already_known_jobs(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    source = GreenhouseSource(id="s1", name="Good Co", type="greenhouse", board_token="good")

    def fake_fetch(source):
        return [Job(key="gh:1", title="Backend Engineer", url="https://x.test/1", source_name=source.name)]

    with patch.dict(orchestrator.ADAPTERS, {"greenhouse": fake_fetch}):
        first = orchestrator.run_once(conn, [source])
        second = orchestrator.run_once(conn, [source])

    assert [j.key for j in first.found_jobs] == ["gh:1"]
    assert [j.key for j in second.found_jobs] == ["gh:1"]
    assert [j.key for j in second.new_jobs] == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_orchestrator.py::test_run_once_found_jobs_includes_already_known_jobs -v`
Expected: FAIL with `AttributeError: 'RunSummary' object has no attribute 'found_jobs'`.

- [ ] **Step 3: Update `app/orchestrator.py`**

Add `found_jobs` to the dataclass (current lines 20-24):

```python
@dataclass
class RunSummary:
    run_id: int
    new_jobs: list[Job]
    found_jobs: list[Job]
    failed_sources: list[str]
```

Update the return statement at the end of `run_once` (current line 48):

```python
        return RunSummary(
            run_id=run_id, new_jobs=new_jobs, found_jobs=deduped_jobs, failed_sources=failed_sources,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS, all tests including the new one.

- [ ] **Step 5: Commit**

```bash
git add app/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: expose all currently-found jobs on RunSummary for resend support"
```

---

### Task 4: Digest accepts a job-count label

**Files:**
- Modify: `app/digest.py`
- Test: `tests/test_digest.py`

**Interfaces:**
- Produces: `build_digest(new_jobs: list[Job], failed_sources: list[str], job_label: str = "new job") -> Digest | None` — subject reads `f"CareerSpyder: {len(new_jobs)} {job_label}(s)"`; default value keeps today's exact subject text unchanged for every existing caller/test.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_digest.py`:

```python
def test_job_label_can_be_overridden_for_resend_digests():
    jobs = [Job(key="1", title="Engineer", url="https://x.test/1", company="Acme", source_name="s")]

    result = build_digest(jobs, [], job_label="job")

    assert "1 job(s)" in result.subject
    assert "new job" not in result.subject
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_digest.py::test_job_label_can_be_overridden_for_resend_digests -v`
Expected: FAIL with `TypeError: build_digest() got an unexpected keyword argument 'job_label'`.

- [ ] **Step 3: Update `app/digest.py`**

Change the `build_digest` signature and subject line (current lines 26-30):

```python
def build_digest(new_jobs: list[Job], failed_sources: list[str], job_label: str = "new job") -> Digest | None:
    if not new_jobs and not failed_sources:
        return None

    subject = (
        f"CareerSpyder: {len(new_jobs)} {job_label}(s)" if new_jobs
        else "CareerSpyder: run had failed sources"
    )
```

The rest of the function is unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_digest.py -v`
Expected: PASS, all tests including `test_groups_new_jobs_by_company` (which asserts `"2 new job" in result.subject` — still true with the default `job_label`).

- [ ] **Step 5: Commit**

```bash
git add app/digest.py tests/test_digest.py
git commit -m "feat: let callers override the digest's job-count label"
```

---

### Task 5: Scheduler day-gating, resend selection, multi-recipient wiring

**Files:**
- Modify: `app/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `db.get_settings`/`db.save_settings`/`db.save_preferences` (Task 1), `emailer.send_email(..., email_to: list[str], ...)` (Task 2), `RunSummary.found_jobs` (Task 3), `digest.build_digest(..., job_label=...)` (Task 4).
- Produces: `run_and_notify(conn, sources_path: str, tz: str = "UTC") -> None`; `create_scheduler(conn, sources_path, run_hour, tz) -> BackgroundScheduler` (now passes `tz` through to the job's `args`).

- [ ] **Step 1: Write the failing tests**

Update every existing test in `tests/test_scheduler.py` that calls `db.save_settings(conn, ..., "to@x.test")` (the old 5-arg form) to instead call the new 4-arg `save_settings` plus `save_preferences`, update the `build_digest`/`send_email` call assertions for the new signatures, and add new tests for day-gating, resend, and multi-recipient behavior. Replace the whole file with:

```python
from unittest.mock import patch

from app import db, scheduler
from app.digest import Digest


def _configure(conn, email_days="mon,tue,wed,thu,fri,sat,sun", resend_jobs=False, email_to="to@x.test"):
    db.save_settings(conn, "smtp.example.com", 587, "user", "from@x.test")
    db.save_preferences(conn, email_days, resend_jobs, email_to)


def test_run_and_notify_sends_email_when_digest_present(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn)
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"], "run_id": 1})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary) as mock_run_once, \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")) as mock_digest, \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_run_once.assert_called_once()
    mock_digest.assert_called_once_with([], ["Bad Co"], "new job")
    mock_send.assert_called_once_with(
        "smtp.example.com", 587, "user", "secret", "from@x.test", ["to@x.test"], "Subj", "<p>Body</p>",
    )


def test_run_and_notify_skips_email_when_digest_is_none(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn)
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": []})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=None), \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_send.assert_not_called()


def test_run_and_notify_swallows_email_send_failures(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn)
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"], "run_id": 1})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email", side_effect=RuntimeError("smtp exploded")):
        scheduler.run_and_notify(conn, sources_path)  # must not raise


def test_run_and_notify_does_not_crash_when_smtp_password_unset(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    conn = db.init_db(tmp_db_path)
    _configure(conn)
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"], "run_id": 1})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_send.assert_called_once()
    assert mock_send.call_args[0][3] == ""


def test_run_and_notify_scans_and_skips_only_email_when_no_settings_configured(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    # No db.save_settings/save_preferences call, so db.get_settings(conn) returns None.
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": [], "failed_sources": ["Bad Co"], "run_id": 1})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary) as mock_run_once, \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)  # must not raise

    mock_run_once.assert_called_once()  # scan still happens, matching today's behavior
    mock_send.assert_not_called()


def test_run_and_notify_skips_entire_run_when_no_days_selected(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn, email_days="")
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    with patch("app.scheduler.orchestrator.run_once") as mock_run_once, \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_run_once.assert_not_called()
    mock_send.assert_not_called()


def test_run_and_notify_skips_email_when_no_recipients_configured(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn, email_to="")
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": ["job-a"], "failed_sources": [], "run_id": 1})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_send.assert_not_called()


def test_run_and_notify_splits_comma_separated_recipients(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn, email_to="a@x.test, b@x.test")
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {"new_jobs": ["job-a"], "failed_sources": [], "run_id": 1})()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")), \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    assert mock_send.call_args[0][5] == ["a@x.test", "b@x.test"]


def test_run_and_notify_uses_found_jobs_and_generic_label_when_resend_enabled(tmp_db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    conn = db.init_db(tmp_db_path)
    _configure(conn, resend_jobs=True)
    sources_path = str(tmp_path / "sources.json")
    (tmp_path / "sources.json").write_text('{"sources": []}')

    fake_summary = type("S", (), {
        "new_jobs": [], "found_jobs": ["job-a"], "failed_sources": [], "run_id": 1,
    })()

    with patch("app.scheduler.orchestrator.run_once", return_value=fake_summary), \
         patch("app.scheduler.digest.build_digest", return_value=Digest("Subj", "<p>Body</p>")) as mock_digest, \
         patch("app.scheduler.emailer.send_email") as mock_send:
        scheduler.run_and_notify(conn, sources_path)

    mock_digest.assert_called_once_with(["job-a"], [], "job")
    mock_send.assert_called_once()


def test_create_scheduler_registers_daily_cron_job(tmp_db_path, tmp_path):
    conn = db.init_db(tmp_db_path)
    sources_path = str(tmp_path / "sources.json")

    sched = scheduler.create_scheduler(conn, sources_path, run_hour=8, tz="UTC")
    try:
        jobs = sched.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == "daily_run"
        assert jobs[0].args == (conn, sources_path, "UTC")
    finally:
        sched.shutdown()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_scheduler.py -v`
Expected: FAIL — `db.save_settings` no longer accepts 5 positional args as called by the old file version, `build_digest`/`send_email` assertions don't match current call signatures, and the day/resend/recipient tests reference behavior that doesn't exist yet.

- [ ] **Step 3: Update `app/scheduler.py`**

```python
import logging
import os
from datetime import datetime
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from app import config, db, digest, emailer, orchestrator

logger = logging.getLogger(__name__)

_DAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _resolve_tz(tz: str):
    # "UTC" is special-cased the same way apscheduler.util.astimezone does,
    # so this never requires the optional `tzdata` package to be installed.
    return dt_timezone.utc if tz == "UTC" else ZoneInfo(tz)


def _today_code(tz: str) -> str:
    return _DAY_CODES[datetime.now(_resolve_tz(tz)).weekday()]


def run_and_notify(conn, sources_path: str, tz: str = "UTC") -> None:
    settings = db.get_settings(conn)
    if settings is not None and _today_code(tz) not in (settings["email_days"] or "").split(","):
        return

    sources = config.load_sources(sources_path)
    summary = orchestrator.run_once(conn, sources)

    resend = bool(settings and settings["resend_jobs"])
    jobs_to_send = summary.found_jobs if resend else summary.new_jobs
    job_label = "job" if resend else "new job"
    d = digest.build_digest(jobs_to_send, summary.failed_sources, job_label)
    if d is None:
        return

    if settings is None:
        logger.warning("Skipping digest email for run %s: no settings configured", summary.run_id)
        return

    email_to = [addr.strip() for addr in (settings["email_to"] or "").split(",") if addr.strip()]
    if not email_to:
        logger.warning("Skipping digest email for run %s: no recipients configured", summary.run_id)
        return

    try:
        emailer.send_email(
            settings["smtp_host"], settings["smtp_port"], settings["smtp_user"],
            os.environ.get("SMTP_PASSWORD", ""), settings["email_from"], email_to,
            d.subject, d.html_body,
        )
    except Exception:
        logger.exception("Failed to send digest email for run %s", summary.run_id)


def create_scheduler(conn, sources_path: str, run_hour: int, tz: str) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=tz)
    sched.add_job(run_and_notify, "cron", hour=run_hour, args=[conn, sources_path, tz], id="daily_run")
    sched.start()
    return sched
```

Note the ordering: the day-of-week check runs first (using `settings["email_days"]`) and returns before scanning — this is the new "skip the whole run" behavior. But it's guarded by `settings is not None`, so when `settings` is `None` (never configured), the function falls through to scan exactly as it did before this change; the `settings is None` skip-email branch further down is unchanged from the original code, just fetched earlier since day-gating also needs it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_scheduler.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Run the full test suite and commit**

Run: `pytest -q`
Expected: PASS, 0 failures.

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "feat: gate daily run by selected days and support resend digests"
```

---

### Task 6: Preferences page — routes, templates, and recipient-row JS

**Files:**
- Modify: `app/web/routes_settings.py` (add `GET`/`POST /settings/preferences`)
- Modify: `app/web/templates/settings_preferences.html`
- Create: `app/web/static/preferences.js`
- Modify: `app/web/templates/base.html`
- Test: `tests/web/test_settings.py`

**Interfaces:**
- Consumes: `db.get_settings`, `db.save_preferences` (Task 1).
- Produces: `POST /settings/preferences` route; `settings_preferences.html` renders checkboxes `name="email_days"` (values `mon`..`sun`), a `name="resend_jobs"` checkbox, and repeatable `name="email_to"` rows inside `#email-recipients`, with an `#email-recipient-template` `<template>` and `#add-recipient` button that `preferences.js` wires up.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_settings.py`:

```python
def test_settings_preferences_page_shows_all_day_checkboxes(client):
    resp = client.get("/settings/preferences")

    assert resp.status_code == 200
    for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        assert f'name="email_days" value="{day}"' in resp.text


def test_settings_preferences_page_prechecks_stored_days(client):
    from app import db
    db.save_preferences(client.app.state.conn, "mon,wed,fri", False, "to@x.test")

    resp = client.get("/settings/preferences")

    assert 'value="mon" checked' in resp.text
    assert 'value="wed" checked' in resp.text
    assert 'value="tue" checked' not in resp.text


def test_settings_preferences_page_shows_resend_checkbox(client):
    resp = client.get("/settings/preferences")

    assert 'name="resend_jobs"' in resp.text


def test_settings_preferences_page_shows_stored_recipients(client):
    from app import db
    db.save_preferences(client.app.state.conn, "mon,tue,wed,thu,fri,sat,sun", False, "a@x.test,b@x.test")

    resp = client.get("/settings/preferences")

    assert 'value="a@x.test"' in resp.text
    assert 'value="b@x.test"' in resp.text


def test_settings_preferences_page_shows_a_blank_recipient_row_when_none_stored(client):
    resp = client.get("/settings/preferences")

    assert 'placeholder="name@example.com"' in resp.text
    assert 'value="a@x.test"' not in resp.text


def test_settings_preferences_page_wraps_sections_in_cards(client):
    resp = client.get("/settings/preferences")

    assert resp.text.count('class="card"') == 4


def test_post_preferences_saves_days_resend_and_recipients(client):
    resp = client.post("/settings/preferences", data={
        "email_days": ["mon", "wed", "fri"],
        "resend_jobs": "on",
        "email_to": ["a@x.test", "b@x.test"],
    }, follow_redirects=False)

    assert resp.status_code == 303

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_days"] == "mon,wed,fri"
    assert settings["resend_jobs"] is True
    assert settings["email_to"] == "a@x.test,b@x.test"


def test_post_preferences_unchecked_resend_is_stored_as_false(client):
    client.post("/settings/preferences", data={"email_days": ["mon"], "email_to": ["a@x.test"]})

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["resend_jobs"] is False


def test_post_preferences_drops_blank_recipient_rows(client):
    client.post("/settings/preferences", data={"email_days": ["mon"], "email_to": ["a@x.test", "", "  "]})

    from app import db
    settings = db.get_settings(client.app.state.conn)
    assert settings["email_to"] == "a@x.test"


def test_post_preferences_rejects_file_upload_field(client):
    resp = client.post(
        "/settings/preferences",
        data={"email_days": ["mon"]},
        files={"email_to": ("evil.txt", b"not an email")},
    )

    assert resp.status_code == 400


def test_preferences_js_is_served(client):
    resp = client.get("/static/preferences.js")

    assert resp.status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/web/test_settings.py -v`
Expected: FAIL — `POST /settings/preferences` doesn't exist (405/404), the GET page has no checkboxes/recipient rows yet, and `/static/preferences.js` 404s.

- [ ] **Step 3: Add the routes to `app/web/routes_settings.py`**

Add near the top, alongside `_str_field`:

```python
DAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _str_list_field(form, key: str) -> list[str]:
    values = form.getlist(key)
    for value in values:
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail=f"{key} must be text fields")
    return values


def _split_emails(raw: str | None) -> list[str]:
    return [addr.strip() for addr in (raw or "").split(",") if addr.strip()]
```

Replace the existing `show_settings_preferences` route (current lines 48-50) and add the new `POST` handler:

```python
@router.get("/settings/preferences", response_class=HTMLResponse)
def show_settings_preferences(request: Request):
    settings = db.get_settings(request.app.state.conn)
    email_days_selected = set((settings["email_days"] if settings else "").split(","))
    email_to_list = _split_emails(settings["email_to"] if settings else "") or [""]
    return templates.TemplateResponse(
        request, "settings_preferences.html",
        {"settings": settings, "email_days_selected": email_days_selected, "email_to_list": email_to_list},
    )


@router.post("/settings/preferences")
async def save_preferences(request: Request):
    form = await request.form()
    selected_days = set(_str_list_field(form, "email_days")) & set(DAY_CODES)
    email_days = ",".join(day for day in DAY_CODES if day in selected_days)
    resend_jobs = "resend_jobs" in form
    email_to = ",".join(addr.strip() for addr in _str_list_field(form, "email_to") if addr.strip())
    db.save_preferences(request.app.state.conn, email_days, resend_jobs, email_to)
    return RedirectResponse(url="/settings/preferences", status_code=303)
```

- [ ] **Step 4: Replace `app/web/templates/settings_preferences.html`**

```html
{% extends "base.html" %}
{% block content %}
{% include "settings_tabs.html" %}
<h1>Preferences</h1>

<div class="card">
  <fieldset>
    <legend>Theme</legend>
    <label><input type="radio" name="theme" value="light"> Light</label>
    <label><input type="radio" name="theme" value="dark"> Dark</label>
    <label><input type="radio" name="theme" value="system"> Match system</label>
  </fieldset>
</div>

<form method="post" action="/settings/preferences">
<div class="card">
  <fieldset>
    <legend>Check days</legend>
    <label><input type="checkbox" name="email_days" value="mon" {% if "mon" in email_days_selected %}checked{% endif %}> Mon</label>
    <label><input type="checkbox" name="email_days" value="tue" {% if "tue" in email_days_selected %}checked{% endif %}> Tue</label>
    <label><input type="checkbox" name="email_days" value="wed" {% if "wed" in email_days_selected %}checked{% endif %}> Wed</label>
    <label><input type="checkbox" name="email_days" value="thu" {% if "thu" in email_days_selected %}checked{% endif %}> Thu</label>
    <label><input type="checkbox" name="email_days" value="fri" {% if "fri" in email_days_selected %}checked{% endif %}> Fri</label>
    <label><input type="checkbox" name="email_days" value="sat" {% if "sat" in email_days_selected %}checked{% endif %}> Sat</label>
    <label><input type="checkbox" name="email_days" value="sun" {% if "sun" in email_days_selected %}checked{% endif %}> Sun</label>
  </fieldset>
</div>

<div class="card">
  <fieldset>
    <legend>Resend</legend>
    <label><input type="checkbox" name="resend_jobs" {% if settings.resend_jobs %}checked{% endif %}> Keep sending a job in each digest until it's no longer listed</label>
  </fieldset>
</div>

<div class="card">
  <fieldset>
    <legend>Recipients</legend>
    <div id="email-recipients">
      {% for email in email_to_list %}
      <div class="recipient-row">
        <input type="email" name="email_to" value="{{ email }}" placeholder="name@example.com">
        <button type="button" class="remove-recipient">Remove</button>
      </div>
      {% endfor %}
    </div>
    <template id="email-recipient-template">
      <div class="recipient-row">
        <input type="email" name="email_to" placeholder="name@example.com">
        <button type="button" class="remove-recipient">Remove</button>
      </div>
    </template>
    <button type="button" id="add-recipient">Add another</button>
  </fieldset>
</div>

<button type="submit" class="btn-primary">Save</button>
</form>
{% endblock %}
```

- [ ] **Step 5: Create `app/web/static/preferences.js`**

```javascript
(function () {
  var list = document.getElementById("email-recipients");
  if (!list) return;

  var template = document.getElementById("email-recipient-template");
  var addButton = document.getElementById("add-recipient");

  function wireRemove(row) {
    row.querySelector(".remove-recipient").addEventListener("click", function () {
      if (list.querySelectorAll(".recipient-row").length > 1) {
        row.remove();
      } else {
        row.querySelector("input").value = "";
      }
    });
  }

  list.querySelectorAll(".recipient-row").forEach(wireRemove);

  addButton.addEventListener("click", function () {
    var row = template.content.firstElementChild.cloneNode(true);
    list.appendChild(row);
    wireRemove(row);
    row.querySelector("input").focus();
  });
})();
```

- [ ] **Step 6: Wire the script into `app/web/templates/base.html`**

Change (current line 16):

```html
  <script src="/static/theme.js" defer></script>
```

to:

```html
  <script src="/static/theme.js" defer></script>
  <script src="/static/preferences.js" defer></script>
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/web/test_settings.py -v`
Expected: PASS, all tests including the new ones. Also re-run the existing `test_settings_preferences_page_shows_theme_radios` and `test_settings_tabs_include_preferences_link` tests from before this plan — they must still pass unchanged.

- [ ] **Step 8: Run the full test suite and commit**

Run: `pytest -q`
Expected: PASS, 0 failures.

```bash
git add app/web/routes_settings.py app/web/templates/settings_preferences.html app/web/static/preferences.js app/web/templates/base.html tests/web/test_settings.py
git commit -m "feat: add check-days, resend, and multi-recipient controls to Preferences"
```

---

### Task 7: Manual verification, docs, and full-suite check

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:** None — documentation and verification only.

- [ ] **Step 1: Manually exercise the Preferences page in a browser**

Start the app locally (adjust env vars as needed for your shell):

```bash
CAREERSPYDER_DB_PATH=/tmp/careerspyder-manual.db CAREERSPYDER_SOURCES_PATH=/tmp/careerspyder-sources.json \
SMTP_HOST=smtp.example.com SMTP_PORT=587 SMTP_USER=user SMTP_PASSWORD=secret \
EMAIL_FROM=from@x.test EMAIL_TO=to@x.test RUN_HOUR=8 TZ=UTC \
uvicorn app.web.main:app --port 8080
```

Open `http://localhost:8080/settings/preferences` and confirm:
- Unchecking a day and clicking Save, then reloading the page, shows it still unchecked.
- Checking "Resend jobs" persists across a save + reload.
- Clicking "Add another" adds a new empty recipient row; typing an address and saving, then reloading, shows both addresses prefilled.
- Clicking "Remove" on a row removes it (except when it's the only row left, where it just clears the input instead).
- Theme radios still apply instantly without a page reload, unaffected by the new form.

Stop the server once satisfied (`Ctrl+C`); delete the two `/tmp` files created above.

- [ ] **Step 2: Update the Features bullet in `README.md`**

Change (current lines 42-48):

```markdown
- **Settings: Email, Data, and Preferences tabs** — `/settings/email` holds
  the SMTP config (unchanged); `/settings/data` adds a job-cache clear
  (clearing it makes the next run re-report every currently known job as
  new, which can trigger a large digest email) and sources.json
  import/export (import replaces the entire source list; export downloads
  the current one); `/settings/preferences` holds the Light/Dark/System
  theme choice, previously a header toggle.
```

to:

```markdown
- **Settings: Email, Data, and Preferences tabs** — `/settings/email` holds
  the SMTP transport config; `/settings/data` adds a job-cache clear
  (clearing it makes the next run re-report every currently known job as
  new, which can trigger a large digest email) and sources.json
  import/export (import replaces the entire source list; export downloads
  the current one); `/settings/preferences` holds the Light/Dark/System
  theme choice plus which days to check for jobs, whether a still-listed
  job is resent in every digest or only ever emailed once, and one or
  more digest recipient addresses.
```

- [ ] **Step 3: Update the dedup store and scheduler rows in the architecture table in `README.md`**

Change (current line 80):

```markdown
| Dedup store | `app/db.py` | SQLite: `jobs` (seen-before keys), `runs` (history), `settings` (SMTP host/port/from/to — **not** the password, see [Secrets](#secrets)). |
```

to:

```markdown
| Dedup store | `app/db.py` | SQLite: `jobs` (seen-before keys), `runs` (history), `settings` (SMTP host/port/from, recipient list, check days, resend flag — **not** the password, see [Secrets](#secrets)). |
```

Change (current line 83):

```markdown
| Scheduler | `app/scheduler.py` | APScheduler cron job, once daily at a configurable hour/timezone. Swallows and logs any email-send failure so a bad SMTP config can never crash the process or block future runs. |
```

to:

```markdown
| Scheduler | `app/scheduler.py` | APScheduler cron job, once daily at a configurable hour/timezone. Skips the scan and email entirely on days not selected in Preferences. Swallows and logs any email-send failure so a bad SMTP config can never crash the process or block future runs. |
```

- [ ] **Step 4: Update the Web UI table in `README.md`**

Change (current lines 229-231):

```markdown
| `/settings/email` | SMTP host/port/from/recipient address. The SMTP password is intentionally not present here (see [Secrets](#secrets)). |
| `/settings/data` | Clear the job dedup cache (the next run will re-report every currently known job as new and may send a large digest email), and export/import `sources.json` (import replaces the entire source list). |
| `/settings/preferences` | Light/Dark/System theme choice. Stored in `localStorage` only, same as the header toggle it replaces — no server-side preference storage. |
```

to:

```markdown
| `/settings/email` | SMTP host/port/from address. The SMTP password is intentionally not present here (see [Secrets](#secrets)). |
| `/settings/data` | Clear the job dedup cache (the next run will re-report every currently known job as new and may send a large digest email), and export/import `sources.json` (import replaces the entire source list). |
| `/settings/preferences` | Light/Dark/System theme choice (client-side, `localStorage` only). Also: which days of the week to check for jobs and send a digest, whether a still-listed job is resent every digest or emailed once ever, and one or more recipient addresses (server-stored). |
```

- [ ] **Step 5: Add a CHANGELOG entry**

Add a new `### Added` section under `## [Unreleased]` in `CHANGELOG.md` (current line 6):

```markdown
## [Unreleased]

### Added

- Preferences tab: choose which days of the week to check for jobs and
  send a digest, choose whether a still-listed job is resent in every
  digest or emailed once ever, and add multiple digest recipients. The
  "To address" field moved from the Email tab to Preferences as part of
  this; the Email tab now holds SMTP transport config only.
```

- [ ] **Step 6: Run the full test suite**

Run: `pytest -q`
Expected: PASS, 0 failures — this covers every task in this plan plus everything untouched (adapters, `config`, source form, etc.).

- [ ] **Step 7: Run lint and type checks**

Run: `ruff check app tests`
Expected: no errors.

Run: `mypy`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: document Preferences email frequency, resend, and multi-recipient controls"
```
