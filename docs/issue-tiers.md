# Issue Tier List

Open GitHub issues ranked by **impact × complexity**. Work top-down; re-tier
when issues are opened/closed (see "Maintaining this list" at the bottom).

**Last reviewed:** 2026-10-22 (branch `docs/backlog-refresh`, v1.11.2)

## Rubric

| | Meaning |
|---|---|
| **Impact H** | Wrong/missing jobs or broken links for the user today, or a user-reported failure |
| **Impact M** | Reliability/latency problem that bites under load or on bad days |
| **Impact L** | Hygiene, diagnosability, or micro-optimization |
| **Effort XS** | < 1 hr, one file, obvious fix |
| **Effort S** | A few hours, one module + tests |
| **Effort M** | ~1 day, touches several modules |
| **Effort L** | Multi-day feature, schema + UI |

| Tier | Rule |
|---|---|
| **1 — Do next** | High impact, any effort ≤ M |
| **2 — Quick wins** | Low/medium impact, XS–S effort |
| **3 — Worth doing** | Medium impact, S–M effort |
| **4 — Backlog / reconsider** | Low impact or L effort, or premise needs re-checking |

## Open

| Tier | # | Title | Impact | Effort |
|---|---|---|---|---|
| 1 | [#240](https://github.com/jasonkryst/CareerSpyder/issues/240) | Pipeline security (match BookWheel #257 ruleset baseline) | H | XS |
| 1 | [#213](https://github.com/jasonkryst/CareerSpyder/issues/213) | Live run progress feedback during "Run now" | H | M |
| 2 | [#216](https://github.com/jasonkryst/CareerSpyder/issues/216) | Admin users page — per-user job and source counts | M | S |
| 2 | [#217](https://github.com/jasonkryst/CareerSpyder/issues/217) | Invite management — expiry date, resend, revoke | M | S |
| 2 | [#241](https://github.com/jasonkryst/CareerSpyder/issues/241) | "What's New" modal | L | S |
| 2 | [#226](https://github.com/jasonkryst/CareerSpyder/issues/226) | Digest — opt-in weekly check-in on clean runs | L | S |
| 3 | [#222](https://github.com/jasonkryst/CareerSpyder/issues/222) | Bulk job status update via multi-select | M | M |
| 3 | [#220](https://github.com/jasonkryst/CareerSpyder/issues/220) | Per-job notes field | M | M |
| 3 | [#221](https://github.com/jasonkryst/CareerSpyder/issues/221) | Settings import — diff/preview before commit | M | M |
| 4 | [#225](https://github.com/jasonkryst/CareerSpyder/issues/225) | Sources list — bulk enable/disable | L | M |
| 4 | [#91](https://github.com/jasonkryst/CareerSpyder/issues/91) | Auto-dedup engine for secondary sources | M | L |

Untracked limitations (no issue filed) live in [ROADMAP.md](../ROADMAP.md);
the cheapest of those — `db.get_new_jobs`' per-job bind parameters and the
digest subject ignoring failures — are XS and could ride along with any
Tier 2 PR.

### #240 — Pipeline security · H / XS
Mostly in place already: the active "Default Branch Protection" ruleset on
`master` requires `lint`, `typecheck`, `test`, `dependency-audit`,
`build-scan-smoketest`, `Analyze Python`, and `CodeQL`; blocks deletion and
force-push; and gates on CodeQL/Trivy code-scanning alerts (high or
higher). Remaining gaps vs. BookWheel #257: `integration-test` and
`trivy-fs` run in CI but aren't required checks; the admin role has
"always" bypass (decide and record whether that's intended); and a
disabled duplicate ruleset ("Protect Main") should be deleted. All repo
settings — no code change.

### #213 — Live run progress · H / M
Highest-impact open feature: a 30-source run can take minutes with no
feedback. Option B (polling `GET /run-status` JSON) fits the dashboard's
existing auto-refresh polling and e2e coverage better than SSE.

### #216, #217 — Admin page improvements · M / S
Both self-contained in `/users`; #216 is a query + two columns, #217 a
pending-invites section plus resend/revoke routes. Good to pair in one PR.

### #241 — "What's New" modal · L / S
Unlabeled. Likely shape: a dialog shown once per version change, fed from
CHANGELOG.md, last-seen version in `localStorage`. Mirror MyFinances #289.

### #226 — Weekly check-in · L / S
Strictly opt-in, so it doesn't violate AGENTS.md's "clean run stays
silent" constraint — but update that constraint's wording when it lands.

### #222, #220, #221 — Jobs/import workflow · M / M
#222 and #225 share a checkbox + bulk-toolbar pattern; build it once.
#221 needs a two-step flow with a session-held confirmation token.

### #225 — Bulk enable/disable sources · L / M
Labeled `complexity:low`, but needs an `enabled` flag on every source
model, an orchestrator skip, a migration, and new UI — re-scored to M.

### #91 — Auto-dedup engine · M / L
Useful if secondary sources (Indeed/LinkedIn) are a big share of the feed;
manual duplicate flagging (#82) covers it today. New table, similarity scoring,
review UI, tests — a multi-day feature. Deliberately kept out of the v1.4.0 fix
branch; brainstorm → spec → plan on its own branch before starting. The
scoring function can be built and unit-tested standalone first.

## Already shipped — close

| # | Title | Evidence |
|---|---|---|
| #223 | Job status select — AJAX save to preserve scroll position | `jobs.html`'s status `<select>` saves via `fetch()` with a toast and no `onchange` submit; covered by `tests/web/e2e/test_job_status.py`. |

## Resolved in v1.10.0 (`feat/quick-wins-phase2`)

| # | Title | Resolution |
|---|---|---|
| #218 | Keyword filters only match title | `apply_keyword_filters` now searches title, company, and location. |
| #215 | Dates shown as raw ISO strings | Added `\|timeago` Jinja2 filter; all date cells show relative time with ISO on hover. |
| #224 | No way to jump to a page | Jump-to-page form added to all paginated views (dashboard, jobs, sources) when total pages > 2. |
| #214 | Dashboard has no at-a-glance stats | Four stat cards (total jobs, new this week, sources, runs) added to dashboard header. |
| #219 | Run history doesn't show source counts | Runs now store `source_count`; table shows "N / M failed" with links to failed source edit pages. |

## Resolved in v1.9.0 (`feat/quick-wins-phase1`)

| # | Title | Resolution |
|---|---|---|
| #209 | No source health status visible | Health badges (ok/failed/never) added to sources list Last run column. |
| #210 | Platform detector doesn't focus name field | Auto-focuses Name input after platform pre-fill. |
| #211 | No way to test email settings | "Send test email" button on email settings page, rate-limited 3/10 min. |
| #212 | Keyword search only finds by title | Full-text ILIKE search on title + company wired to /jobs and /jobs/map. |

## Resolved in v1.4.0 (`fix/issue-tiers`)

| # | Title | Resolution |
|---|---|---|
| #175 | Workday job URLs 404 | Links include the career-site segment; `db.refresh_job_urls` heals existing rows each run. The 404 had also made the URL checker mark every Workday job removed. |
| #153 | RUMC Infor source failing | Root cause: one cold Chromium load per results page (20 for RUMC), ~25% of which hit a >15 s iframe render and were misdetected as v2. Now one browser session for all pages, a combined v1/v2 readiness wait (30 s), and one retry of the initial load. |
| #164 | TalentBrew silent under-scrape | Warning logged when `data-total-pages` is missing. |
| #166 | URL checker sequential under `_run_lock` | 8-worker thread pool with a 60 s overall deadline. |
| #167 | No Cache-Control on static assets | `max-age=604800` + `?v={{ app_version }}` cache-busting; manifest/offline page `no-cache`. |
| #165 | Cache `/jobs` filter data | Closed won't-fix: premise stale (sources are in Postgres, not `sources.json`), and the DISTINCT queries are sub-millisecond — caching only adds invalidation risk. |
| #163, #162, #161 | board_token encoding, preview semaphore, import size cap | Already fixed in PR #186; closed by the v1.4.0 PR. |
| #159, #158 | Malformed-record isolation, reactivated-job digest | Already fixed in PR #168; closed by the v1.4.0 PR. |

## Maintaining this list

- When an issue closes, move it off the table.
- New issues: score Impact + Effort with the rubric, drop into the matching tier.
- Re-verify "Tier 4 premise" notes against master when re-reviewing — code moves
  under issues.
- Use `Closes #N` in PR bodies so issues close on merge and don't linger here.
- Bump **Last reviewed** each pass.
