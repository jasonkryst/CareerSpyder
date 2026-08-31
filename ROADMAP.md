# Roadmap

Known limitations and planned future work for CareerSpyder, past the v1
release described in [CHANGELOG.md](CHANGELOG.md). Nothing here is
scheduled — it's a backlog, roughly ordered by impact within each section.
Items marked **(from design spec)** were explicitly deferred at design
time; items marked **(from review)** were flagged as minor/non-blocking by
the whole-branch code review that preceded the v1 release and parked for
later rather than fixed immediately.

## Security & access

- **Authentication on the web UI (from design spec).** v1 has none — it's
  built for a trusted home/private network only. Before exposing this
  beyond that, add at minimum a login gate; consider whether "single user"
  is still the right model at that point.
- **Editable SMTP password (from design spec).** Currently env-var only by
  design, to avoid persisting a credential in plaintext on disk. If this
  becomes painful operationally, revisit with e.g. an encrypted-at-rest
  secret store rather than a plain UI field.
- **No CSRF protection on any state-changing route (from audit).** Every
  `POST` route trusts any request that reaches it by network path alone.
  Since the app sets no cookies, a per-user token isn't a natural fit;
  an `Origin`/`Sec-Fetch-Site` check on state-changing requests would
  close this without new session infrastructure. See
  [docs/audits/2026-08-19-app-audit.md](docs/audits/2026-08-19-app-audit.md#m1-no-csrf-protection-on-any-state-changing-route)
  (finding M1) — this is what makes the SSRF finding below remotely
  triggerable, so fix together.
- **SSRF via user-configured source URLs (from audit).** URL-bearing
  source fields (`generic_html`, `linkedin`, `indeed`, `infor`,
  `talentbrew`, `workday`, `phenompeople`, `findly`) have no scheme
  allow-list and no internal/link-local address check, and
  `/sources/test-preview` executes the adapter immediately without the
  source being saved. Playwright-driven adapters will navigate to
  `file://` and internal-network URLs. See
  [docs/audits/2026-08-19-app-audit.md](docs/audits/2026-08-19-app-audit.md#h1-ssrf-via-user-supplied-source-urls-reachable-through-sourcestest-preview-with-no-csrf-protection-to-gate-it)
  (finding H1).
- **Unbounded settings-import upload and unrate-limited preview fetches
  (from audit).** `/settings/data`'s import has no upload size cap;
  `/sources/test-preview`'s Playwright-driven fetches have no concurrency
  limit (unlike the daily run, which is serialized). See the audit's
  findings M2 and M3.
- **Minor security hygiene items (from audit).** `board_token` is
  interpolated unescaped into the Greenhouse/Lever API URL (finding L1);
  a non-numeric `max_pages` form value raises an unhandled 500 instead of
  a graceful validation error (finding L2); runtime dependencies are
  pinned with `>=` only, no upper bounds (finding L3). None are urgent —
  see the audit for details.

## Reliability & operations

- **Concurrent writes to `sources.json` aren't locked (from review).** The
  save path is atomic (temp file + `os.replace`) but two simultaneous
  `/sources` edits can still interleave before the swap. Low risk for a
  single-operator deployment; worth a lock (mirroring the SQLite run lock
  in `app/orchestrator.py`) if this ever gets multiple concurrent editors.
- **SMTP port 465 / implicit TLS isn't supported (from review).** The
  emailer always does STARTTLS; the settings page accepts port 465 without
  validating it needs `smtplib.SMTP_SSL` instead. Either branch on the
  port or restrict/validate to STARTTLS-compatible ports.
- **Missed daily runs aren't caught up (from review).** APScheduler's
  default misfire grace time means a restart or a busy process at
  `RUN_HOUR:00` silently skips that day. Consider a small grace window
  plus a "haven't run today yet" check at startup.
- **Very large aggregate job counts could hit SQLite's bound-parameter cap
  (from review).** `db.get_new_jobs` binds one SQL parameter per job
  checked; SQLite's default limit is 32,766. A single well-known ATS board
  can already return 500+ postings, so a config with many large boards
  should chunk the `IN (...)` query.

## Features

- **Auto-dedup engine for secondary sources (issue #82, item 4).** Jobs
  found by secondary sources (Indeed, LinkedIn) could be automatically
  compared against primary-source listings using title + company similarity
  scoring (e.g. `difflib.SequenceMatcher`) to produce low/medium/high
  confidence duplicate candidates. High-confidence matches could be
  auto-flagged; lower-confidence ones surfaced for manual review in the UI.
  Manual duplicate marking (added in #82) provides the data model for this.
- **Official LinkedIn/Indeed APIs or RSS feeds (from design spec).** The
  current `linkedin`/`indeed` adapters are explicitly best-effort
  Playwright scraping of public search pages — fragile by nature (layout
  changes, blocking, CAPTCHAs). Replacing them with an official API or RSS
  source, where available, would be far lower-maintenance.
- **Job type (full-time/part-time/contract) filtering.** No adapter
  currently extracts employment type. Known availability by platform:
  - **Lever:** `categories.commitment` in the job listing API response
    (e.g. `"Full-time"`, `"Part-time"`, `"Contract"`) — available.
  - **Greenhouse:** job metadata may include employment type — needs investigation per board.
  - **Findly:** API response may include an `employment_type` field — needs investigation.
  - **Workday:** job posting detail fields may expose job type — needs investigation.
  - **TalentBrew, Infor, LinkedIn, Indeed:** HTML/Playwright scrapers with no reliable
    structured job-type field; would require regex parsing of unstructured content.
  Implementing requires: a `job_type` field on the `Job` model and DB schema, per-adapter
  extraction for supported platforms, and a filter UI control.
- **Digest subject line doesn't mention failures when jobs also exist
  (from review).** `app/digest.py` currently only reflects the new-job
  count in the subject when there are new jobs, even if the same run also
  had source failures — a minor readability gap, not a functional one.

## UI, UX & accessibility

- **Raw pydantic/adapter exceptions shown directly to end users (from
  audit).** Source add/edit validation errors and `/sources/test-preview`
  failures both render `str(exc)` verbatim — confusing jargon for a
  self-hosting home user, and a minor incidental leak of internal model
  names and library internals. See finding U2.
- **Ambiguous "Status" filter naming on `/jobs` and `/jobs/map` (from
  audit).** The filter labeled "Status" filters Active/Removed, while the
  table's own "Status" column shows the separate Applied/Ignored/
  Accepted/Rejected/Not Interested job status (filtered by the
  differently-labeled "Job status" field). See finding U4.
- **Smaller UX/accessibility polish items (from audit).** No
  required-field indication on the source form (U5); the confirm-modal
  has no non-JS fallback, so Delete/Import submit with zero warning if JS
  is blocked (U6); form validation error banners aren't marked
  `role="alert"` (A3). See the audit for details on each.

Full write-up, including what's already solid (landmarks, focus
handling, dark-mode contrast, responsive table collapse, etc.):
[docs/audits/2026-08-19-app-audit.md](docs/audits/2026-08-19-app-audit.md).

## Testing & tooling

- **Local dev environment doesn't match the deploy runtime (from
  review).** The `Dockerfile` pins `python:3.12-slim`; local development
  has run against newer interpreters. Pin (or document) a matching local
  Python version so the test suite exercises the same runtime that ships.
- **No settings-survives-a-restart test (from review).** `/settings`
  writes are covered unit-wise, but nothing simulates a container restart
  to confirm persisted settings actually reload correctly.
