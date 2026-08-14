# Settings Page Tabs (Email / Data) — Design Spec

Date: 2026-08-13
Status: Approved for planning

## Purpose

GitHub issue #14 asks for the Settings page to grow tabs: an **Email**
tab (today's only content — SMTP host/port/from/to) and a **Data** tab
with two admin actions:

- **Cache clear** of identified jobs — empty the dedup store so the next
  scrape treats every currently-known job as new again.
- **Import and export of sources** — download the current `sources.json`
  as a file, and upload a file to replace it.

## Current state

`/settings` is a single `GET`/`POST` route pair in `routes_settings.py`
rendering `templates/settings.html`, an SMTP form only. There is no tab
concept anywhere in the app yet — the closest precedent is the main
`<nav aria-label="Main">` in `base.html`, which is plain server-rendered
links with `aria-current="page"` computed from `request.url.path`, no
JS. The app has no flash-message or session infrastructure; the one
existing "tell the user something happened" pattern is `source_form.html`
re-rendering an inline `{% if error %}` block on a failed `POST`.

## Decision: tabs are routes, not client-side toggles

Consistent with this app's explicit no-SPA/no-JS-build design (see
`docs/superpowers/specs/2026-08-13-enhanced-fed-ui-design.md`), each tab
is its own full-page-reload route rather than a JS-toggled panel:
`/settings/email` and `/settings/data`, sharing a small tab-nav partial.
`/settings` redirects to `/settings/email` so the existing bookmark/link
keeps working.

## Routes (`app/web/routes_settings.py`, one router, unchanged file scope)

| Method | Path | Behavior |
|---|---|---|
| GET | `/settings` | Redirect to `/settings/email` |
| GET | `/settings/email` | Renders the SMTP form (today's `show_settings`, moved) |
| POST | `/settings/email` | Today's `save_settings` logic, unchanged; redirects to `/settings/email` |
| GET | `/settings/data` | Renders Data tab. Reads `?cleared=1` / `?imported=N` query params to show a success banner |
| POST | `/settings/data/clear-cache` | Calls `db.clear_jobs(conn)`; redirects to `/settings/data?cleared=1` (303) |
| GET | `/settings/data/sources/export` | Streams the current sources as a downloadable JSON file (`sources.json`, `application/json`) |
| POST | `/settings/data/sources/import` | Validates and replaces `sources.json` from an uploaded file. Success → redirect to `/settings/data?imported=N` (303). Failure → re-render the Data tab with an inline error, HTTP 400, `sources.json` left untouched |

## Backend changes

`app/db.py`:
- `clear_jobs(conn: sqlite3.Connection) -> None` — `DELETE FROM jobs`,
  then `commit()`. Idempotent on an already-empty table. Does not touch
  `runs` or `settings` — "identified jobs" maps precisely to the `jobs`
  table (README already describes it as "seen-before keys"); run history
  is untouched.

`app/config.py`, reusing the existing pydantic `SourceConfig`/`SourcesFile`
models rather than introducing a parallel schema:
- `export_sources_json(path: str) -> str` — loads sources via the
  existing `load_sources`, serializes them with the same
  `{"sources": [s.model_dump() for s in sources]}` shape `save_sources`
  already writes, returns the JSON string. A missing `sources.json`
  exports `{"sources": []}`, matching `load_sources`'s existing
  missing-file-is-empty-list behavior.
- `import_sources_json(path: str, raw: bytes) -> list[SourceConfig]` —
  `json.loads(raw)` → `SourcesFile.model_validate(...)` → `save_sources`.
  Raises `json.JSONDecodeError` on unparseable input and
  `pydantic.ValidationError` on a well-formed-but-invalid payload (missing
  `"sources"` key, unknown `type`, or any per-type validation failure such
  as a blank `board_token`). Both exceptions propagate to the caller
  un-caught — the route is responsible for turning them into a 400.
  `save_sources` (and therefore the file on disk) is only reached after
  validation succeeds, so a rejected import can't partially write.

## Templates

- `templates/settings_tabs.html` — new shared partial: two links,
  **Email** (`/settings/email`) and **Data** (`/settings/data`), with
  `aria-current="page"` on whichever matches `request.url.path`. Same
  shape as the existing main nav, just a second-level one.
- `templates/settings_email.html` — today's `settings.html` content,
  `{% include "settings_tabs.html" %}` added above the `<h1>`. The `POST`
  target changes from `/settings` to `/settings/email`.
- `templates/settings_data.html` — new:
  - Success banner (`.success` class) shown when `cleared` or `imported`
    is present in the query string.
  - Inline `.error` block (existing class, same pattern as
    `source_form.html`) shown when the last import failed.
  - Clear-cache: a single `<form method="post" action="/settings/data/clear-cache">`
    with one submit button — no confirm dialog, consistent with
    `Delete source` on `/sources` today, which is also an unconfirmed
    plain submit.
  - Export: `<a href="/settings/data/sources/export">Export sources</a>`.
  - Import: `<form method="post" action="/settings/data/sources/import" enctype="multipart/form-data">`
    with a `<input type="file" name="file">` and a submit button.
- `templates/base.html`: the `Settings` nav link's active-state check
  changes from `request.url.path == "/settings"` to
  `request.url.path.startswith("/settings")`, matching how the `Sources`
  link already checks `startswith("/sources")`.
- `static/style.css`: new `.success` rule, same shape as the existing
  `.error` rule but using the accent color instead of the error color
  (no new custom properties needed — `--accent`/`--accent-fg` already
  exist).

## Error handling / edge cases

- Import with no file chosen, an empty file, non-JSON bytes, valid JSON
  missing `"sources"`, or a source failing its own type's validation →
  all land as the same inline error block, HTTP 400, file on disk
  untouched.
- Export when `sources.json` doesn't exist yet → downloads `{"sources": []}`
  rather than 404ing, matching `load_sources`'s existing behavior.
- Clear-cache on an empty `jobs` table → no error, redirects with the
  success banner same as a non-empty clear.
- No new authentication/authorization — matches the rest of the app
  (ROADMAP.md already tracks "no auth" as a known v1 gap, not something
  this issue changes).

## Testing

TDD per `AGENTS.md` (failing test before implementation), extending
existing files rather than adding new ones (Settings stays one route
group):

`tests/test_db.py`:
- `clear_jobs` empties a populated `jobs` table (positive).
- A job seen before `clear_jobs` is reported "new" again afterward —
  the actual behavioral point of the feature (positive).
- `clear_jobs` on an already-empty table doesn't raise (negative/edge).

`tests/test_config.py`:
- `export_sources_json` returns the saved sources round-tripped through
  `load_sources`'s shape (positive).
- `export_sources_json` on a missing file returns `{"sources": []}`
  (positive/edge).
- `import_sources_json` replaces an existing source list and the change
  is visible via `load_sources` (positive).
- `import_sources_json` rejects non-JSON bytes, raising
  `json.JSONDecodeError`, file unchanged (negative).
- `import_sources_json` rejects JSON missing `"sources"`, raising
  `ValidationError`, file unchanged (negative).
- `import_sources_json` rejects a source with an unknown `type`
  (negative).
- `import_sources_json` rejects a source failing its own type's
  validation, e.g. blank `board_token` (negative).

`tests/web/test_settings.py` (extended, existing SMTP tests updated to
target `/settings/email`):
- `GET /settings` redirects to `/settings/email` (positive).
- Email GET shows current values / hides the password field, POST saves
  — same assertions as today, against the new path (positive, migrated).
- `GET /settings/data` renders the Clear-cache form, Export link, and
  Import form (positive).
- `POST /settings/data/clear-cache` empties `jobs` and redirects to
  `/settings/data?cleared=1` (positive).
- `GET /settings/data/sources/export` returns the current sources as a
  JSON body with an `attachment` `Content-Disposition` (positive).
- `POST /settings/data/sources/import` with a valid file replaces sources
  and redirects to `/settings/data?imported=N` with the right count
  (positive).
- `POST /settings/data/sources/import` with invalid JSON returns 400 with
  an inline error, sources unchanged (negative).
- `POST /settings/data/sources/import` with a schema-invalid payload
  (unknown `type`) returns 400, sources unchanged (negative).
- `POST /settings/data/sources/import` with no file field returns 400
  (negative).

`tests/web/e2e/`: extend the existing keyboard-tab-order test to also
cover the Email/Data tab-nav links (already asserts on nav semantics
app-wide).

## Docs

- `README.md`: new Features bullet for the Data tab; Web UI table split
  into `/settings/email` and `/settings/data` rows, with the re-digest
  consequence of clearing the cache called out explicitly; Project
  structure template list updated.
- `CHANGELOG.md`: `[Unreleased]` entry for GH #14.
- `AGENTS.md`: Web UI module-responsibility line updated to mention
  `/settings/data`.

## Explicitly out of scope for this iteration

- **Per-source cache clear.** The issue asks for "cache clear of
  identified jobs" with no per-source scoping; a global clear is the
  literal reading and the simpler mechanism. Per-source clearing can be
  added later if wanted.
- **Confirmation dialog / typed-confirmation guard on cache clear.**
  Matches the existing unconfirmed-delete precedent on `/sources`; the
  re-digest consequence is documented instead of gated.
- **Merge-on-import.** Import replaces the whole source list (a clean
  export → edit → re-import round trip); merge-by-id semantics can be
  added later if the replace behavior proves too blunt in practice.
- **Backup-before-overwrite on import.** `save_sources` already writes
  atomically (temp file + `os.replace`), which prevents corruption but
  not data loss from a bad import — not addressed here, same posture as
  the rest of `sources.json` today.
- **Authentication.** Already tracked in ROADMAP.md, unrelated to this
  issue.
