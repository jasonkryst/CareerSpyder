# Usage Guide

A walkthrough of CareerSpyder's web UI, plus example configuration values
for every source type. For architecture and full configuration reference,
see [README.md](../README.md).

## Getting started

1. Open the web UI and go to **Sources**.
2. Click **Add source**, pick a **Type**, and fill in its fields — see
   [Source types & examples](#source-types--examples) below for example
   values.
3. Click **Test this source** to preview the jobs it currently finds
   before saving.
4. Click **Save**.
5. Go to the **Dashboard** and click **Run now** to trigger an immediate
   scrape.
6. Check the **Dashboard**'s run table for the result, the **Jobs** page
   for the postings themselves, or wait for the digest email if new jobs
   were found.

After that, CareerSpyder scrapes automatically once a day at the
configured hour — no further action needed unless you're adding more
sources or changing settings.

## Web UI tour

Every save, update, or delete action across these pages shows a brief
toast confirmation in the top-right corner. Dates are stored as UTC but
displayed in your browser's local timezone.

| Page | Purpose |
|---|---|
| Dashboard (`/`) | A **Run now** button (always triggers an immediate scrape, regardless of configured check days) at the top, plus a paginated, sortable table of past runs — start/finish time, new job count, failed source names — filterable by whether a run had failed sources. A **Refresh** button re-fetches the latest rows, and the page auto-refreshes itself every 10 seconds while a run is still in progress. |
| Jobs (`/jobs`) | Every job ever found — company, search name, title/link (opens in a new tab), location, dates found/removed, age, emailed status, status (Applied/Ignored/Accepted/Rejected, with a per-job change history), and a summary where available. Sortable by company, title, date found, or age; filterable by company, source, removed/emailed status, and status. |
| Sources (`/sources`) | Sortable (name/type/company) and type-filterable table of configured sources with Edit/Delete actions (delete asks for confirmation via a themed dialog) and an **Add source** button. |
| Settings → Email (`/settings/email`) | SMTP host/port/from address (the password is a container env var, not editable here). |
| Settings → Data (`/settings/data`) | Clear the job dedup cache, and export/import `sources.json`. Importing asks for confirmation via a themed dialog before replacing the source list. |
| Settings → Preferences (`/settings/preferences`) | Theme, which days to check for jobs, resend behavior, and digest recipients (validated email addresses). |

This app also has an in-app copy of this page at `/guide`, one click from
any page's nav bar.

On narrow screens (phones, small tablets) the main menu collapses
behind a menu button in the header, and tables switch from a
horizontally-scrolling grid to a stacked card layout — tap the button
to open the menu, and scroll normally to read table rows.

## Source types & examples

Every source has a **Type** that determines which other fields are
required.

### greenhouse

Calls Greenhouse's public JSON board API directly. Requires the token
from the ATS's board URL (`boards.greenhouse.io/<board_token>`).

**Example:** `board_token: "acme"`

### lever

Calls Lever's public JSON board API directly. Same shape as `greenhouse`.

**Example:** `board_token: "beta"`

### generic_html

Fetches any careers page via plain HTTP (or a headless-Chromium render
when the page needs JavaScript) and extracts listings with CSS selectors
you define.

**Example:**
- `url: "https://customco.com/careers?q=backend+engineer"`
- `render_js: false` (set `true` if the page needs JavaScript to populate
  listings)
- `selectors.job_card: ".job-listing"`
- `selectors.title: ".job-title"`
- `selectors.link: "a.job-link"`
- `selectors.location: ".job-location"` (optional)

### linkedin

Best-effort, Playwright-based scraping of a public LinkedIn job search
results page. Fragile by nature (blocking, layout changes, CAPTCHAs);
isolated so its breakage never affects other sources.

**Example:** `url: "https://www.linkedin.com/jobs/search/?keywords=backend+engineer&f_WT=2"`

### indeed

Best-effort, Playwright-based scraping of a public Indeed job search
results page. Same caveats as `linkedin`.

**Example:** `url: "https://www.indeed.com/jobs?q=backend+engineer&sc=0kf%3Aattr%28DSQF7%29%3B"`

### infor

For employers on Infor's Global HR / CandidateSelfService platform.
There's no per-job link on this platform, so the digest links to the
listing page itself.

**Example:**
- `url: "https://careers.example.com/go/All-Jobs/12345/"` (the full
  listing page URL)
- `max_pages: 3` (default; bounds how many result pages are crawled per
  run)

### healthcaresource

For employers on the HealthcareSource/symplr talent platform (e.g.
`pm.healthcaresource.com/CS/<site_id>`). Calls a directly-callable JSON
API — no browser needed.

**Example:** `site_id: "rcmc"`

### talentbrew

For employers on Radancy's TalentBrew career-site platform (e.g.
`jobs.nm.org`). `base_url` is just the site's origin.

**Example:**
- `base_url: "https://jobs.nm.org"`
- `max_pages: 60` (default safety cap)

### workday

For employers on Workday's recruiting platform — works identically for
any Workday tenant. No auth, no browser needed.

**Example:**
- `career_site_url: "https://dulyhealthandcare.wd1.myworkdayjobs.com/Duly"`
- `max_pages: 60` (default)

### phenompeople

For employers on Phenom People's "CareerConnect" career-site platform
(e.g. `jobs.ascension.org`). No cookies, CSRF token, or tenant ID needed.

**Example:**
- `career_site_url: "https://jobs.ascension.org"`
- `state: "Illinois"` (optional; worth setting since unfiltered results
  are personalized to the requester's IP-geolocated location)

### findly

For employers on the Findly/Radancy career-site platform (e.g. Advocate
Health at `careers.aah.org`). Needs the numeric tenant ID (`org_id`),
found in the target site's `cws_opts` JS object.

**Example:**
- `org_id: "2297"`
- `career_site_url: "https://careers.aah.org"` (captured for
  documentation only; the adapter doesn't read it)
- `max_pages: 20` (default)

---

`include_keywords` / `exclude_keywords` are optional on every type —
case-insensitive title filters, matched against the job title only.
