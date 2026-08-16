# Settings Import/Export — Data + Preferences — Design Spec

Date: 2026-08-16
Status: Approved for planning

## Purpose

Closes GH #29. Today's `/settings/data` export/import (`GET/POST
/settings/data/sources/*`) only round-trips the source list
(`sources.json`). Preferences-tab settings (which days to check/email,
whether jobs resend, digest recipients) have no export/import path at
all — moving to a new deployment or restoring after a wipe means
re-entering them by hand. This spec extends the existing export/import
to also cover those Preferences-tab settings, in the same file.

Explicitly excluded: **theme** (client-side `localStorage` only,
nothing server-side to export — see
`2026-08-14-modernized-theme-preferences-design.md`), **Email-tab SMTP
settings** (`smtp_host`/`smtp_port`/`smtp_user`/`email_from` — per
issue wording, which names only the Data and Preferences tabs), and the
**job-cache-clear action** (a one-shot action, not persisted data).

## Current state

- `app/config.py::export_sources_json`/`import_sources_json` read/write
  `{"sources": [...]}` against the sources JSON file. `SourcesFile` is a
  plain `pydantic.BaseModel` with a single `sources` field and default
  (`ignore`) extra-field behavior — confirmed by hand that an unknown
  top-level `preferences` key in the input is silently dropped by
  `SourcesFile.model_validate`, so today's import function already
  tolerates a combined payload without modification.
- `app/web/routes_settings.py` exposes `GET
  /settings/data/sources/export` and `POST
  /settings/data/sources/import`, calling those two `config` functions
  directly. Both are referenced by URL in `settings_data.html` and by
  ~9 assertions in `tests/web/test_settings.py`.
- Preferences live in the `settings` SQLite table
  (`app/db.py::get_settings`/`save_preferences`) as `email_days` (CSV of
  3-letter day codes), `resend_jobs` (0/1), `email_to` (CSV of
  addresses) — the same three fields `POST /settings/preferences`
  already reads from form data via `DAY_CODES`-filtered
  `form.getlist(...)`.

## Payload shape

```json
{
  "sources": [ ... unchanged ... ],
  "preferences": {
    "email_days": ["mon", "wed", "fri"],
    "resend_jobs": false,
    "email_to": ["a@x.test", "b@x.test"]
  }
}
```

`email_days`/`email_to` are JSON arrays, not the DB's internal CSV
strings — matches how the Preferences form already submits/displays
them and is more readable in a hand-edited file. `preferences` is
optional on import (see below); always present on export.

## Routes

`app/web/routes_settings.py`, renamed from `.../sources/export` and
`.../sources/import` to `/settings/data/export` and
`/settings/data/import` (no longer sources-only, so the URL drops
`sources`):

- `GET /settings/data/export`: `sources = config.load_sources(...)`,
  `settings = db.get_settings(...)`, builds the combined payload above
  (empty-list/`False` defaults when `settings` is `None`), returns it
  as an `application/json` attachment named `settings.json` (was
  `sources.json`).
- `POST /settings/data/import`: calls `config.import_sources_json(path,
  raw)` first, unchanged — this keeps today's strict behavior for the
  sources half (bad JSON or invalid source shape still 400s via the
  same `except (json.JSONDecodeError, ValidationError)` handling, and
  leaves the sources file untouched on failure). On success, re-parses
  the same `raw` bytes (already proven valid JSON by the call above) to
  read `data.get("preferences")`:
  - **absent**: stored preferences untouched.
  - **present**: `email_days` intersected with `DAY_CODES` (unknown
    values dropped, same as the form handler), `resend_jobs` coerced
    via `bool(...)`, `email_to` filtered to non-blank strings — then
    `db.save_preferences(conn, email_days_csv, resend_jobs,
    email_to_csv)`. Non-list/wrong-type sub-fields degrade to their
    empty/`False` default rather than raising, so a hand-edited file
    with a slightly-off `preferences` block doesn't 400 the whole
    import (the sources half already succeeded by this point).
  - Redirects to `/settings/data?imported=<n>[&preferences=1]`, `n`
    being the source count as today.

## Template

`settings_data.html`: the "Sources" card is relabeled to reflect the
wider scope (e.g. "Export/Import settings" heading, updated href/action
to the renamed routes). Success banner extends: when the
`preferences=1` query param is present, appends "and preferences" to
the existing "Imported N source(s)" message.

## Testing

`tests/web/test_settings.py`: update the ~9 existing assertions that
hardcode `/settings/data/sources/export`/`/settings/data/sources/import`
and the sources-only export payload equality to the new paths and
combined shape. Add:

- export includes a `preferences` object matching stored
  `email_days`/`resend_jobs`/`email_to`.
- import with a `preferences` block present overwrites stored
  preferences (verified via `db.get_settings`).
- import with `preferences` absent leaves previously-stored preferences
  unchanged.
- import with a malformed `preferences` block (e.g. `email_days` as a
  string, not a list) still 400-free — sources import succeeds and
  preferences fall back to defaults, not a crash.

`tests/test_config.py`: no changes expected —
`export_sources_json`/`import_sources_json` keep their existing
sources-only contract; the combined payload is assembled/parsed one
layer up in `routes_settings.py`.

## Explicitly out of scope

- Theme (client-only, nothing to export).
- Email-tab SMTP settings (`smtp_host`/`smtp_port`/`smtp_user`/`email_from`).
- The job-cache-clear action.
- A versioned/migrating export format — this is a single-deployment
  personal tool; the new shape is the only shape going forward, same as
  every other unversioned schema change in this codebase.
