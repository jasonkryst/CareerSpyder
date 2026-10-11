# CareerSpyder feature audit — 2026-10-11

**Scope:** Feature completeness and usability audit of the full application
as of `v1.8.0`. Focused on *what the app can do versus what a power user
needs*, separate from prior security/a11y/testing audits.

**Method:** Static code review of all routes, templates, models, and
adapters; cross-referenced against ROADMAP.md, all prior audit docs
(2026-08-19, 2026-09-04-*), and the complete GitHub issue history. Only
findings not already tracked in open issues or ROADMAP are included here.

**Not re-raised:** Items already in ROADMAP.md (employment type, SMTP 465,
missed-run catch-up, SQLite param cap, auto-dedup engine) or in open issues
(#91). Prior security findings (SSRF, CSRF, upload limits, preview
semaphore) were fully resolved in v1.5–v1.7 and are not repeated.

---

## Summary

| Area | Impact | Complexity | GH issue |
|---|---|---|---|
| Source health stats on sources list | High | Low | #209 |
| Platform detector: auto-fill source form on detection | High | Low | #210 |
| "Send test email" button in email settings | High | Low | #211 |
| Full-text keyword search on jobs list | High | Low | #212 |
| Live "Run now" progress feedback | High | Medium | #213 |
| Dashboard summary stat cards | Medium | Medium | #214 |
| Human-friendly relative dates in jobs table | Medium | Low | #215 |
| Admin users page: per-user job/source counts | Medium | Low | #216 |
| Invite management: show expiry + admin resend | Medium | Low | #217 |
| Keyword filters: also match company and location | Medium | Low | #218 |
| Run history: source attempt/failure ratio column | Medium | Low | #219 |
| Job notes field | Medium | Medium | #220 |
| Settings import: diff preview before commit | Medium | Medium | #221 |
| Bulk job status update via multi-select | Medium | Medium | #222 |
| Status dropdown: AJAX save to preserve scroll position | Medium | Medium | #223 |
| Pagination: jump-to-page input | Low | Low | #224 |
| Sources: bulk enable/disable | Low | Low | #225 |
| Digest: weekly check-in even on clean runs | Low | Low | #226 |

---

## Feature-by-feature analysis

### Jobs list (`/jobs`)

**Current capabilities:**
- Rich filter bar: company text, multi-select source/state/status, location
  dropdown, zip+radius geocode, emailed, duplicates, admin user filter
- Sortable columns, paginated (25/page)
- Per-row status select, location override, duplicate marking, manual remove
- Map view toggle, status history details expand
- Secondary-source badge

**Gaps:**
- No free-text search across titles — users must know the exact company name
  to filter; there is no way to search "engineer" across all companies
- Dates display raw ISO-8601 ("2026-10-08T14:32:00+00:00") — no relative
  or formatted date, making recency hard to scan
- No job-level annotation/notes field — users can set a status but cannot
  record "interviewed 10/5" or "recruiter called" alongside it
- Status `<select>` uses `onchange="this.form.submit()"`, causing a full
  page reload and loss of scroll position on every status change (carried
  forward from a11y audit finding A1, not yet filed as an issue)
- Bulk actions require individual row operations — no multi-select to set
  status on 10 "not interested" rows at once
- Keyword filters match only `title` (see `app/filters.py`) — a job at
  "Google" for "engineer" could slip through an include filter if the title
  alone doesn't match

### Dashboard (`/`)

**Current capabilities:**
- Run history table with sort, filter by failures/clean, pagination
- Run Now + Check URLs buttons with rate limiting
- Refresh button for async row reload

**Gaps:**
- No summary stat cards — user must scan the table to know "how many active
  jobs do I have?" or "when did I last get new results?"
- "Run now" returns immediately (background task) with no indication of
  which source is currently being scraped or how far along the run is;
  the only feedback is the table refreshing after completion

### Sources (`/sources`, `/sources/new`, `/sources/{id}/edit`)

**Current capabilities:**
- CRUD with type-switching form, keyword filters per source
- Test-preview (Playwright-gated), platform detector
- Sort by name/type/company, filter by type, paginated

**Gaps:**
- Sources list shows name/type/company only — no indication whether the
  source succeeded or failed on the last run; a user with 30 sources has
  no way to see which ones are consistently failing without checking
  individual run history records
- Platform detector successfully identifies a platform but requires the
  user to manually copy the result into the Add Source form — the natural
  next step (auto-populate fields) is missing
- No bulk enable/disable — users with many sources cannot pause a group
  (e.g., "pause all LinkedIn sources while I travel")

### Email / Digest

**Current capabilities:**
- Per-user SMTP settings (admin-only), per-user recipient list (up to 5),
  day-of-week schedule, per-company cap, exclude-by-status, resend option
- Digest groups jobs by company, omits clean+no-failure runs

**Gaps:**
- No "send test email" button — verifying SMTP config requires waiting for
  a scheduled run or manually triggering Run Now
- No weekly check-in option for clean runs — users who want a "nothing new
  this week" confirmation on quiet weeks have no opt-in for it

### Settings (`/settings/*`)

**Current capabilities:**
- Email settings (admin), preferences (days, recipients, caps, exclusions),
  data (export/import/clear cache), account (password change)
- Import validates against SourcesFile model before writing

**Gaps:**
- Import shows no diff before committing — replacing 40 sources with 35
  from a JSON backup happens silently with only "Imported 35 source(s)"
  as feedback; no preview of what's being added, updated, or removed
- No dry-run/preview for preferences import either

### User management (`/users`)

**Current capabilities:**
- Invite via link (token-based), deactivate, list all users (admin)

**Gaps:**
- Invite list shows email but no expiry timestamp — admins cannot tell
  whether a pending invite has expired without checking the DB
- No resend/regenerate invite action — if a link expires or is lost, admin
  must deactivate the invite (no UI for this) and create a new one
- Users list shows no per-user stats (how many sources, how many jobs) —
  admin cannot gauge which accounts are active

### Run history (`/`)

**Current capabilities:**
- Timestamp, new job count, failed source names per run

**Gaps:**
- No column showing how many sources were attempted vs. how many failed —
  "3 failed" means something different when there are 5 total vs. 50 total
- No inline link from a failed source name to that source's edit page

### Pagination (cross-cutting)

**Current capabilities:**
- Previous/Next links with "Page N of M"

**Gaps:**
- No jump-to-page input — navigating to page 15 of a large job list
  requires 14 consecutive "Next" clicks

---

## Cross-cutting observations

1. **Source ↔ run ↔ job linkage is one-directional.** You can see which
   source produced a job (source_name column), but from a source's edit
   page you cannot see the jobs it produced or its run history. This
   makes diagnosing a misconfigured source harder than it needs to be.

2. **Keyword filtering is title-only.** `app/filters.py::apply_keyword_filters`
   checks only `j.title.lower()`. A job titled "Software Engineer" at
   "Google" passes a `["Google"]` include filter only by accident if the
   title mentions the company. Expanding to company + location is a
   one-line change but affects dedup semantics if extended to the DB layer.

3. **Status change is the most frequent user action and the most disruptive
   to UX** (full reload, scroll loss). It's isolated to a single form +
   route, making an AJAX upgrade straightforward.

4. **Platform detector closes a key friction gap** for adding sources, but
   stops one step short of the goal: auto-populating the form. The
   detection result already returns `platform_type` and `fields` — the
   routing logic to fill the form is already three-quarters done.

---

*Generated by feature audit pass, 2026-10-11. Issues filed: #209–#226.*
