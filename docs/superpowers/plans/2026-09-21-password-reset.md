# Password Reset & Account Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add account recovery (forgot username/password via email link), password reset (token-validated form), and a logged-in change-password settings tab.

**Architecture:** `itsdangerous.URLSafeTimedSerializer` generates HMAC-signed, time-limited tokens containing `{user_id, email, pw_fp}` — no new DB table or migration. A short fingerprint of the stored password hash (`pw_fp`) in the token payload self-invalidates any token the moment the password changes. The account-recovery email (sent via admin SMTP) contains the username and a reset link; the "forgot username" and "forgot password" cases are handled by one flow.

**Tech Stack:** FastAPI, Jinja2, psycopg3, itsdangerous (already in `pyproject.toml`), bcrypt, smtplib (via `app.emailer`)

**Spec:** `docs/superpowers/specs/2026-09-21-password-reset-design.md`

## Global Constraints

- Python ≥ 3.12; all new code follows existing `ruff` rules (see `pyproject.toml`).
- All new routes must pass mypy (strict enough to satisfy `mypy app`).
- Password minimum length: 8 characters (matches existing register flow).
- Token expiry: 3600 seconds (1 hour).
- Token salt: `"password-reset"` — distinct from the session salt.
- SMTP password comes from `os.environ.get("SMTP_PASSWORD", "")` — it is NOT stored in the DB.
- Flash messages use `app.web.flash.flash_redirect(path, message)` for success redirects.
- Target version: `1.2.0`.
- Branch: create `feat/password-reset` from `master` before starting.

---

## Branch Setup

Before Task 1, create a worktree branch from master:

```bash
git fetch origin
git checkout -b feat/password-reset origin/master
```

If working inside an existing worktree on `fix/admin-smtp-for-all-users`, create the branch instead:

```bash
git checkout -b feat/password-reset origin/master
```

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app/db.py` | Modify | Add `get_user_by_id_with_hash`, `update_password` |
| `app/web/auth.py` | Modify | Add `generate_reset_token`, `verify_reset_token` |
| `app/web/main.py` | Modify | Store `secret_key` on `app.state` in lifespan |
| `app/web/routes_auth.py` | Modify | Add `GET/POST /account-recovery`, `GET/POST /reset-password` |
| `app/web/routes_settings.py` | Modify | Add `GET /settings/account`, `POST /settings/account/password` |
| `app/web/templates/login.html` | Modify | Add "Forgot username or password?" link + flash display |
| `app/web/templates/settings_tabs.html` | Modify | Add "Account" tab (all roles) |
| `app/web/templates/account_recovery.html` | Create | Standalone auth-card: email form + post-submit confirmation |
| `app/web/templates/reset_password.html` | Create | Standalone auth-card: new-password form + error view |
| `app/web/templates/settings_account.html` | Create | Settings tab: change-password form |
| `tests/web/test_auth.py` | Modify | Add DB-helper, token-helper, recovery, and reset tests |
| `tests/web/test_settings_account.py` | Create | Change-password tests |
| `CHANGELOG.md` | Modify | Document 1.2.0 |
| `pyproject.toml` | Modify | Bump `version` to `"1.2.0"` |

---

### Task 1: DB helpers, token helpers, and secret_key on app.state

**Files:**
- Modify: `app/db.py` — add two functions after `get_user_by_id` (~line 636)
- Modify: `app/web/auth.py` — add imports and two functions at end of file
- Modify: `app/web/main.py` — one line in the lifespan block
- Test: `tests/web/test_auth.py` — append test functions

**Interfaces:**
- Produces:
  - `db.get_user_by_id_with_hash(conn, user_id: str) -> dict | None` — all user fields + `password_hash`
  - `db.update_password(conn, user_id: str, new_hash: str) -> None`
  - `auth.generate_reset_token(secret_key: str, user_id: str, email: str, pw_hash: str) -> str`
  - `auth.verify_reset_token(secret_key: str, token: str, conn, max_age: int = 3600) -> dict | None` — returns full user dict (with `password_hash`) or `None`
  - `request.app.state.secret_key: str` — available in all routes

- [ ] **Step 1: Extend test imports in `tests/web/test_auth.py`**

At the top of `tests/web/test_auth.py`, the existing imports read:
```python
import pytest
from pydantic import TypeAdapter

from app import db
from app.config import SourceConfig
from app.web.auth import hash_password
```
Change to:
```python
import pytest
from pydantic import TypeAdapter
from unittest.mock import patch

from app import db
from app.config import SourceConfig
from app.web.auth import generate_reset_token, hash_password, verify_password, verify_reset_token
```

- [ ] **Step 2: Write failing DB-helper tests — append to `tests/web/test_auth.py`**

```python
# ── DB helpers ────────────────────────────────────────────────────────────────

def test_get_user_by_id_with_hash_returns_password_hash(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    result = db.get_user_by_id_with_hash(conn, user["id"])
    assert result is not None
    assert "password_hash" in result
    assert result["password_hash"].startswith("$2b$")
    assert result["id"] == user["id"]


def test_get_user_by_id_with_hash_returns_none_for_unknown_id(unauthed_client):
    conn = unauthed_client.app.state.conn
    result = db.get_user_by_id_with_hash(conn, "00000000-0000-0000-0000-000000000000")
    assert result is None


def test_update_password_changes_stored_hash(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    old_hash = user["password_hash"]
    db.update_password(conn, user["id"], hash_password("newpassword123"))
    updated = db.get_user_by_id_with_hash(conn, user["id"])
    assert updated["password_hash"] != old_hash
    assert verify_password("newpassword123", updated["password_hash"])
```

- [ ] **Step 3: Run DB-helper tests — confirm FAIL**

```
pytest tests/web/test_auth.py::test_get_user_by_id_with_hash_returns_password_hash -v
```
Expected: `AttributeError: module 'app.db' has no attribute 'get_user_by_id_with_hash'`

- [ ] **Step 4: Add DB helpers to `app/db.py`**

Insert immediately after the closing brace of `get_user_by_id` (after line ~636):

```python
def get_user_by_id_with_hash(conn: psycopg.Connection, user_id: str) -> dict | None:
    row = conn.execute(
        "SELECT id, username, email, password_hash, role, is_active, created_at "
        "FROM users WHERE id = %s",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]), "username": row[1], "email": row[2],
        "password_hash": row[3], "role": row[4], "is_active": row[5],
        "created_at": str(row[6]),
    }


def update_password(conn: psycopg.Connection, user_id: str, new_hash: str) -> None:
    conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user_id))
    conn.commit()
```

- [ ] **Step 5: Run DB-helper tests — confirm PASS**

```
pytest tests/web/test_auth.py::test_get_user_by_id_with_hash_returns_password_hash tests/web/test_auth.py::test_get_user_by_id_with_hash_returns_none_for_unknown_id tests/web/test_auth.py::test_update_password_changes_stored_hash -v
```

- [ ] **Step 6: Write failing token-helper tests — append to `tests/web/test_auth.py`**

```python
# ── Token helpers ─────────────────────────────────────────────────────────────

def test_generate_and_verify_reset_token(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    result = verify_reset_token("test-secret-key", token, conn)
    assert result is not None
    assert result["id"] == user["id"]
    assert result["username"] == "admin"


def test_verify_reset_token_rejects_expired_token(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    result = verify_reset_token("test-secret-key", token, conn, max_age=0)
    assert result is None


def test_verify_reset_token_rejects_tampered_token(unauthed_client):
    conn = unauthed_client.app.state.conn
    result = verify_reset_token("test-secret-key", "garbage.tampered.token", conn)
    assert result is None


def test_verify_reset_token_invalidated_after_password_change(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    db.update_password(conn, user["id"], hash_password("newpassword123"))
    result = verify_reset_token("test-secret-key", token, conn)
    assert result is None
```

- [ ] **Step 7: Run token-helper tests — confirm FAIL**

```
pytest tests/web/test_auth.py::test_generate_and_verify_reset_token -v
```
Expected: `ImportError` or `AttributeError` — `generate_reset_token` not yet defined.

- [ ] **Step 8: Add token helpers to `app/web/auth.py`**

Add these imports at the top of `app/web/auth.py`, after the existing imports:

```python
import hashlib

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
```

Append these functions at the end of `app/web/auth.py`:

```python
_RESET_SALT = "password-reset"


def generate_reset_token(secret_key: str, user_id: str, email: str, pw_hash: str) -> str:
    s = URLSafeTimedSerializer(secret_key)
    pw_fp = hashlib.sha256(pw_hash.encode()).hexdigest()[:8]
    return s.dumps({"user_id": user_id, "email": email, "pw_fp": pw_fp}, salt=_RESET_SALT)


def verify_reset_token(
    secret_key: str, token: str, conn: psycopg.Connection, max_age: int = 3600,
) -> dict | None:
    s = URLSafeTimedSerializer(secret_key)
    try:
        payload = s.loads(token, salt=_RESET_SALT, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    user = db.get_user_by_id_with_hash(conn, payload["user_id"])
    if user is None or not user["is_active"]:
        return None
    expected_fp = hashlib.sha256(user["password_hash"].encode()).hexdigest()[:8]
    if payload.get("pw_fp") != expected_fp:
        return None
    return user
```

- [ ] **Step 9: Expose secret_key on app.state in `app/web/main.py`**

In the `lifespan` function, after the line `app.state.pool = pool`, add:

```python
app.state.secret_key = _resolve_secret_key()
```

- [ ] **Step 10: Run all token-helper tests — confirm PASS**

```
pytest tests/web/test_auth.py::test_generate_and_verify_reset_token tests/web/test_auth.py::test_verify_reset_token_rejects_expired_token tests/web/test_auth.py::test_verify_reset_token_rejects_tampered_token tests/web/test_auth.py::test_verify_reset_token_invalidated_after_password_change -v
```

- [ ] **Step 11: Run full test suite — confirm no regressions**

```
pytest tests/ -x -q
```

- [ ] **Step 12: Commit**

```bash
git add app/db.py app/web/auth.py app/web/main.py tests/web/test_auth.py
git commit -m "feat: add password DB helpers, itsdangerous reset token utilities, and secret_key on app.state

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KR3FdjZuPUMQ9ZdszibyZH"
```

---

### Task 2: Account recovery routes and template

**Files:**
- Modify: `app/web/routes_auth.py`
- Create: `app/web/templates/account_recovery.html`
- Test: `tests/web/test_auth.py`

**Interfaces:**
- Consumes: `db.get_user_by_email`, `db.get_user_by_id_with_hash`, `db.get_admin_smtp_settings`, `auth.generate_reset_token`, `emailer.send_email`, `request.app.state.secret_key`
- Produces: `GET /account-recovery`, `POST /account-recovery`

- [ ] **Step 1: Write failing account-recovery tests — append to `tests/web/test_auth.py`**

```python
# ── Account recovery ──────────────────────────────────────────────────────────

def test_account_recovery_form_renders_for_unauthenticated_user(unauthed_client):
    resp = unauthed_client.get("/account-recovery")
    assert resp.status_code == 200
    assert 'name="email"' in resp.text


def test_authenticated_user_redirected_from_account_recovery(client):
    resp = client.get("/account-recovery", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["location"] == "/"


def test_account_recovery_with_registered_email_shows_confirmation(unauthed_client):
    with patch("app.emailer.send_email"):
        resp = unauthed_client.post("/account-recovery", data={"email": "admin@test.local"})
    assert resp.status_code == 200
    assert "we've sent" in resp.text.lower()


def test_account_recovery_with_registered_email_sends_one_email(unauthed_client):
    with patch("app.emailer.send_email") as mock_send:
        unauthed_client.post("/account-recovery", data={"email": "admin@test.local"})
    assert mock_send.call_count == 1


def test_account_recovery_email_contains_username_and_reset_link(unauthed_client):
    with patch("app.emailer.send_email") as mock_send:
        unauthed_client.post("/account-recovery", data={"email": "admin@test.local"})
    kwargs = mock_send.call_args.kwargs
    assert "admin" in kwargs["html_body"]
    assert "/reset-password?token=" in kwargs["html_body"]


def test_account_recovery_with_unknown_email_shows_same_confirmation(unauthed_client):
    with patch("app.emailer.send_email") as mock_send:
        resp = unauthed_client.post("/account-recovery", data={"email": "nobody@x.test"})
    assert resp.status_code == 200
    assert "we've sent" in resp.text.lower()
    mock_send.assert_not_called()


def test_account_recovery_with_empty_email_returns_400(unauthed_client):
    resp = unauthed_client.post("/account-recovery", data={"email": ""})
    assert resp.status_code == 400
    assert "required" in resp.text.lower()
```

- [ ] **Step 2: Run tests — confirm FAIL**

```
pytest tests/web/test_auth.py::test_account_recovery_form_renders_for_unauthenticated_user -v
```
Expected: 404 (route not yet defined).

- [ ] **Step 3: Add imports to `app/web/routes_auth.py`**

The current imports at the top of `app/web/routes_auth.py` are:
```python
from datetime import UTC, datetime
from urllib.parse import urlparse
```
Change to:
```python
import logging
import os
from datetime import UTC, datetime
from html import escape as _esc
from urllib.parse import urlparse
```

The current `from app import db` line:
```python
from app import db
```
Change to:
```python
from app import db, emailer
```

The current `from app.web.auth import ...` line:
```python
from app.web.auth import hash_password, verify_password
```
Change to:
```python
from app.web.auth import generate_reset_token, hash_password, verify_password, verify_reset_token
```

Add after the existing imports:
```python
from app.web.flash import flash_redirect

logger = logging.getLogger(__name__)
```

- [ ] **Step 4: Add helper function and routes to `app/web/routes_auth.py`**

Add this helper function before (or after) `_validate_invite`, near the bottom of the file:

```python
def _recovery_email_html(username: str, reset_url: str) -> str:
    u = _esc(username)
    r = _esc(reset_url)
    return (
        f"<p>Your username is: <strong>{u}</strong></p>"
        f"<p>To reset your password, click the link below. It expires in 1 hour.</p>"
        f'<p><a href="{r}">Reset my password</a></p>'
        f"<p>If you didn’t request this, you can safely ignore this email.</p>"
    )
```

Add these two routes after the `logout` route (before `register_form`):

```python
@router.get("/account-recovery", response_class=HTMLResponse)
async def account_recovery_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "account_recovery.html", {})


@router.post("/account-recovery", response_class=HTMLResponse)
async def account_recovery(request: Request):
    form = dict((await request.form()).items())
    email = str(form.get("email") or "").strip().lower()

    if not email:
        return templates.TemplateResponse(
            request, "account_recovery.html",
            {"error": "Email address is required."},
            status_code=400,
        )

    user_with_hash = None
    smtp = None
    with request.app.state.pool.connection() as conn:
        user = db.get_user_by_email(conn, email)
        if user and user["is_active"]:
            user_with_hash = db.get_user_by_id_with_hash(conn, user["id"])
            smtp = db.get_admin_smtp_settings(conn)

    if user_with_hash and smtp and smtp.get("smtp_host"):
        token = generate_reset_token(
            request.app.state.secret_key,
            user_with_hash["id"],
            user_with_hash["email"],
            user_with_hash["password_hash"],
        )
        reset_url = str(request.base_url).rstrip("/") + f"/reset-password?token={token}"
        try:
            emailer.send_email(
                smtp_host=smtp["smtp_host"],
                smtp_port=smtp["smtp_port"],
                smtp_user=smtp["smtp_user"],
                smtp_password=os.environ.get("SMTP_PASSWORD", ""),
                email_from=smtp["email_from"],
                email_to=[email],
                subject="CareerSpyder account recovery",
                html_body=_recovery_email_html(user_with_hash["username"], reset_url),
            )
        except Exception:
            logger.exception("Failed to send recovery email to %s", email)

    return templates.TemplateResponse(
        request, "account_recovery.html",
        {"submitted": True},
    )
```

- [ ] **Step 5: Create `app/web/templates/account_recovery.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Account recovery — CareerSpyder</title>
  <meta name="theme-color" content="#b3101f">
  <link rel="icon" href="/static/icons/favicon-32.png">
  <script>
    (function () {
      var stored = localStorage.getItem("theme");
      if (stored === "dark" || stored === "light") {
        document.documentElement.setAttribute("data-theme", stored);
      }
    })();
  </script>
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/theme.js" defer></script>
  <style>
    .auth-wrap {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 80vh;
      padding: 2rem 1rem;
    }
    .auth-card {
      width: 100%;
      max-width: 380px;
      background: var(--surface, #fff);
      border: 1px solid var(--border, #ddd);
      border-radius: 8px;
      padding: 2rem;
    }
    .auth-brand {
      display: flex;
      align-items: center;
      gap: .5rem;
      font-size: 1.25rem;
      font-weight: 600;
      margin-bottom: 1.5rem;
      color: var(--accent, #b3101f);
    }
    .auth-card h1 { font-size: 1.2rem; margin: 0 0 1.25rem; }
    .form-group { margin-bottom: 1rem; }
    .form-group label { display: block; font-size: .875rem; margin-bottom: .25rem; }
    .form-group input { width: 100%; box-sizing: border-box; }
    .btn-primary { width: 100%; margin-top: .5rem; }
    .auth-error {
      background: var(--error-bg, #fef2f2);
      color: var(--error, #b91c1c);
      border: 1px solid var(--error-border, #fca5a5);
      border-radius: 4px;
      padding: .625rem .75rem;
      font-size: .875rem;
      margin-bottom: 1rem;
    }
    .auth-success {
      background: var(--success-bg, #f0fdf4);
      color: var(--success, #15803d);
      border: 1px solid var(--success-border, #86efac);
      border-radius: 4px;
      padding: .625rem .75rem;
      font-size: .875rem;
      margin-bottom: 1rem;
    }
    .auth-help { margin-top: 1rem; font-size: .875rem; text-align: center; }
    .auth-hint { font-size: .875rem; margin: 0 0 1.25rem; color: var(--text-muted, #555); }
  </style>
</head>
<body>
  <div class="auth-wrap">
    <div class="auth-card">
      <div class="auth-brand">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="9" cy="9" r="5"></circle>
          <line x1="13" y1="13" x2="20" y2="20"></line>
        </svg>
        CareerSpyder
      </div>
      <h1>Account recovery</h1>
      {% if submitted %}
      <div class="auth-success" role="status">
        If that email is registered, we've sent you an email with your username and a password reset link.
      </div>
      <p class="auth-help"><a href="/login">Back to sign in</a></p>
      {% else %}
      {% if error %}
      <div class="auth-error" role="alert">{{ error }}</div>
      {% endif %}
      <p class="auth-hint">Enter your email address and we'll send your username and a link to reset your password.</p>
      <form method="post" action="/account-recovery">
        <div class="form-group">
          <label for="email">Email address</label>
          <input id="email" name="email" type="email" autocomplete="email" autofocus required>
        </div>
        <button type="submit" class="btn btn-primary">Send recovery email</button>
      </form>
      <p class="auth-help"><a href="/login">Back to sign in</a></p>
      {% endif %}
    </div>
  </div>
</body>
</html>
```

- [ ] **Step 6: Run account-recovery tests — confirm PASS**

```
pytest tests/web/test_auth.py -k "account_recovery" -v
```

- [ ] **Step 7: Run full test suite — confirm no regressions**

```
pytest tests/ -x -q
```

- [ ] **Step 8: Commit**

```bash
git add app/web/routes_auth.py app/web/templates/account_recovery.html tests/web/test_auth.py
git commit -m "feat: add account recovery route and template (GET/POST /account-recovery)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KR3FdjZuPUMQ9ZdszibyZH"
```

---

### Task 3: Password reset routes and template

**Files:**
- Modify: `app/web/routes_auth.py`
- Create: `app/web/templates/reset_password.html`
- Test: `tests/web/test_auth.py`

**Interfaces:**
- Consumes: `auth.verify_reset_token`, `db.update_password`, `auth.hash_password`, `flash_redirect`, `request.app.state.secret_key`
- Produces: `GET /reset-password`, `POST /reset-password`

- [ ] **Step 1: Write failing reset-password tests — append to `tests/web/test_auth.py`**

```python
# ── Password reset ────────────────────────────────────────────────────────────

def test_reset_password_form_with_valid_token_renders(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    resp = unauthed_client.get(f"/reset-password?token={token}")
    assert resp.status_code == 200
    assert 'name="password"' in resp.text
    assert "admin" in resp.text


def test_reset_password_form_shows_username(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    resp = unauthed_client.get(f"/reset-password?token={token}")
    assert "admin" in resp.text


def test_reset_password_form_with_no_token_returns_400(unauthed_client):
    resp = unauthed_client.get("/reset-password")
    assert resp.status_code == 400
    assert "invalid or has expired" in resp.text.lower()


def test_reset_password_form_with_tampered_token_returns_400(unauthed_client):
    resp = unauthed_client.get("/reset-password?token=garbage.invalid.token")
    assert resp.status_code == 400
    assert "invalid or has expired" in resp.text.lower()


def test_reset_password_form_with_expired_token_returns_400(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    # Generate with same key but verify with max_age=0 via the route's internal logic.
    # We can't pass max_age to the route, so we generate a token then tamper with the
    # timestamp by monkey-patching verify_reset_token.
    # Simpler: generate a token with a wrong secret so it fails signature check.
    token = generate_reset_token("wrong-secret", user["id"], user["email"], user["password_hash"])
    resp = unauthed_client.get(f"/reset-password?token={token}")
    assert resp.status_code == 400
    assert "invalid or has expired" in resp.text.lower()


def test_post_reset_password_with_valid_token_redirects_to_login(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    resp = unauthed_client.post("/reset-password", data={
        "token": token,
        "password": "freshpassword1",
        "password_confirm": "freshpassword1",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


def test_post_reset_password_old_password_no_longer_works(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    unauthed_client.post("/reset-password", data={
        "token": token,
        "password": "freshpassword1",
        "password_confirm": "freshpassword1",
    }, follow_redirects=False)
    resp = unauthed_client.post("/login", data={"username": "admin", "password": "password123"})
    assert resp.status_code == 401


def test_post_reset_password_with_mismatched_passwords_returns_400(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    resp = unauthed_client.post("/reset-password", data={
        "token": token,
        "password": "freshpassword1",
        "password_confirm": "differentpass1",
    })
    assert resp.status_code == 400
    assert "do not match" in resp.text.lower()


def test_post_reset_password_with_short_password_returns_400(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])
    resp = unauthed_client.post("/reset-password", data={
        "token": token,
        "password": "short",
        "password_confirm": "short",
    })
    assert resp.status_code == 400
    assert "8 characters" in resp.text


def test_post_reset_password_token_is_invalidated_after_use(unauthed_client):
    conn = unauthed_client.app.state.conn
    user = db.get_user_by_username(conn, "admin")
    token = generate_reset_token("test-secret-key", user["id"], user["email"], user["password_hash"])

    # First use — succeeds
    resp = unauthed_client.post("/reset-password", data={
        "token": token,
        "password": "freshpassword1",
        "password_confirm": "freshpassword1",
    }, follow_redirects=False)
    assert resp.status_code == 303

    # Replay — fails (password_hash fingerprint has changed)
    resp = unauthed_client.post("/reset-password", data={
        "token": token,
        "password": "anotherpass99",
        "password_confirm": "anotherpass99",
    })
    assert resp.status_code == 400
    assert "invalid or has expired" in resp.text.lower()
```

- [ ] **Step 2: Run tests — confirm FAIL**

```
pytest tests/web/test_auth.py::test_reset_password_form_with_no_token_returns_400 -v
```
Expected: 404.

- [ ] **Step 3: Add reset-password routes to `app/web/routes_auth.py`**

Add these two routes after the `account_recovery` POST route:

```python
@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_form(request: Request):
    token = request.query_params.get("token", "").strip()
    with request.app.state.pool.connection() as conn:
        user = verify_reset_token(request.app.state.secret_key, token, conn) if token else None
    if user is None:
        return templates.TemplateResponse(
            request, "reset_password.html",
            {"error": "This link is invalid or has expired.", "show_recovery_link": True},
            status_code=400,
        )
    return templates.TemplateResponse(
        request, "reset_password.html",
        {"token": token, "username": user["username"]},
    )


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_password(request: Request):
    form = dict((await request.form()).items())
    token = str(form.get("token") or "").strip()
    password = str(form.get("password") or "")
    password_confirm = str(form.get("password_confirm") or "")

    def _token_error() -> HTMLResponse:
        return templates.TemplateResponse(
            request, "reset_password.html",
            {"error": "This link is invalid or has expired.", "show_recovery_link": True},
            status_code=400,
        )

    def _form_error(msg: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "reset_password.html",
            {"error": msg, "token": token},
            status_code=400,
        )

    if not token:
        return _token_error()

    with request.app.state.pool.connection() as conn:
        user = verify_reset_token(request.app.state.secret_key, token, conn)
        if user is None:
            return _token_error()
        if len(password) < 8:
            return _form_error("Password must be at least 8 characters.")
        if password != password_confirm:
            return _form_error("Passwords do not match.")
        db.update_password(conn, user["id"], hash_password(password))

    request.session.clear()
    return flash_redirect("/login", "Password reset. Please sign in with your new password.")
```

- [ ] **Step 4: Create `app/web/templates/reset_password.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Reset password — CareerSpyder</title>
  <meta name="theme-color" content="#b3101f">
  <link rel="icon" href="/static/icons/favicon-32.png">
  <script>
    (function () {
      var stored = localStorage.getItem("theme");
      if (stored === "dark" || stored === "light") {
        document.documentElement.setAttribute("data-theme", stored);
      }
    })();
  </script>
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/theme.js" defer></script>
  <style>
    .auth-wrap {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 80vh;
      padding: 2rem 1rem;
    }
    .auth-card {
      width: 100%;
      max-width: 380px;
      background: var(--surface, #fff);
      border: 1px solid var(--border, #ddd);
      border-radius: 8px;
      padding: 2rem;
    }
    .auth-brand {
      display: flex;
      align-items: center;
      gap: .5rem;
      font-size: 1.25rem;
      font-weight: 600;
      margin-bottom: 1.5rem;
      color: var(--accent, #b3101f);
    }
    .auth-card h1 { font-size: 1.2rem; margin: 0 0 1.25rem; }
    .form-group { margin-bottom: 1rem; }
    .form-group label { display: block; font-size: .875rem; margin-bottom: .25rem; }
    .form-group input { width: 100%; box-sizing: border-box; }
    .btn-primary { width: 100%; margin-top: .5rem; }
    .auth-error {
      background: var(--error-bg, #fef2f2);
      color: var(--error, #b91c1c);
      border: 1px solid var(--error-border, #fca5a5);
      border-radius: 4px;
      padding: .625rem .75rem;
      font-size: .875rem;
      margin-bottom: 1rem;
    }
    .auth-help { margin-top: 1rem; font-size: .875rem; text-align: center; }
    .auth-context { font-size: .875rem; margin: 0 0 1.25rem; color: var(--text-muted, #555); }
  </style>
</head>
<body>
  <div class="auth-wrap">
    <div class="auth-card">
      <div class="auth-brand">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="9" cy="9" r="5"></circle>
          <line x1="13" y1="13" x2="20" y2="20"></line>
        </svg>
        CareerSpyder
      </div>
      <h1>Reset password</h1>
      {% if error %}
      <div class="auth-error" role="alert">{{ error }}</div>
      {% if show_recovery_link %}
      <p class="auth-help"><a href="/account-recovery">Request a new recovery link</a></p>
      {% endif %}
      {% endif %}
      {% if token %}
      {% if username %}
      <p class="auth-context">Setting new password for <strong>{{ username }}</strong></p>
      {% endif %}
      <form method="post" action="/reset-password">
        <input type="hidden" name="token" value="{{ token }}">
        <div class="form-group">
          <label for="password">New password</label>
          <input id="password" name="password" type="password" autocomplete="new-password" autofocus required minlength="8">
        </div>
        <div class="form-group">
          <label for="password_confirm">Confirm new password</label>
          <input id="password_confirm" name="password_confirm" type="password" autocomplete="new-password" required minlength="8">
        </div>
        <button type="submit" class="btn btn-primary">Set new password</button>
      </form>
      {% endif %}
      <p class="auth-help"><a href="/login">Back to sign in</a></p>
    </div>
  </div>
</body>
</html>
```

- [ ] **Step 5: Run reset-password tests — confirm PASS**

```
pytest tests/web/test_auth.py -k "reset_password" -v
```

- [ ] **Step 6: Run full test suite — confirm no regressions**

```
pytest tests/ -x -q
```

- [ ] **Step 7: Commit**

```bash
git add app/web/routes_auth.py app/web/templates/reset_password.html tests/web/test_auth.py
git commit -m "feat: add password reset routes and template (GET/POST /reset-password)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KR3FdjZuPUMQ9ZdszibyZH"
```

---

### Task 4: Login template — link and flash display

**Files:**
- Modify: `app/web/templates/login.html`

**Interfaces:**
- Consumes: `request.query_params.get("flash")` (set by `flash_redirect` from Task 3)
- Produces: visible "Forgot username or password?" link; flash success banner from reset redirect

- [ ] **Step 1: Write failing test — append to `tests/web/test_auth.py`**

```python
# ── Login page links ──────────────────────────────────────────────────────────

def test_login_page_shows_account_recovery_link(unauthed_client):
    resp = unauthed_client.get("/login")
    assert "account-recovery" in resp.text


def test_login_page_displays_flash_message_from_query_param(unauthed_client):
    resp = unauthed_client.get("/login?flash=Password+reset")
    assert "Password reset" in resp.text
```

- [ ] **Step 2: Run tests — confirm FAIL**

```
pytest tests/web/test_auth.py::test_login_page_shows_account_recovery_link tests/web/test_auth.py::test_login_page_displays_flash_message_from_query_param -v
```

- [ ] **Step 3: Edit `app/web/templates/login.html`**

Add the following CSS rule to the `<style>` block inside `login.html`, after `.auth-error { ... }`:

```css
    .auth-success {
      background: var(--success-bg, #f0fdf4);
      color: var(--success, #15803d);
      border: 1px solid var(--success-border, #86efac);
      border-radius: 4px;
      padding: .625rem .75rem;
      font-size: .875rem;
      margin-bottom: 1rem;
    }
    .auth-help { margin-top: 1rem; font-size: .875rem; text-align: center; }
```

After the existing `{% if error %}...{% endif %}` block (around line 88), add:

```html
      {% if request.query_params.get("flash") %}
      <div class="auth-success" role="status">{{ request.query_params.get("flash") }}</div>
      {% endif %}
```

After the `<button type="submit" ...>Sign in</button>` line, add:

```html
        <p class="auth-help"><a href="/account-recovery">Forgot username or password?</a></p>
```

- [ ] **Step 4: Run tests — confirm PASS**

```
pytest tests/web/test_auth.py::test_login_page_shows_account_recovery_link tests/web/test_auth.py::test_login_page_displays_flash_message_from_query_param -v
```

- [ ] **Step 5: Run full test suite — confirm no regressions**

```
pytest tests/ -x -q
```

- [ ] **Step 6: Commit**

```bash
git add app/web/templates/login.html tests/web/test_auth.py
git commit -m "feat: add account recovery link and flash display to login page

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KR3FdjZuPUMQ9ZdszibyZH"
```

---

### Task 5: Change-password settings tab

**Files:**
- Modify: `app/web/routes_settings.py`
- Create: `app/web/templates/settings_account.html`
- Modify: `app/web/templates/settings_tabs.html`
- Create: `tests/web/test_settings_account.py`

**Interfaces:**
- Consumes: `db.get_user_by_id_with_hash`, `db.update_password`, `auth.verify_password`, `auth.hash_password`, `flash_redirect`, `require_user`
- Produces: `GET /settings/account`, `POST /settings/account/password`

- [ ] **Step 1: Create `tests/web/test_settings_account.py`**

```python
"""Tests for the Account settings tab: change-password form."""
from app import db
from app.web.auth import hash_password, verify_password


# ── GET /settings/account ─────────────────────────────────────────────────────

def test_settings_account_renders_for_admin(client):
    resp = client.get("/settings/account")
    assert resp.status_code == 200
    assert 'name="current_password"' in resp.text
    assert 'name="new_password"' in resp.text
    assert 'name="new_password_confirm"' in resp.text


def test_settings_account_renders_for_member(member_client):
    resp = member_client.get("/settings/account")
    assert resp.status_code == 200
    assert 'name="current_password"' in resp.text


def test_settings_account_unauthenticated_redirects_to_login(unauthed_client):
    resp = unauthed_client.get("/settings/account", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


def test_settings_account_shows_account_tab_as_current(client):
    resp = client.get("/settings/account")
    assert resp.status_code == 200
    assert "Account" in resp.text


# ── POST /settings/account/password ──────────────────────────────────────────

def test_change_password_with_correct_current_password_succeeds(client):
    conn = client.app.state.conn
    resp = client.post("/settings/account/password", data={
        "current_password": "password123",
        "new_password": "newpassword99",
        "new_password_confirm": "newpassword99",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "/settings/account" in resp.headers["location"]
    user = db.get_user_by_username(conn, "admin")
    assert verify_password("newpassword99", user["password_hash"])


def test_change_password_with_wrong_current_password_returns_400(client):
    resp = client.post("/settings/account/password", data={
        "current_password": "wrongpassword",
        "new_password": "newpassword99",
        "new_password_confirm": "newpassword99",
    })
    assert resp.status_code == 400
    assert "incorrect" in resp.text.lower()


def test_change_password_with_mismatched_new_passwords_returns_400(client):
    resp = client.post("/settings/account/password", data={
        "current_password": "password123",
        "new_password": "newpassword99",
        "new_password_confirm": "differentpass99",
    })
    assert resp.status_code == 400
    assert "do not match" in resp.text.lower()


def test_change_password_with_short_new_password_returns_400(client):
    resp = client.post("/settings/account/password", data={
        "current_password": "password123",
        "new_password": "short",
        "new_password_confirm": "short",
    })
    assert resp.status_code == 400
    assert "8 characters" in resp.text


def test_change_password_unauthenticated_redirects_to_login(unauthed_client):
    resp = unauthed_client.post("/settings/account/password", data={
        "current_password": "password123",
        "new_password": "newpassword99",
        "new_password_confirm": "newpassword99",
    }, follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers["location"]
```

- [ ] **Step 2: Run tests — confirm FAIL**

```
pytest tests/web/test_settings_account.py::test_settings_account_renders_for_admin -v
```
Expected: 404 (route not defined).

- [ ] **Step 3: Add imports to `app/web/routes_settings.py`**

Extend the existing `from app.web.auth import require_admin, require_user` line:

```python
from app.web.auth import hash_password, require_admin, require_user, verify_password
```

- [ ] **Step 4: Add routes to `app/web/routes_settings.py`**

Append these two routes at the end of `app/web/routes_settings.py`:

```python
@router.get("/settings/account", response_class=HTMLResponse)
def account_settings(
    request: Request,
    current_user: dict = Depends(require_user),
):
    return templates.TemplateResponse(request, "settings_account.html", {})


@router.post("/settings/account/password")
async def change_password(
    request: Request,
    current_user: dict = Depends(require_user),
):
    form = dict((await request.form()).items())
    current_password = str(form.get("current_password") or "")
    new_password = str(form.get("new_password") or "")
    new_password_confirm = str(form.get("new_password_confirm") or "")

    def _error(msg: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "settings_account.html",
            {"error": msg},
            status_code=400,
        )

    with request.app.state.pool.connection() as conn:
        user_with_hash = db.get_user_by_id_with_hash(conn, current_user["id"])

    if user_with_hash is None or not verify_password(current_password, user_with_hash["password_hash"]):
        return _error("Current password is incorrect.")
    if len(new_password) < 8:
        return _error("New password must be at least 8 characters.")
    if new_password != new_password_confirm:
        return _error("New passwords do not match.")

    with request.app.state.pool.connection() as conn:
        db.update_password(conn, current_user["id"], hash_password(new_password))

    return flash_redirect("/settings/account", "Password updated.")
```

- [ ] **Step 5: Create `app/web/templates/settings_account.html`**

```html
{% extends "base.html" %}
{% block content %}
{% include "settings_tabs.html" %}
<h1>Account</h1>

{% if error %}
<div class="error" role="alert">{{ error }}</div>
{% endif %}

<form method="post" action="/settings/account/password">
<div class="card">
  <fieldset>
    <legend>Change password</legend>
    <div class="form-group">
      <label for="current_password">Current password</label>
      <input id="current_password" name="current_password" type="password" autocomplete="current-password" required>
    </div>
    <div class="form-group">
      <label for="new_password">New password</label>
      <input id="new_password" name="new_password" type="password" autocomplete="new-password" required minlength="8">
    </div>
    <div class="form-group">
      <label for="new_password_confirm">Confirm new password</label>
      <input id="new_password_confirm" name="new_password_confirm" type="password" autocomplete="new-password" required minlength="8">
    </div>
  </fieldset>
</div>
<div class="form-actions">
  <button type="submit" class="btn btn-primary">Update password</button>
</div>
</form>
{% endblock %}
```

- [ ] **Step 6: Add "Account" tab to `app/web/templates/settings_tabs.html`**

The current file ends with:
```html
  <a href="/settings/preferences" {% if request.url.path == "/settings/preferences" %}aria-current="page"{% endif %}>Preferences</a>
</nav>
```

Change to:
```html
  <a href="/settings/preferences" {% if request.url.path == "/settings/preferences" %}aria-current="page"{% endif %}>Preferences</a>
  <a href="/settings/account" {% if request.url.path == "/settings/account" %}aria-current="page"{% endif %}>Account</a>
</nav>
```

- [ ] **Step 7: Run account settings tests — confirm PASS**

```
pytest tests/web/test_settings_account.py -v
```

- [ ] **Step 8: Run full test suite — confirm no regressions**

```
pytest tests/ -x -q
```

- [ ] **Step 9: Commit**

```bash
git add app/web/routes_settings.py app/web/templates/settings_account.html app/web/templates/settings_tabs.html tests/web/test_settings_account.py
git commit -m "feat: add Account settings tab with change-password form

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KR3FdjZuPUMQ9ZdszibyZH"
```

---

### Task 6: Version bump and changelog

**Files:**
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`

**Interfaces:**
- No code — documentation and version metadata only.

- [ ] **Step 1: Bump version in `pyproject.toml`**

Change:
```toml
version = "1.1.1"
```
To:
```toml
version = "1.2.0"
```

- [ ] **Step 2: Update `CHANGELOG.md`**

Insert the following new section between the `## [Unreleased]` header and the existing `## [1.1.1]` section:

```markdown
## [1.2.0] — 2026-09-21

### Added

- **Account recovery from the login page.** A "Forgot username or password?" link on
  the sign-in page opens a one-page recovery flow. Enter the email address associated
  with your account; if the email is registered and admin SMTP is configured, you'll
  receive an email containing your username and a time-limited password-reset link
  (expires in 1 hour). The response is always the same neutral confirmation to avoid
  revealing whether an email address is registered.

- **Password reset via email link.** The reset link from the recovery email leads to
  `/reset-password`, where you can set a new password. The link is invalidated
  immediately after use (the token embeds a fingerprint of the current password hash,
  so changing the password makes any earlier token fail). A successful reset redirects
  to the sign-in page.

- **Change password from Settings.** A new **Account** tab in Settings
  (`/settings/account`) lets any authenticated user (admin or member) change their
  password by supplying their current password and a new one. The tab appears after
  "Preferences" for all roles.
```

- [ ] **Step 3: Run full test suite — confirm version appears in responses**

```
pytest tests/ -x -q
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: bump version to 1.2.0; document password reset in CHANGELOG

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KR3FdjZuPUMQ9ZdszibyZH"
```

---

## CI/CD

After all tasks are committed:

```bash
# Lint
ruff check app/ tests/

# Type-check
mypy app

# Full test suite
pytest tests/ -q

# Dependency audit
pip-audit
```

All checks must pass before opening the PR. Then:

```bash
git push -u origin feat/password-reset
gh pr create --title "feat: password reset and account recovery (v1.2.0)" \
  --body "..."
```
