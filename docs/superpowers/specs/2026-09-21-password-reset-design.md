# Password Reset & Account Recovery Design

**Date:** 2026-09-21  
**Status:** Approved  
**Version target:** 1.2.0

---

## Overview

Adds three capabilities to CareerSpyder:

1. **Account recovery** — an unauthenticated "Account recovery" flow accessible from the login page. Users enter their email; if it matches an account, one email is sent containing their username and a time-limited password-reset link.
2. **Password reset** — the reset link leads to a form where the user sets a new password. The link expires after 1 hour and is invalidated after use.
3. **Change password (logged-in)** — a new "Account" tab in Settings lets any authenticated user change their password by providing their current password plus a new one.

---

## Token Design

Tokens are generated with `itsdangerous.URLSafeTimedSerializer`, which is already a declared dependency (`itsdangerous>=2.1`). No new database table or Alembic migration is required.

### Payload

```python
{"user_id": "<uuid>", "email": "<email>", "pw_fp": "<first 8 chars of sha256(password_hash)>"}
```

- **`user_id`** — identifies the account to reset.
- **`email`** — matches the address the token was sent to; provides a sanity check if the email ever changes.
- **`pw_fp`** — a short fingerprint of the stored `password_hash` at the time of token generation. After a successful reset the stored hash changes, so any previously-issued token fails fingerprint verification and is automatically dead. This is the same invalidation strategy used by Django's password reset.

### Parameters

| Parameter | Value |
|-----------|-------|
| Salt | `"password-reset"` (distinct from the session salt) |
| Expiry | 3600 seconds (1 hour) |
| Serializer secret | `SECRET_KEY` env var (same key used for sessions) |

---

## New Files

| File | Purpose |
|------|---------|
| `app/web/templates/account_recovery.html` | Email entry form + post-submit confirmation |
| `app/web/templates/reset_password.html` | New-password form; error view for bad/expired tokens |
| `app/web/templates/settings_account.html` | Account settings tab with change-password form |

---

## Modified Files

| File | Change |
|------|--------|
| `app/web/auth.py` | Add `generate_reset_token()` and `verify_reset_token()` |
| `app/web/routes_auth.py` | Add 4 new routes: `GET/POST /account-recovery`, `GET/POST /reset-password` |
| `app/web/routes_settings.py` | Add 2 new routes: `GET /settings/account`, `POST /settings/account/password` |
| `app/web/templates/login.html` | Add "Forgot username or password?" link to `/account-recovery` |
| `app/web/templates/settings_tabs.html` | Add "Account" tab visible to all roles |
| `tests/web/test_auth.py` | Add account-recovery and password-reset tests |
| `tests/web/test_settings_account.py` | New file: change-password tests |
| `CHANGELOG.md` | Document 1.2.0 additions |
| `pyproject.toml` | Bump version to `1.2.0` |

---

## Route Inventory

### `GET /account-recovery`

- Accessible when unauthenticated only (redirect to `/` if already logged in).
- Renders `account_recovery.html` with an email input field.

### `POST /account-recovery`

- Reads `email` from form.
- Looks up user by email via `db.get_user_by_email()`.
- If found and active: fetches admin SMTP settings via `db.get_admin_smtp_settings()`, generates a token, sends a recovery email containing:
  - The user's username (satisfies the "forgot username" case).
  - A password-reset link: `https://<host>/reset-password?token=<token>`.
- **Always** returns the same generic confirmation ("If that email is registered, we've sent instructions.") — no email-existence enumeration.
- If admin SMTP is not configured: log a warning; still show the confirmation (avoids revealing config state).

### `GET /reset-password`

- Reads `token` from query string.
- Calls `verify_reset_token()`:
  - If valid: renders `reset_password.html` with the username as read-only context and hidden token field.
  - If missing, invalid, or expired: renders `reset_password.html` in error mode with a link back to `/account-recovery`.

### `POST /reset-password`

- Reads `token`, `password`, `password_confirm` from form.
- Calls `verify_reset_token()` again (prevents token-swapping between GET and POST).
- Validates: passwords match, length ≥ 8.
- Updates `password_hash` in the `users` table via a new `db.update_password()` helper.
- Redirects to `/login` with a flash message: "Password reset. Please sign in with your new password."
- On any validation error: re-renders the form (no redirect).

### `GET /settings/account`

- Requires authentication (`require_user` dependency).
- Visible to all roles (admin and member).
- Renders `settings_account.html` with the change-password form.

### `POST /settings/account/password`

- Requires authentication.
- Reads `current_password`, `new_password`, `new_password_confirm` from form.
- Verifies `current_password` against stored hash via `verify_password()`.
- Validates: new passwords match, length ≥ 8.
- Updates hash via `db.update_password()`.
- Re-renders the form with a success or error message (no redirect).

---

## Token Helpers (`app/web/auth.py`)

```python
import hashlib
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

_RESET_SALT = "password-reset"

def generate_reset_token(secret_key: str, user_id: str, email: str, pw_hash: str) -> str:
    s = URLSafeTimedSerializer(secret_key)
    pw_fp = hashlib.sha256(pw_hash.encode()).hexdigest()[:8]
    return s.dumps({"user_id": user_id, "email": email, "pw_fp": pw_fp}, salt=_RESET_SALT)

def verify_reset_token(
    secret_key: str, token: str, conn, max_age: int = 3600
) -> dict | None:
    """Returns the user dict if the token is valid and the fingerprint matches; else None."""
    s = URLSafeTimedSerializer(secret_key)
    try:
        payload = s.loads(token, salt=_RESET_SALT, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    from app import db
    user = db.get_user_by_id_with_hash(conn, payload["user_id"])
    if user is None or not user["is_active"]:
        return None
    # Fingerprint check: invalidates tokens issued before the last password change
    expected_fp = hashlib.sha256(user["password_hash"].encode()).hexdigest()[:8]
    if payload.get("pw_fp") != expected_fp:
        return None
    return user
```

Note: `verify_reset_token` needs a DB connection to fetch the user and check the fingerprint. The call above uses a new `db.get_user_by_id_with_hash()` helper (see below); replace the `db.get_user_by_id` call in the snippet with `db.get_user_by_id_with_hash`.

---

## New DB Helpers

### `db.update_password(conn, user_id, new_hash)`

```sql
UPDATE users SET password_hash = %s WHERE id = %s
```

### `db.get_user_by_id_with_hash(conn, user_id)`

Returns the same fields as `get_user_by_id` plus `password_hash`. Used only by `verify_reset_token` and the `POST /settings/account/password` handler where the current-password check needs the stored hash.

---

## Email Template

The recovery email is an HTML string constructed in `routes_auth.py` (no separate template file). Content:

```
Subject: CareerSpyder account recovery

Your username is: <username>

If you want to reset your password, click the link below. It expires in 1 hour.

[Reset my password] → https://<host>/reset-password?token=<token>

If you didn't request this, you can ignore this email.
```

The `host` is derived from `request.base_url` (strips trailing slash).

---

## UX Details

### Login page
- Add below the submit button:
  ```html
  <p class="auth-help"><a href="/account-recovery">Forgot username or password?</a></p>
  ```

### Account recovery page (`account_recovery.html`)
- Standalone auth-card (same style as `login.html`, does not extend `base.html`).
- Before submit: single email field + "Send recovery email" button + link back to Sign in.
- After submit (same page, same URL): neutral banner — "If that email is registered, we've sent you an email with your username and a password reset link." — with a link back to Sign in. The form is hidden after submission.

### Reset password page (`reset_password.html`)
- Standalone auth-card.
- Valid token: read-only username display, new password field, confirm field, submit button.
- Invalid/expired token: error message ("This link is invalid or has expired.") + link to `/account-recovery`.

### Account settings tab (`settings_account.html`)
- Extends `base.html`, includes `settings_tabs.html` (same pattern as other settings pages).
- "Change password" section: current password, new password, confirm.
- Success: inline success alert after POST, form cleared.
- Error: inline error alert, form values preserved (except password fields).

### Settings tabs (`settings_tabs.html`)
- "Account" tab appended after Preferences, visible to all roles:
  ```html
  <a href="/settings/account" ...>Account</a>
  ```

---

## Testing Plan

### `tests/web/test_auth.py` additions

**Account recovery — positive:**
- `GET /account-recovery` renders the email form for unauthenticated users.
- Authenticated user hitting `GET /account-recovery` is redirected to `/`.
- `POST /account-recovery` with a registered email shows the confirmation message and calls `send_email` once.
- `POST /account-recovery` with an unrecognised email shows the same confirmation message and does **not** call `send_email`.
- `GET /reset-password?token=<valid>` renders the new-password form with the username visible.
- `POST /reset-password` with valid token + matching passwords ≥ 8 chars redirects to `/login`.
- After a successful reset, old password no longer authenticates.

**Account recovery — negative:**
- `GET /reset-password` with no token → 400 / error view.
- `GET /reset-password` with a tampered token → error view.
- `GET /reset-password` with an expired token (tested via `max_age=0`) → error view.
- `POST /reset-password` with mismatched passwords → 400.
- `POST /reset-password` with password < 8 chars → 400.
- `POST /reset-password` replaying token after successful reset → rejected (fingerprint mismatch).

### `tests/web/test_settings_account.py` (new file)

**Change password — positive:**
- `GET /settings/account` renders for admin.
- `GET /settings/account` renders for member.
- `POST /settings/account/password` with correct current password and valid new password → hash updated, success message shown.

**Change password — negative:**
- `POST /settings/account/password` with wrong current password → 400.
- `POST /settings/account/password` with mismatched new passwords → 400.
- `POST /settings/account/password` with new password < 8 chars → 400.
- Unauthenticated `GET /settings/account` → redirect to login.

---

## Version & Changelog

- `pyproject.toml`: `version = "1.2.0"`
- `CHANGELOG.md`: new `[1.2.0]` section documenting the three additions.

---

## Out of Scope

- Rate limiting on the recovery endpoint (acceptable for a small private instance).
- Invalidating existing login sessions on password reset (session cookies are not server-tracked; the user is simply redirected to login and the new password takes effect immediately for future logins).
- Admin-initiated password reset from the `/users` page (separate feature).
