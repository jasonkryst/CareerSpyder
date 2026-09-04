# CareerSpyder security audit — 2026-09-04

A follow-up, security-focused review requested to check on the **Security**
section of [`docs/audits/2026-08-19-app-audit.md`](2026-08-19-app-audit.md)
(from `v0.37.1`), roughly 19 releases later at `v0.56.1`. This audit
**supersedes/updates that prior audit's Security section only** — its
UI/UX and Accessibility sections are out of scope here (several of those
items, U1/U3/A2, have since been fixed per `CHANGELOG.md` 0.51.0, but that's
not re-verified in this document).

Scope: `app/` in full (`adapters/`, `web/routes_*.py`, `config.py`, `db.py`,
`orchestrator.py`, `checker.py`, `digest.py`, `emailer.py`, `scheduler.py`,
`geocoding/`), `Dockerfile`, `docker-compose.yml`/`docker-compose.prod.yml`,
`docker-entrypoint.sh`.

Methodology: a static code review of the files above, cross-referenced
against `CHANGELOG.md` to date each behavior change, plus `pip-audit`
against an environment matching `pyproject.toml`'s floor versions. This was
not a penetration test against a deployed instance.

Severity labels (Critical/High/Medium/Low/Informational) reflect impact
*within CareerSpyder's documented trust model*: a single-operator app
designed for a trusted home/private network with no authentication (see
[SECURITY.md](../../SECURITY.md)). The absence of authentication itself is
not re-litigated as a finding — only gaps on top of that accepted posture.

## Summary

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 1 |
| Medium | 4 |
| Low | 3 |

All four items from the prior audit's High/Medium tier (H1, M1, M2, M3) are
**still open, unchanged in substance**. One new Medium finding (N1) was
found in code added since the prior audit. The dependency baseline remains
clean.

---

## Findings

### High

**H1 (carried forward, unchanged). SSRF via user-supplied source URLs,
reachable through `/sources/test-preview` with no CSRF protection to gate
it**

`app/web/routes_sources.py:112-126`, `app/config.py:37,44,49,54,65,71,77,84`,
`app/adapters/browser.py:16`, `generic_html.py:13,15`, `indeed.py:11`,
`linkedin.py:9`, `infor.py:61`, `workday.py:40-49`, `talentbrew.py:74-78`,
`phenompeople.py:11-22`

Every URL-bearing source field is still a plain `str` with only
`min_length=1` — no scheme allow-list, no check against internal/link-local
address ranges:

```python
# app/config.py:35-44
class GenericHtmlSource(BaseSource):
    type: Literal["generic_html"]
    url: str = Field(min_length=1)
    ...
class LinkedInSource(BaseSource):
    type: Literal["linkedin"]
    url: str = Field(min_length=1)
```

`POST /sources/test-preview` (`routes_sources.py:112-126`) still takes this
straight from form data and immediately executes the corresponding adapter
server-side — no source needs to be saved first, and the endpoint requires
no confirmation. For `generic_html` with `render_js: true`, `linkedin`,
`indeed`, and `infor`, this drives Playwright's Chromium directly:

```python
# app/adapters/browser.py:4-17
def render_html(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ...
            page.goto(url, wait_until="networkidle", timeout=30000)
```

`page.goto(url, ...)` has no scheme or host restriction, so a crafted
`url`/`career_site_url` can make the container's headless Chromium navigate
to any address reachable from its network namespace — RFC1918 ranges,
`localhost`, cloud metadata (`169.254.169.254`), or `file://` paths — and
`generic_html`'s attacker-supplied CSS selectors let the response be
scraped back out through the JSON preview response. The `requests`-based
adapters (`workday.py`, `talentbrew.py`, `phenompeople.py`,
`indeed.py`/`linkedin.py` when not rendering JS) carry the same SSRF
exposure into `requests.get`/`requests.post`, just without the `file://`
angle.

Because `/sources/test-preview` still has no CSRF protection (see M1), this
remains exploitable blind by an unrelated malicious webpage visited by
anyone whose browser can reach the CareerSpyder instance — the attacker
never needs direct network access to the instance itself.

*Fix (unchanged from prior audit):* validate URL fields with
`pydantic.AnyHttpUrl` restricted to `http`/`https`; resolve the hostname
and reject loopback/link-local/RFC1918 targets (re-checked after redirects)
before both `requests` calls and `page.goto()`. Prioritize alongside M1.

### Medium

**M1 (carried forward, unchanged in substance — blast radius grew). No CSRF
protection on any state-changing route**

`app/web/main.py:46-58` (no CSRF/CORS/Origin-check middleware registered),
and all fourteen `@router.post(...)` handlers:

```
app/web/routes_dashboard.py:43   /run-now
app/web/routes_dashboard.py:56   /check-urls
app/web/routes_jobs.py:165       /jobs/status
app/web/routes_jobs.py:182       /jobs/remove
app/web/routes_jobs.py:199       /jobs/duplicate
app/web/routes_jobs.py:229       /jobs/location-override
app/web/routes_settings.py:56    /settings/email
app/web/routes_settings.py:83    /settings/preferences
app/web/routes_settings.py:111   /settings/data/clear-cache
app/web/routes_settings.py:178   /settings/data/import
app/web/routes_sources.py:47     /sources/{id}/delete
app/web/routes_sources.py:61     /sources/new
app/web/routes_sources.py:88     /sources/{id}/edit
app/web/routes_sources.py:112    /sources/test-preview
```

No anti-CSRF token, `Origin`, or `Referer` check exists anywhere, and no
`CORSMiddleware` is registered. Since the prior audit, three of these
routes are *new* (`/jobs/remove`, `/jobs/duplicate`,
`/jobs/location-override`, added in `v0.45.0` per `CHANGELOG.md:119-138`),
and a fourth (`/jobs/status`) gained a JSON response mode. All four detect
`Accept: application/json` and skip the redirect in favor of a JSON body —
but `Accept` is a CORS-safelisted header and `FormData` a safelisted
content type, so a cross-site page can still fire these as a "simple"
request (no preflight) exactly as it could before; only the *response* is
opaque to the attacker, not the side effect. Concrete new chains: a
malicious page can blind-POST `/jobs/remove` or `/jobs/duplicate` for a
guessed/enumerated `key`, or drive `/jobs/location-override` to spend the
victim's Nominatim quota (see N1).

*Fix (unchanged from prior audit):* reject state-changing requests whose
`Origin`/`Sec-Fetch-Site` doesn't match the app's own host.

**M2 (carried forward, unchanged). Unbounded file upload on settings
import**

`app/web/routes_settings.py:186`, `app/config.py:142-146`

```python
# app/web/routes_settings.py:178-189
@router.post("/settings/data/import")
async def import_settings(request: Request):
    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        ...
    raw = await upload.read()
    try:
        sources = config.import_sources_json(request.app.state.sources_path, raw)
```

`upload.read()` still has no size cap before the bytes are `json.loads()`'d.

*Fix (unchanged from prior audit):* enforce an explicit max content-length
before/while reading.

**M3 (carried forward, unchanged). No concurrency/rate limit on
Playwright-driven preview fetches**

`app/web/routes_sources.py:123`, `app/adapters/browser.py:1-19`

Each `render_js` preview (and `linkedin`/`indeed`/`infor` previews) still
launches a fresh headless Chromium instance via
`run_in_threadpool(ADAPTERS[source.type], source)` with no limit on
concurrent invocations, unlike `orchestrator.run_once`, which is serialized
by `orchestrator.py`'s `_run_lock`. Reachable blind via M1.

*Fix (unchanged from prior audit):* add an in-process semaphore/lock around
preview fetches, mirroring `orchestrator.py`'s `_run_lock`.

**N1 (new). Unbounded, unauthenticated outbound geocoding requests via a
plain `GET`, bypassing the app's own Nominatim rate limit — DoS and
third-party-ToS risk**

`app/web/routes_jobs.py:51-61` (`jobs()`), `app/web/routes_jobs.py:132-140`
(`jobs_map_data()`), `app/web/routes_jobs.py:247-249`
(`update_location_override()`), `app/geocoding/nominatim.py:16-54`

The zip/location-radius filter (added `v0.45.0`, `CHANGELOG.md:109-115`)
calls the geocoder synchronously, once per request, directly from the
request path:

```python
# app/web/routes_jobs.py:51-58 (jobs()); jobs_map_data() at :132-139 is identical
if zip_code:
    geocoder = get_geocoder()
    try:
        result = geocoder.geocode(zip_code)
    except Exception:  # noqa: BLE001
        result = None
```

`NominatimGeocoder.geocode()` (`app/geocoding/nominatim.py:30-40`) issues a
blocking `requests.get(..., timeout=10)` to
`nominatim.openstreetmap.org` with **no caching and no throttling** at this
call site. The only rate limiting in the codebase
(`geocoder.min_interval_seconds`, a documented 1 request/second) is applied
solely inside `app/geocoding/service.py:20-22`'s background
`geocode_pending` loop — the on-demand paths in `routes_jobs.py` bypass it
entirely.

Both `/jobs` and `/jobs/map/data` are plain `GET` routes, so unlike the
POST-based findings above, no CSRF gate would even help here: any page —
including a passive `<img src="http://<host>/jobs?zip=00501">` or link
prefetch — triggers the outbound call with zero user interaction. Because
FastAPI runs synchronous `def` route handlers in a bounded thread pool,
concurrently loading enough distinct `zip=`/`location=` values (cache
misses each hold a worker for up to the 10s Nominatim timeout) can exhaust
that pool and stall the app for its legitimate single operator — a
low-cost DoS. It also lets an outside page cause the app's outbound IP to
send bursts of un-throttled traffic to a third-party service
(`nominatim.openstreetmap.org`), risking that IP being rate-limited/banned
under Nominatim's usage policy, independent of any impact to CareerSpyder
itself. `/jobs/location-override` (`routes_jobs.py:247-249`, a POST, gated
by M1 not by anything here) has the same unthrottled-call issue for
operator-triggered/blind-CSRF-triggered manual overrides.

*Fix:* cache geocode results for the request's `zip`/`location` value
(e.g. keyed in `geocoded_locations`, which already exists for job
locations) instead of calling Nominatim fresh per page view; apply
`min_interval_seconds` (or a stricter per-process token bucket) to this
call site the same way `geocode_pending` does; consider capping how often
an unresolved `zip=`/`location=` value can be retried.

### Low

**L1 (carried forward, unchanged). `board_token` interpolated unescaped
into fixed-host API URLs**

`app/adapters/greenhouse.py:9`, `app/adapters/lever.py:9` — still validated
only as `min_length=1`, still placed directly into an f-string URL path
with no `urllib.parse.quote`.

*Fix (unchanged from prior audit):* `urllib.parse.quote(source.board_token,
safe="")`, or restrict the field to `^[A-Za-z0-9_-]+$`.

**L2 (carried forward, scope grew). Unhandled `ValueError` on malformed
numeric form fields**

`app/web/source_form.py:73,81,86,98` (`int(form["max_pages"])`, now
repeated across `infor`, `talentbrew`, `workday`, and `findly` — the last
three added after the prior audit) and, not previously called out,
`app/web/routes_settings.py:61` (`int(_str_field(form, "smtp_port"))`) —
none of these guard the conversion, so a non-numeric value raises a bare
`ValueError` before validation, producing an unhandled 500 instead of a
graceful re-render.

*Fix (unchanged from prior audit):* wrap the conversions or pre-validate
with a regex.

**L3 (carried forward, unchanged). Loose dependency version floors, no
ceilings**

`pyproject.toml:8-17` — all runtime deps are still `>=` only. `pip-audit`
is currently clean (see below), and CI gained a Trivy filesystem scan
(`v0.52.0`) plus the pre-existing container-image scan, both now uploading
SARIF to the repo's Security tab — real hardening since the prior audit,
though it doesn't change the underlying lack of upper bounds.

*Fix (unchanged from prior audit):* consider a lockfile or upper bounds on
security-sensitive deps reviewed on a cadence.

### Informational (verified, no gap found)

- Re-verified: Jinja2 autoescaping is intact everywhere (`grep`'d every
  template for `| safe`/`autoescape false` — none found); digest email
  escaping (`app/digest.py`) still routes every interpolated field through
  `html.escape` and every href through `safe_url_scheme`; `app/db.py`'s
  dynamic SQL (`list_jobs`, `list_runs`, `list_mappable_jobs`, etc., grown
  substantially since the prior audit with the state/zip/duplicate filters)
  still draws `ORDER BY`/`WHERE` structure only from fixed allow-list dicts
  or literal ternaries, with all values passed as `?` placeholders — no
  regression despite the added surface area.
- New check: `emailer.py`'s `MIMEText` header assignment
  (`msg["From"] = email_from`, `msg["To"] = ...`) is not proactively
  validated against CRLF injection in `routes_settings.py`'s
  `save_settings`/`save_preferences`, but Python's stdlib `email` generator
  independently rejects embedded newlines in header values at send time
  (verified: assigning `"a@b.com\r\nBcc: x@y.com"` to a header and calling
  `.as_string()` raises `email.errors.HeaderParseError`), and
  `scheduler.py:65-73` wraps the send in a broad `try/except` that logs and
  swallows it — so this fails closed (no email sent) rather than enabling
  header injection.
- `flash_redirect()` (`app/web/flash.py`) is only ever called with
  hardcoded literal paths, never user input — no open-redirect surface.
- `SMTP_PASSWORD` is still correctly absent from the settings export
  payload and remains a container-env-only value.
- Docker hardening is unchanged and solid: digest-pinned base image,
  non-root uid 1000 via `setpriv`, `pip` itself uninstalled from the final
  image after dependency install (`Dockerfile`), so the one vulnerable
  package `pip-audit` found (see below) never ships in the runtime image.

---

## Dependency scan (`pip-audit`)

The project has no committed lockfile/venv, so `pip-audit` was run against
a Python environment whose installed package versions were confirmed to
match `pyproject.toml`'s floors (`fastapi==0.141.1`, `jinja2==3.1.6`,
`pydantic==2.13.4`*, `playwright==1.62.0`, `beautifulsoup4==4.15.0`,
`requests==2.34.2`, `python-multipart==0.0.32`, `uvicorn==0.52.3`,
`apscheduler==3.11.3`). `python -m pip_audit` (no args, auditing the
environment directly — passing `pyproject.toml` to `-r` failed since it
isn't a `requirements.txt`-formatted file):

```
Found 1 known vulnerability in 1 package
Name Version ID              Fix Versions
---- ------- --------------- ------------
pip  26.1.2  PYSEC-2026-3721 26.2
```

All of CareerSpyder's actual runtime dependencies are clean. The one
finding is in `pip` itself, a build-time tool that the `Dockerfile`
explicitly uninstalls after `pip install .` completes — it is not present
in the shipped image. (`careerspyder` itself was skipped as "not found on
PyPI," expected for a private project package.)

---

## Changes since 2026-08-19

- **Still open, unchanged:** H1 (SSRF via source URLs / test-preview), M1
  (no CSRF anywhere), M2 (unbounded settings-import upload), M3 (no
  concurrency limit on preview Chromium launches), L1 (`board_token`
  unescaped in Greenhouse/Lever URLs), L3 (loose dependency floors).
- **Still open, scope grew:** L2 (unhandled `ValueError` on numeric form
  fields) now spans four source types plus `routes_settings.py`'s
  `smtp_port`; M1's affected-route count grew from 10 to 14 as
  `/jobs/remove`, `/jobs/duplicate`, and `/jobs/location-override` were
  added in `v0.45.0` with no CSRF gate of their own.
- **New:** N1 (Medium) — the zip/location-radius filter, also added in
  `v0.45.0`, added an unauthenticated, unthrottled outbound-request path to
  a third-party geocoding service that bypasses the app's own existing rate
  limit and is triggerable via a plain `GET`.
- **Regressed:** none found — no previously-fixed security item reopened.
- **Hardening added (informational, not a finding either way):** a Trivy
  filesystem scan (`v0.52.0`) now runs in CI alongside the existing
  container-image scan, both uploading SARIF to GitHub's Security tab.
