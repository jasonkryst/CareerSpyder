# Roadmap

Known limitations and planned future work for CareerSpyder that aren't
(yet) tracked as their own GitHub issues. Nothing here is scheduled — it's
a backlog, roughly ordered by impact within each section. For the ranked
list of open GitHub issues, see [docs/issue-tiers.md](docs/issue-tiers.md);
for what's shipped, see [CHANGELOG.md](CHANGELOG.md).

Items marked **(from design spec)** were explicitly deferred at design
time; **(from review)** were flagged as minor/non-blocking by a code review
and parked; **(from audit)** come from
[docs/audits/2026-08-19-app-audit.md](docs/audits/2026-08-19-app-audit.md).

_Last reviewed 2026-10-22 against v1.11.2. Items verified as already
shipped (SMTP port 465 / implicit TLS, missed-run catch-up at startup, the
1 MB import cap, the `/sources/test-preview` concurrency limit, friendly
validation/preview errors (U2), the "Listing status" vs "Job status"
filter labels (U4), `role="alert"` on form error banners (A3), and the
local-vs-Docker Python version mismatch) were removed in that pass._

## Security & access

- **Editable SMTP password (from design spec).** Currently env-var only by
  design, to avoid persisting a credential in plaintext on disk. If this
  becomes painful operationally, revisit with e.g. an encrypted-at-rest
  secret store rather than a plain UI field.
- **Flash messages travel as query-string parameters (from audit, L6).**
  `app/web/flash.py::flash_redirect` passes the success/error message in
  the redirect URL's query string rather than in the session. Moving it
  into the session would be cleaner but is not exploitable (the message is
  HTML-escaped in the template). See SECURITY.md's residual-risks section.

## Reliability & operations

- **New-job lookup binds one SQL parameter per job (from review).**
  `db.get_new_jobs` builds `key IN (%s, %s, …)` with one placeholder per
  scraped job. PostgreSQL caps a single statement at 65,535 bound
  parameters, and one large ATS board can already return 500+ postings.
  Switching to `key = ANY(%s)` with a single list parameter removes the
  limit (and the dynamic SQL) in one line.

## Features

- **Auto-dedup engine for secondary sources
  ([#91](https://github.com/jasonkryst/CareerSpyder/issues/91)).** Compare
  jobs from secondary sources (Indeed, LinkedIn) against primary-source
  listings using title + company similarity scoring (e.g.
  `difflib.SequenceMatcher`) to produce low/medium/high confidence
  duplicate candidates. Manual duplicate marking (added in #82) provides
  the data model.
- **Official LinkedIn/Indeed APIs or RSS feeds (from design spec).** The
  current `linkedin`/`indeed` adapters are explicitly best-effort
  Playwright scraping of public search pages — fragile by nature (layout
  changes, blocking, CAPTCHAs). Neither currently offers a public
  job-search API, so this is likely blocked; revisit if that changes.
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
  extraction for supported platforms, and a filter UI control. A Lever-only first cut
  would be much smaller.
- **Digest subject line doesn't mention failures when jobs also exist
  (from review).** `app/digest.py::build_digest` only reflects the new-job
  count in the subject when there are new jobs, even if the same run also
  had source failures (e.g. it could read "5 new jobs, 2 sources failed").

## UI, UX & accessibility

- **Smaller UX/accessibility polish items (from audit).** No
  required-field indication on the source form (U5); the confirm-modal
  has no non-JS fallback, so Delete/Import submit with zero warning if JS
  is blocked (U6). See the audit for details.

## Testing & tooling

- **No settings-survives-a-restart test (from review).** `/settings`
  writes are covered unit-wise, but nothing simulates a container restart
  to confirm persisted settings actually reload correctly.
