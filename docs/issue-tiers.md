# Issue Tier List

Open GitHub issues ranked by **impact × complexity**. Work top-down; re-tier
when issues are opened/closed (see "Maintaining this list" at the bottom).

**Last reviewed:** 2026-09-22 (branch `fix/issue-tiers`, v1.4.0)

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
| 4 | [#91](https://github.com/jasonkryst/CareerSpyder/issues/91) | Auto-dedup engine for secondary sources | M | L |

### #91 — Auto-dedup engine · M / L
Useful if secondary sources (Indeed/LinkedIn) are a big share of the feed;
manual duplicate flagging (#82) covers it today. New table, similarity scoring,
review UI, tests — a multi-day feature. Deliberately kept out of the v1.4.0 fix
branch; brainstorm → spec → plan on its own branch before starting.

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
