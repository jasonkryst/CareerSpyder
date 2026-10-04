# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately via [GitHub Security
Advisories](https://github.com/jasonkryst/CareerSpyder/security/advisories/new)
rather than a public issue. Include reproduction steps and the affected
version (`pyproject.toml`'s `version`, or the image tag if using Docker).

## Supported versions

Only the latest `master`/release is supported. There's no LTS branch —
apply updates by pulling the latest image or re-deploying from `master`.

## Security model

CareerSpyder is a **private, invite-only multi-user app** designed for a
small trusted group (a household, a team) behind a reverse proxy with TLS.
It is **not** designed for open-internet self-registration.

### Authentication and sessions

- Users sign in with username + password (bcrypt-hashed, max 72 bytes).
- New accounts are created by an admin via invite links (time-limited,
  single-use tokens).
- Sessions use signed cookies (`SECRET_KEY` ≥ 32 random characters,
  required — the app refuses to start without one). Session cookies are
  `HttpOnly`, `SameSite=Lax`, and `Secure` when `PUBLIC_BASE_URL` starts
  with `https://`.
- Password changes and role changes revoke all of the affected user's
  sessions immediately.

### Per-user data isolation

- Each user's jobs, sources, run history, and settings are scoped by
  `user_id` at the database layer. Every query filters by the
  authenticated user's ID.
- Admin users can view (read-only) all users' jobs for oversight, but
  cannot modify another user's data.
- Source IDs submitted in forms are validated against the current user's
  sources — submitting another user's source ID has no effect.

### Required configuration

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Signs session cookies and password-reset links. Must be ≥ 32 random characters. Generate with: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `PUBLIC_BASE_URL` | The site's canonical HTTPS URL. Enables `Secure` session cookies, and is used for invite/reset links. |
| `ALLOWED_HOSTS` | Comma-separated hostnames the app will serve (e.g. `jobs.example.com,localhost`). Include `localhost` so Docker's healthcheck keeps working. When unset, all hosts are accepted. |

### CSRF protection

State-changing requests (POST/PUT/PATCH/DELETE) are checked against the
`Origin` and `Sec-Fetch-Site` headers that modern browsers attach
automatically. This complements the `SameSite=Lax` session cookie: a
cross-origin `<form>` POST from a malicious page is blocked even though
the browser would send the cookie. Requests carrying neither header
(non-browser API clients, older browsers) are allowed through because they
carry no session cookie and therefore have no session to abuse.

### SSRF guard (outbound requests)

All user-supplied URLs (source URLs, preview fetches, URL checker) pass
through an SSRF guard (`app/security/ssrf_guard.py`) that:

- Resolves hostnames and blocks all non-global IP ranges (private,
  loopback, link-local, NAT64, IPv4-mapped IPv6).
- Pins the validated IP address to defeat DNS rebinding between check and
  connect.
- Returns a generic "URL is not allowed" error that does not leak the
  resolved IP.

The headless browser (Playwright/Chromium) has an additional guard layer
that intercepts every HTTP(S) request and WebSocket the page opens via
`page.route()` and `page.route_web_socket()`, walks redirect chains
hop-by-hop (since Chromium follows 3xx redirects outside Playwright's
routing), and blocks service workers.

### SMTP

SMTP connections verify server certificates for both STARTTLS (port 587)
and implicit TLS (port 465). Self-signed certificates are rejected.
`SMTP_PASSWORD` is a container env var only — never written to disk, never
shown or editable in the UI.

## Residual risks (not vulnerabilities)

These are known, accepted limitations documented here so they are not
reported as new findings:

- **Browser-guard DNS rebinding window for WebSocket connections.**
  `page.route_web_socket()` does not support IP pinning — the handler
  validates the URL but `connect_to_server()` re-resolves the hostname. A
  DNS rebinding attack against a WebSocket-speaking internal service is
  theoretically possible but requires the attacker to control both DNS and
  the page content being scraped.
- **Browser-guard redirect window for sub-resources.** The guard checks
  every sub-resource's initial URL but does not walk redirect chains for
  non-document requests (images, scripts, etc.). A sub-resource redirect
  to an internal host would connect.
- **Chromium sandbox is off by default in Docker.** Most Docker runtimes
  do not allow unprivileged user namespaces, which Chromium's sandbox
  requires. Set `CHROMIUM_SANDBOX=1` if your host supports it (rootless
  Docker, or `sysctl kernel.unprivileged_userns_clone=1`). Enabling it
  when unsupported crashes the browser process. See Task 13 in the
  [security remediation plan](docs/superpowers/plans/2026-09-27-security-remediation.md).
- **Flash messages travel as query-string parameters (L6).** After a
  redirect (e.g. "Source saved"), the success/error message is passed in
  the URL's query string rather than in the session. This is cosmetic (the
  message is HTML-escaped in the template), not exploitable, but could be
  moved into the session for cleanliness. Tracked in
  [ROADMAP.md](ROADMAP.md).
- **CSP allows inline scripts and styles.** The app uses genuine inline
  `<script>` blocks and has no nonce/hash plumbing. This is a known
  trade-off, not an oversight.

## Audit history

- **2026-09-27:** Comprehensive security audit covering auth, CSRF, SSRF,
  SQLi, rate limiting, session management, and CVE scanning. Remediated
  across three phases (v1.5.0 tenant isolation, v1.6.0 auth hardening,
  v1.7.0 outbound requests) plus a fourth phase (this release) for
  hardening and documentation.
- **2026-09-04:** Full application audit (security, testing, a11y, i18n,
  performance, database, core functionality, devops/code quality).
