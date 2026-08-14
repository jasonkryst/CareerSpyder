# Preferences — Email Frequency, Resend, Multiple Recipients — Design Spec

Date: 2026-08-14
Status: Approved for planning

## Purpose

Give users control, from the Preferences tab, over three aspects of the
daily digest email that are currently hardcoded or single-valued:

1. **Which days of the week** the app checks for jobs and emails a digest
   (today: every day, fixed at `RUN_HOUR`, no day-of-week concept).
2. **Whether a job is resent** in later digests while it's still listed,
   or emailed exactly once, ever (today: always exactly once — a job is
   recorded in `jobs` the first time it's seen and is excluded from every
   digest after that).
3. **Multiple recipient addresses** for the digest (today: `email_to` is
   a single string, used as the sole SMTP recipient).

This supersedes the "server-stored preferences" exclusion in
`2026-08-14-modernized-theme-preferences-design.md`, which scoped that
pass to visual-only, client-side (localStorage) theme control. That
scope decision stands for theme; this spec adds the first
server-persisted preferences alongside it on the same tab.

## Current state

- `app/scheduler.py::create_scheduler` registers one APScheduler cron
  job at a fixed `hour=run_hour`, no `day_of_week`. `run_and_notify`
  always scans and, if there are new jobs or failures, always emails.
- `app/orchestrator.py::run_once` computes `deduped_jobs` (everything
  found this run, after keyword filtering) and `new_jobs` (the subset
  not already in the `jobs` table via `db.get_new_jobs`). Only
  `new_jobs` is returned on `RunSummary`; `deduped_jobs` is discarded
  after `db.save_jobs` records it for future dedup.
- `app/digest.py::build_digest` takes `new_jobs` and always titles the
  email `"CareerSpyder: N new job(s)"`.
- `app/emailer.py::send_email` takes `email_to: str`, sets it as both
  the `To` header and the sole `sendmail` recipient.
- `app/db.py` settings table has no frequency/resend columns;
  `email_to` is a single `TEXT` value both in schema and everywhere
  it's read/written (`get_settings`, `save_settings`,
  `seed_settings_if_empty`).
- `app/web/templates/settings_email.html` has the current "To address"
  input, on the Email tab, next to SMTP host/port/user/from.
  `app/web/templates/settings_preferences.html` currently holds only
  the Theme radio group, no form/POST route.
- No migration mechanism exists (`db.SCHEMA` is `CREATE TABLE IF NOT
  EXISTS` only); every existing deployment's `settings` table already
  exists without the new columns.

## Data model

`app/db.py`: three new `settings` columns, applied via `ALTER TABLE`
statements run at `init_db` time (guarded so re-running against a
database that already has them is a no-op):

- `email_days TEXT NOT NULL DEFAULT 'mon,tue,wed,thu,fri,sat,sun'` —
  comma-separated lowercase 3-letter day codes. Default is all seven,
  so existing deployments keep today's "runs every day" behavior with
  no action required.
- `resend_jobs INTEGER NOT NULL DEFAULT 0` — 0/1. Default off preserves
  today's "send once" behavior.
- `email_to` — unchanged column, but now holds a comma-separated list
  (e.g. `"a@x.com,b@y.com"`) instead of a single address. A single
  existing address round-trips unchanged (it's just a 1-item list).

`get_settings`/`save_settings`/`seed_settings_if_empty` extend to
include `email_days` and `resend_jobs` (typed `bool` at the Python
layer, stored as `0`/`1`).

## Preferences page

`app/web/templates/settings_preferences.html` becomes a form
(`POST /settings/preferences`), Theme radios unchanged, with two new
`<fieldset>` sections plus the recipients list below them:

- **Check days**: 7 checkboxes, `name="email_days"`, `value` one of
  `mon`..`sun`, labeled Mon–Sun, pre-checked per the stored setting.
- **Resend jobs**: one checkbox, `name="resend_jobs"`, labeled "Keep
  sending a job in each digest until it's no longer listed."
- **Recipients**: repeatable rows — an `<input type="email"
  name="email_to">` plus a "Remove" button per row, seeded from the
  stored comma-separated list (one row per address, minimum one empty
  row if none stored), and an "Add another" button below the rows.
  Row add/remove is handled client-side by a new
  `app/web/static/preferences.js`, in the same plain-vanilla-JS style
  as the existing `theme.js` (clone a hidden `<template>` row, wire its
  remove button; the "Add another" button clones and appends). No
  build step, no new dependency.

A single "Save" button submits Check days, Resend, and Recipients
together (Theme stays separate/instant via existing JS, unaffected).

`app/web/routes_settings.py`:
- `GET /settings/preferences` passes `settings` into the template
  (currently passes nothing).
- `POST /settings/preferences` (new): reads `email_days` via
  `form.getlist("email_days")` (joined to CSV), `resend_jobs` via
  `"resend_jobs" in form`, `email_to` via `form.getlist("email_to")`
  (blank-filtered, joined to CSV), and calls a new
  `db.save_preferences(conn, email_days, resend_jobs, email_to)` —
  kept separate from `db.save_settings` (SMTP transport fields) since
  the two forms now save independently. Redirects back to
  `/settings/preferences`.

`app/web/templates/settings_email.html`: the "To address" field and
its `email_to` handling are removed; that tab keeps only SMTP host,
port, user, and From address. `save_settings`'s signature drops
`email_to`.

## Scheduler: day-of-week gating

`app/scheduler.py::run_and_notify` reads `settings["email_days"]` (via
`db.get_settings`) as its first step, before running the scan. It
computes today's 3-letter weekday code in the scheduler's configured
`tz` and returns immediately — no scan, no email — if that code isn't
in the stored list. This is a runtime check inside the existing daily
cron job (which keeps firing at `run_hour` every day) rather than
reconfiguring APScheduler's `day_of_week` trigger, so a Preferences
change takes effect on the next scheduled run without an app restart.
If `settings` is `None` (never configured), behavior is unchanged from
today: log and skip.

## Resend behavior

`app/orchestrator.py`: `RunSummary` gains `found_jobs: list[Job]` —
the existing `deduped_jobs` value (everything found this run, after
keyword filtering, before the "already in `jobs` table" check), now
surfaced instead of discarded. `new_jobs` and the `db.save_jobs`
history write are unchanged.

`app/scheduler.py::run_and_notify`: after the day check passes and the
run completes, it picks which list to email based on
`settings["resend_jobs"]`:
- off (default): `summary.new_jobs`, same as today.
- on: `summary.found_jobs` — every currently-listed matching job, so
  one still open next run appears in the next digest too, and one no
  longer found (closed/removed) naturally drops out.

`app/digest.py::build_digest`'s subject changes from the hardcoded
`f"CareerSpyder: {len(new_jobs)} new job(s)"` to a subject built by the
caller-aware label: when the list passed in is a resend batch it should
not claim everything is "new." Simplest fix that keeps `build_digest`
ignorant of the resend concept: `run_and_notify` computes the label
(`"new job"` vs `"job"`) and passes it as a `build_digest` parameter
alongside the job list.

## Multiple recipients

`app/emailer.py::send_email`'s `email_to` parameter becomes
`list[str]`. `msg["To"]` is set to `", ".join(email_to)` for the
header; `server.sendmail(email_from, email_to, msg.as_string())` passes
the actual list so every address is an SMTP envelope recipient (not
just the header).

`app/scheduler.py::run_and_notify` splits `settings["email_to"]` on
`","` (stripping blanks) before calling `send_email`.

## Testing

Extends existing files, no new ones, following this repo's existing
per-module test layout:

`tests/test_db.py`: settings round-trip covers `email_days`,
`resend_jobs`, and multi-address `email_to`; a test seeds a database
without the new columns (simulating an existing deployment) and
confirms `init_db` adds them without error and without disturbing
existing rows.

`tests/test_scheduler.py`: a run on a day not in `email_days` performs
no scan and sends no email; a run on a listed day behaves as today;
resend-on includes a still-listed previously-seen job in the digest,
resend-off excludes it; multiple `email_to` addresses are all passed to
`send_email`.

`tests/test_emailer.py`: `send_email` with a multi-item list sets a
comma-joined `To` header and passes the full list to `sendmail`.

`tests/test_orchestrator.py` (existing file, if present — otherwise
inline in the scheduler tests): `RunSummary.found_jobs` contains all
filtered jobs from the run, including ones already known.

`tests/web/test_settings.py`: `POST /settings/preferences` persists
check days, resend, and a multi-row recipient list; `GET` prefills the
form from stored settings; `settings_email.html` no longer renders a
"To address" field.

## Explicitly out of scope for this iteration

- **A separate "resend window" (e.g. resend for N days only).**
  Discussed and deferred in favor of the simpler "resend while still
  listed" semantics, which needs no new counter/expiry state.
- **Per-recipient controls** (e.g. some recipients get resends, others
  don't, or different days per recipient). One shared frequency/resend
  policy for the whole digest.
- **Email address validation beyond blank-filtering.** Matches this
  codebase's existing precedent (`include_keywords`/`exclude_keywords`
  in `source_form.py` are similarly unvalidated free text).
- **Rescheduling APScheduler's cron trigger itself.** The daily job
  keeps firing every day; day selection is enforced inside the job
  body, not via `day_of_week` on the trigger.
- **Changing `RUN_HOUR`/timezone configuration**, which stays an
  environment variable, untouched by this spec.
