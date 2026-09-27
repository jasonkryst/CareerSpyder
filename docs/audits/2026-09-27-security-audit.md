# CareerSpyder security audit — 2026-09-27

Full internal + external security audit of `master` at `f33f829` (v1.4.0).
This **supersedes** [`2026-09-04-security-audit.md`](2026-09-04-security-audit.md):
since that audit the app gained multi-user authentication (v1.1.0),
password reset (v1.2.1), an Origin-check CSRF middleware, an SSRF guard, and
a login rate limiter (v1.3.0). Those changes closed most of the 09-04
findings but moved the trust boundary: the app is no longer a single-operator
tool on a trusted LAN — it is a multi-tenant web app with invited users,
per-user data, and a password-reset flow reachable by anyone who can reach
the port. This audit is judged against *that* model.

Remediation plan: [`docs/superpowers/plans/2026-09-27-security-remediation.md`](../superpowers/plans/2026-09-27-security-remediation.md).

## Scope and method

- **Code:** all of `app/` (auth, routes, db, orchestrator, scheduler, adapters,
  SSRF guard, checker, emailer, digest, templates, static JS), `alembic/`,
  `Dockerfile`, `docker-entrypoint.sh`, both compose files, `.env.example`,
  `.github/workflows/`, `SECURITY.md`.
- **Static review** of every route handler and every SQL statement.
- **Dynamic verification** of the highest-impact claims:
  - Cross-tenant IDOR and cross-tenant `reconcile_jobs` were reproduced with a
    throwaway pytest probe against a real Postgres (`cs-test-pg` container):
    a `member` POSTing `/jobs/remove` for the admin's job key got `303` and the
    admin's row gained `removed_at`; running user A's scrape (A has no sources)
    set `removed_at` on user B's job.
  - Playwright redirect bypass reproduced with a local `/a → 302 → /b` server:
    `page.route("**/*")` saw only `/a`; Chromium loaded `/b` unchecked.
  - `ssrf_guard._is_disallowed_ip("100.64.0.1")` returns `False` (allowed).
  - `bcrypt` 5.0.0 `hashpw`/`checkpw` raise `ValueError` on >72-byte input.
  - `pip-audit`: no known vulnerabilities in runtime dependencies (only local
    `pip` itself, which the Docker image uninstalls).
- **Not done:** a penetration test against the production deployment, or a
  review of the Portainer host / reverse proxy configuration.

## Threat actors

| Vector | Actor | Reaches |
|---|---|---|
| **External, unauthenticated** | Anyone who can reach port 32600 (LAN, or internet if proxied/forwarded) | `/login`, `/account-recovery`, `/reset-password`, `/register`, `/static`, PWA routes |
| **External, content** | Operator of any site a source points at (or who compromises one) | Headless Chromium, `requests` adapters, URL checker, digest email body |
| **External, network** | On-path attacker between the container and the SMTP server / job sites | SMTP credential, scraped content |
| **Internal, authenticated** | Any invited `member` (or a stolen member session) | Every `require_user` route |
| **Internal, host/container** | Code execution inside the app container | Env secrets (`SECRET_KEY`, `SMTP_PASSWORD`, `DATABASE_URL`), Postgres, LAN |

## Summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 0 | — |
| High | 5 | H1–H5 |
| Medium | 9 | M1–M9 |
| Low | 8 | L1–L8 |

The dominant theme is **incomplete tenant isolation**: the v1.1 multi-user
migration added `user_id` columns and scoped the *read* paths, but most
*write* paths, the global `jobs.key` primary key, and the scrape pipeline
still behave as if there were one user. The second theme is **SSRF guard
gaps** — the guard exists and is wired into most adapters, but it can be
bypassed through the browser, DNS rebinding, CGNAT ranges, and the URL
checker.

---

## High

### H1. Cross-tenant IDOR on every job mutation route — *internal* (confirmed)

`app/web/routes_jobs.py:205-335`; `app/db.py:537-637`

`/jobs/status`, `/jobs/remove`, `/jobs/duplicate`, and
`/jobs/location-override` require a logged-in user but pass only the
form-supplied `key` to `db.set_job_status`, `mark_job_removed`,
`set_job_duplicate`/`clear_job_duplicate`, `set_location_override`/
`clear_location_override` — all of which filter `WHERE key = %s` with no
`user_id`. Job keys are not secret: they are built from public ATS
identifiers (`greenhouse:{id}`, `lever:{id}`, `workday:{requisition_id}`,
`linkedin:{href}`…, see `app/adapters/*.py`), so a member can read the IDs
straight off a public job board and rewrite or hide another user's jobs.
`/jobs/remove`'s JSON branch also reads `removed_at` back unscoped
(`routes_jobs.py:241`).

**Fix:** scope every job read/write by `(user_id, key)`; hide row actions in
`jobs.html` for rows the viewer doesn't own (admin's cross-user view becomes
read-only).

### H2. Any user can delete every tenant's jobs — *internal*

`app/web/routes_settings.py:162-172`; `app/db.py:70-72`

`POST /settings/data/clear-cache` needs only `require_user` and runs
`DELETE FROM jobs` — every user's jobs, statuses, and duplicate flags.

**Fix:** `clear_jobs(conn, user_id)` deleting only the caller's rows (and
their `job_status_history`).

### H3. Scrape pipeline is not tenant-scoped — cross-tenant data corruption — *internal* (confirmed)

`app/orchestrator.py:188-239`; `app/db.py:18-68, 468-534, 601-620`;
`alembic/versions/0001_initial_schema.py:57` (`key TEXT PRIMARY KEY`)

`scheduler.run_and_notify` runs `orchestrator.run_once` once per user, but
inside it:

- `reconcile_jobs` selects **all** active jobs and treats any `source_id` not
  in *this user's* sources as deleted → each user's run marks every other
  user's jobs removed; the owner's next run "reactivates" them and resets
  `emailed_at = NULL`, so jobs churn and get re-emailed.
- `jobs.key` is a global primary key and `get_new_jobs` checks keys globally,
  so a second user who adds the same job board never receives those jobs
  (`ON CONFLICT DO NOTHING` silently drops them).
- `refresh_job_urls`, `mark_emailed`, `get_job_statuses`, `get_emailed_keys`,
  and the in-run `checker.check_job_urls(conn)` all operate on keys across
  all tenants.

Integrity rather than confidentiality, but any user can deliberately
trigger it (see M3) and it silently breaks other users' digests.

**Fix:** migration to a composite `(user_id, key)` primary key; thread
`user_id` through every pipeline helper.

### H4. Browser SSRF guard bypassable via redirect — *external content / internal* (confirmed)

`app/security/ssrf_guard.py:73-92`; `app/adapters/browser.py`; `app/adapters/infor.py:169`

`install_ssrf_guard` assumes redirect hops "arrive as separate routed
requests". They don't: Playwright's `page.route` handler is invoked only for
the first URL of a redirect chain (reproduced). A source URL on any public
host that 302s to `http://169.254.169.254/…`, `http://192.168.x.x/…`, or a
Tailscale `100.x` address passes the guard, and `render_html` returns the
internal page's HTML. Through `/sources/test-preview` with a `generic_html`
source and `render_js: true`, the attacker chooses the CSS selectors, so the
internal response comes straight back in the JSON preview — a full-read SSRF
available to any logged-in user, and to any site owner a user points a
source at. The guard also skips every non-`document` request (fetch/XHR/img/
script), so attacker page JavaScript can fire requests at LAN hosts, and
service workers are not intercepted at all.

**Fix:** for document requests, perform the hop via `route.fetch(max_redirects=0)`,
validate any `Location`, and `route.fulfill` so the next hop is routed again;
validate every resource type; block service workers.

### H5. Password-reset link poisoning via Host header — *external, unauthenticated*

`app/web/routes_auth.py:119`; `app/web/main.py:116-122`; `docker-compose*.yml` (`PUBLIC_BASE_URL: ${PUBLIC_BASE_URL:-}`)

When `PUBLIC_BASE_URL` is unset, the reset link is built from
`request.base_url`, i.e. the attacker-controlled `Host` header, and
`ALLOWED_HOSTS` defaults to `*`. An unauthenticated attacker POSTs
`/account-recovery` with the victim's email and `Host: evil.example`; the
victim receives a genuine email from the real SMTP account containing
`https://evil.example/reset-password?token=<valid token>`. One click hands
over a working reset token → account takeover (including the admin). The
app only logs a warning at startup. Invite links (`routes_users.py:51`) use
the same pattern (admin-only, lower impact).

**Fix:** never build security links from the request; refuse to send a
recovery email unless `PUBLIC_BASE_URL` is configured.

---

## Medium

### M1. SMTP TLS without certificate verification — *external, network*

`app/emailer.py:22-29`

`smtplib.SMTP.starttls()` and `SMTP_SSL(...)` are called without a
`context`; Python then uses `ssl._create_stdlib_context()`, which does **not**
verify the server certificate or hostname. An on-path attacker can present
any certificate and capture `SMTP_PASSWORD` from the `login()` that follows.

**Fix:** pass `ssl.create_default_context()` to both.

### M2. SSRF guard: DNS-rebinding TOCTOU and CGNAT gap — *internal / external content*

`app/security/ssrf_guard.py:16-62`

- `assert_safe_url` resolves the hostname, then `requests` resolves it
  **again** to connect. A low-TTL rebinding domain answers public first and
  private second.
- `_is_disallowed_ip` enumerates `is_private/loopback/link_local/…`, which
  misses `100.64.0.0/10` (CGNAT — the **Tailscale** range) and other
  non-global space. Verified: `100.64.0.1` is allowed.

**Fix:** block anything `not ip.is_global`; pin the validated IP by
connecting through a urllib3 connection class that resolves-validates-connects
in one step.

### M3. Any user can force a full run for every tenant — *internal*

`app/web/routes_dashboard.py:53-62`; `app/scheduler.py:109-119`

`POST /run-now` calls `run_and_notify(pool, tz, force=True)`, which scrapes
**all** users' sources and ignores each user's `email_days`, sending every
tenant a digest. There is no rate limit, so a member can spam it to hold
`_run_lock`, launch Chromium repeatedly, and email every user repeatedly
(and trigger H3 at will).

**Fix:** non-admins run only their own sources; rate-limit the endpoint.

### M4. Settings import overwrites another user's sources — *internal*

`app/db.py:866-883`

`import_sources` upserts `ON CONFLICT(id) DO UPDATE` without checking the
existing row's owner, and `user_id` isn't in the update set. IDs are 48
random bits (`uuid4().hex[:12]`) so blind guessing is impractical, but the
realistic case is a shared export: user A sends their `settings.json` to
user B; B's import silently rewrites A's sources (B gets nothing, message
still says "Imported N"), and every later import from B keeps rewriting A's
source configs — including the URLs A's scraper visits and whose content
lands in A's digest.

**Fix:** on conflict with another owner's row, mint a fresh id for the
importer; never update rows the importer doesn't own.

### M5. Sessions can't be revoked; cookie not `Secure` — *external / internal*

`app/web/main.py:111-112`; `app/web/auth.py:26-36`

Sessions are Starlette signed cookies holding only `user_id`, valid for 7
days. Changing or resetting a password does not invalidate other sessions,
so a stolen cookie survives the victim's password change. `https_only` is
not set, so the cookie is sent over plain HTTP too.

**Fix:** store a password-hash fingerprint in the session and compare it on
every request; set `https_only` when `PUBLIC_BASE_URL` is `https://`.

### M6. `SECRET_KEY` fails open — *external, conditional*

`app/web/main.py:30-38`; `docker-compose*.yml`; `.env.example:15`

An unset `SECRET_KEY` becomes the public constant
`"dev-insecure-secret-change-me"`; the `.env.example` placeholder
`change-me-generate-a-real-secret` is accepted too. Forging an admin session
additionally needs the admin's UUID, and forging a reset token needs the
password-hash fingerprint, so this is one leak away from takeover rather
than an instant one — but there's no reason to ever start with a known key.

**Fix:** refuse to start with a missing, placeholder, or short key.

### M7. Event-loop blocking in auth handlers; no rate limit on reset/register/change-password — *external, unauthenticated*

`app/web/routes_auth.py:34-267`; `app/web/routes_settings.py:309-339`

`login`, `register`, `reset_password`, `change_password`, and
`account_recovery` are `async def` but run bcrypt (~250 ms), synchronous
psycopg, and — in `account_recovery` — a synchronous SMTP session with a
30 s timeout **on the event loop**. A few concurrent requests stall every
other user. `/reset-password` POST, `/register` POST, and the change-password
current-password check have no rate limit. `account_recovery`'s SMTP send
only happens for known emails, so its response time is also an
account-enumeration oracle.

**Fix:** move blocking work into `run_in_threadpool`; send recovery email via
`BackgroundTasks`; add rate limits.

### M8. Headless Chromium runs unsandboxed next to all secrets — *external content*

`app/adapters/browser.py:9`; `app/adapters/infor.py`; `Dockerfile`

Playwright launches Chromium with `chromiumSandbox: false` by default, and it
renders arbitrary third-party pages (any user can choose the URL). A renderer
exploit lands directly in the app process's uid, whose environment holds
`SECRET_KEY`, `SMTP_PASSWORD`, and `DATABASE_URL`, and which can reach
Postgres and the LAN.

**Fix:** spike enabling the sandbox inside the container (seccomp profile /
user namespaces); if not viable, document the residual risk.

### M9. URL checker is an unguarded SSRF sink — *internal / external content*

`app/checker.py:20-43`

`check_job_urls` HEADs every stored job URL with raw `requests.head(...,
allow_redirects=True)`. Job URLs come from scraped pages (`generic_html`
takes `href`s from attacker-chosen pages), so any user can plant URLs to
internal addresses; the checker runs on every scrape and via `/check-urls`.
Blind, but `404/410` vs. other responses flips `removed_at`, which is an
oracle.

**Fix:** route through the SSRF-guarded HEAD; treat `UnsafeUrlError` as "skip".

---

## Low

- **L1. bcrypt >72-byte passwords → HTTP 500.** `bcrypt` 5.x raises
  `ValueError` in both `hashpw` and `checkpw`; `/login`, `/register`,
  `/reset-password`, and change-password don't catch it. Cap passwords at
  72 UTF-8 bytes. (`app/web/auth.py:18-23`)
- **L2. Cross-tenant metadata leak in filter dropdowns.** `list_job_locations`
  and `list_job_states` read the shared `geocoded_locations` table, so a
  member's `/jobs` and `/jobs/map` dropdowns list every tenant's job
  locations. (`app/db.py:412-429`; `routes_jobs.py:117-118, 147-148`)
- **L3. Preview errors leak internal network details.** `/sources/test-preview`
  returns `str(exc)`; `UnsafeUrlError` includes the resolved private IP
  ("resolves to a disallowed address: 10.0.0.5"), turning the endpoint into an
  internal-DNS oracle. (`routes_sources.py:163-164`; `ssrf_guard.py:37-41`)
- **L4. Invite single-use race.** `register` validates the invite, creates the
  user, then marks it used without checking the `UPDATE`'s rowcount, so
  concurrent submissions can mint multiple accounts from one invite.
  Usernames also have no maximum length or character set.
  (`routes_auth.py:238-264`; `db.py:774-779`)
- **L5. Unbounded digest recipients.** Any member can set `email_to` to any
  number of arbitrary addresses, and the digest body can be steered by that
  member's own `generic_html` source — mail sent from the admin's SMTP
  identity to third parties. (`routes_settings.py:114-159`)
- **L6. Flash messages via query string.** `?flash=` is rendered on every page
  (escaped — no XSS), so anyone can craft a link that shows arbitrary text
  on the trusted origin. (`base.html:90-92`; `app/web/flash.py`)
- **L7. Stale security documentation.** `SECURITY.md` still says "No
  authentication on the web UI"; `csrf_protection.py` and
  `security_headers.py` docstrings describe a no-auth app; the
  `install_ssrf_guard` docstring's redirect claim is false (H4).
- **L8. CI/infra hygiene.** `ci.yml` has no top-level `permissions:` block
  (inherits the repo default token scope); `postgres:17` isn't
  digest-pinned in either compose file.

## Verified-good (no action)

- **SQL injection:** every value is parameterized; the only interpolated
  fragments (`ORDER BY`, `IN (...)` placeholder lists) come from whitelists
  (`_JOB_SORT_COLUMNS`, `_RUN_SORT_COLUMNS`) or `%s` counts.
- **XSS:** Jinja2 autoescape everywhere, no `|safe`; the three `innerHTML`
  sinks in `jobs.html`/`leaflet_renderer.js` escape inputs; `dashboard.js`
  injects same-origin server-rendered HTML; the digest escapes all fields and
  neutralizes non-http(s) schemes.
- **Open redirect on `/login?next=`:** scheme/netloc rejected; `/\evil.com`
  is percent-encoded by Starlette (`/%5Cevil.com`).
- **CSRF:** `Sec-Fetch-Site`/`Origin` check on unsafe methods plus the
  session cookie's default `SameSite=Lax`.
- **Reset tokens:** signed, 1 h expiry, bound to a password-hash fingerprint
  (effectively single-use).
- **Deactivation:** takes effect immediately (`is_active` checked per request).
- **Secrets hygiene:** `SMTP_PASSWORD` env-only, never persisted or rendered.
- **GA:** not loaded on the token-bearing auth pages (they don't extend `base.html`).
- **Supply chain:** all GitHub Actions SHA-pinned; base image digest-pinned;
  Dependabot for pip/actions/docker; Trivy + CodeQL + pip-audit in CI;
  Docker Hub push only on `push` to `master`.
- **Container:** server process drops to uid 1000; Postgres not published to
  the host.
