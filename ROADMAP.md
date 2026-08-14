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
- **Docker image hardening (from review).** No `HEALTHCHECK`, runs as
  root, base image isn't digest-pinned. Worth doing before this runs
  anywhere more exposed than a home lab.
- **Very large aggregate job counts could hit SQLite's bound-parameter cap
  (from review).** `db.get_new_jobs` binds one SQL parameter per job
  checked; SQLite's default limit is 32,766. A single well-known ATS board
  can already return 500+ postings, so a config with many large boards
  should chunk the `IN (...)` query.

## Features

- **Official LinkedIn/Indeed APIs or RSS feeds (from design spec).** The
  current `linkedin`/`indeed` adapters are explicitly best-effort
  Playwright scraping of public search pages — fragile by nature (layout
  changes, blocking, CAPTCHAs). Replacing them with an official API or RSS
  source, where available, would be far lower-maintenance.
- **Multi-recipient digest email (from design spec + review).** `email_to`
  is a single address today. Comma-splitting it into multiple recipients
  is a small, low-risk addition if/when more than one person wants the
  digest.
- **Richer frontend (from design spec).** v1 is deliberately
  server-rendered, full-page-reload HTML with no SPA and no JS build step.
  A live-updating dashboard (e.g. via polling or SSE for in-progress "Run
  now" status) is a reasonable next step if the current UX feels too
  static, but isn't needed for the core job-digest use case.
- **Digest subject line doesn't mention failures when jobs also exist
  (from review).** `app/digest.py` currently only reflects the new-job
  count in the subject when there are new jobs, even if the same run also
  had source failures — a minor readability gap, not a functional one.

## Testing & tooling

- **Local dev environment doesn't match the deploy runtime (from
  review).** The `Dockerfile` pins `python:3.12-slim`; local development
  has run against newer interpreters. Pin (or document) a matching local
  Python version so the test suite exercises the same runtime that ships.
- **No settings-survives-a-restart test (from review).** `/settings`
  writes are covered unit-wise, but nothing simulates a container restart
  to confirm persisted settings actually reload correctly.
- **Scheduler test still mocks the orchestrator and digest builder (from
  review).** `tests/test_scheduler.py` verifies wiring, but nothing
  exercises the real orchestrator → digest → "skip email when nothing to
  report" path as one integration test with real objects (only mocked
  adapters, per the project's no-live-network testing constraint).
