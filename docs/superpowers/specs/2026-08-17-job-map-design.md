# Job Map — Design Spec

Date: 2026-08-17
Status: Approved for planning

## Purpose

Closes GH #49 ("Job Map" — "Given the city locations of the jobs, can a
map be generated to show where the jobs are?").

The issue is a one-line ask with no labels or comments; scope was
clarified directly with the user — see Decisions below.

## Decisions (from user clarification)

| Question | Decision |
|---|---|
| Where the map lives | A view toggle on the existing `/jobs` table page, sharing its filters, backed by its own addressable route (`/jobs/map`) rather than a client-side-only tab |
| Geocoding provider | Nominatim (OpenStreetMap) as the default, free, no API key — behind a swappable provider abstraction |
| Map rendering library | Leaflet + Leaflet.markercluster as the default, self-hosted (no CDN) — behind a swappable renderer module |
| Location normalization scope | Also drives the `/jobs` table: a new Location filter dropdown, and cleaner display of the Location column, not just the map |
| Location relationship | `jobs.location` gets a real, enforced `FOREIGN KEY` to the new `geocoded_locations` table (not just an implicit string match) |
| When geocoding happens | Background step at the end of each orchestrator run, respecting the provider's rate limit — never synchronously on page load |
| Marker click behavior | Popup listing the job(s) at that location, each linking out (same `safe_url_scheme` pattern as elsewhere); clicking a cluster zooms in |
| Unresolved locations (`Remote`, empty, failed geocodes) | Silently excluded from the map's markers; still visible in the table and its filter under a single "Other / Unresolved" bucket |

## Data model (`app/db.py`)

New table, added to `SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS geocoded_locations (
    location TEXT PRIMARY KEY,   -- raw Job.location string, the cache key
    display_name TEXT,           -- clean label, e.g. "Chicago, IL"
    city TEXT,
    region TEXT,
    country TEXT,
    lat REAL,
    lng REAL,
    status TEXT NOT NULL,        -- 'pending' | 'resolved' | 'failed'
    provider TEXT,
    resolved_at TEXT
);
```

`location` is the natural key — many jobs across many adapters share the
same raw string, so this table doubles as the geocode cache. No new
column on `jobs`; the existing `jobs.location` column becomes the FK
target's other end.

### FK enforcement (a real migration, not an additive one)

Every other migration in this codebase so far has been additive
(`ALTER TABLE ... ADD COLUMN`, see `_migrate_jobs_table`). This one isn't:

- SQLite cannot add a `FOREIGN KEY` constraint to an existing table via
  `ALTER TABLE`. Enforcing `jobs.location REFERENCES geocoded_locations(location)`
  requires the standard SQLite rebuild pattern — create a new `jobs`
  table with the constraint declared, `INSERT INTO ... SELECT` the
  existing rows across, drop the old table, rename the new one — done
  once, inside a transaction, in a new migration function.
- `PRAGMA foreign_keys = ON` is not currently set anywhere (SQLite
  defaults to unenforced, and the setting doesn't persist in the file —
  it must be issued on every connection). Add it in `init_db`,
  immediately after `sqlite3.connect(...)`.
- Because this is a live prod SQLite file (Portainer-deployed, per
  existing deployment notes), the rebuild migration gets verified
  against a copy of the production database before shipping, not just
  the test suite's throwaway DB.
- Once FK enforcement is on, `save_jobs` must insert a stub row
  (`location`, `status='pending'`) into `geocoded_locations` for any
  new location string *before* inserting the job row that references
  it — otherwise the insert violates the FK the first time a location
  is ever seen. `NULL` locations are unaffected (SQLite FKs don't
  require `NULL` child values to match anything).

### New functions

- `list_job_locations(conn) -> list[str]` — distinct resolved
  `display_name` values for the filter dropdown, plus a single
  `"Other / Unresolved"` sentinel representing everything with
  `status != 'resolved'` or a `NULL` location. Mirrors
  `list_job_source_names`.
- Geocoding-specific functions live in `app/geocoding/`, not `app/db.py`
  (see below), to keep the cache-table CRUD separate from the
  provider-calling logic.

### Filtering

`_job_filters_sql`, `list_jobs`, `count_jobs` gain a `location`
parameter, same shape as `company`/`source_name`:

- `""` (absent) → no filter
- `"__unresolved__"` (or similar sentinel) → jobs whose location has no
  `status = 'resolved'` row
- any other value → `geocoded_locations.display_name = ?`, via
  `LEFT JOIN geocoded_locations ON jobs.location = geocoded_locations.location`

The same join backs the table's Location column: `display_name` when
resolved, falling back to raw `jobs.location` text otherwise.

## Geocoding abstraction (`app/geocoding/`)

New package:

- `base.py` — a `Geocoder` protocol with one method:
  `geocode(location: str) -> GeocodeResult | None`, where
  `GeocodeResult` carries `display_name`, `city`, `region`, `country`,
  `lat`, `lng`.
- `nominatim.py` — default implementation using `requests` (already a
  dependency). Enforces the ~1 req/sec rate limit and sets the
  descriptive `User-Agent` header Nominatim's usage policy requires —
  not optional, this is how the service identifies well-behaved
  clients.
- `factory.py` — reads a config value (`app/config.py`) to construct
  the active `Geocoder`. Swapping providers later (Mapbox, Google) is
  one new file + one config value, no call-site changes.
- `service.py` — `geocode_pending(conn, geocoder) -> None`: queries
  `geocoded_locations WHERE status = 'pending'`, geocodes each through
  the given `Geocoder`, rate-limited, updates each row to `resolved` or
  `failed`. Catches and logs per-location failures individually — one
  bad location never aborts the batch.

## Orchestrator integration (`app/orchestrator.py`)

`geocode_pending` runs as a best-effort tail step after each scheduled
fetch run:

- Must never block or fail the run itself — wrapped so a geocoding
  error (network failure, provider outage) is caught and logged, not
  raised.
- Steady-state cost is low: `save_jobs` only stubs genuinely *new*
  location strings, so a typical run has zero or a handful of pending
  rows. The 1 req/sec limit only matters for the first-run backlog on
  an existing dataset.
- Failed rows stay `failed` (not silently retried forever) — a future
  "reset failed geocodes" path is explicitly out of scope for v1 (see
  below); for now a failed row is simply excluded from the map/filter
  like any unresolved one.

## Map page & JS

**Routes** (`app/web/routes_jobs.py`):

- `GET /jobs/map` — renders `jobs_map.html`: same filter bar as
  `/jobs`, an empty map container, a "Table view" link back to `/jobs`
  carrying the current query string. `/jobs` gains the matching
  "Map view" link.
- `GET /jobs/map/data` — JSON endpoint, accepts the same filter params
  as `/jobs` (`company`, `source`, `location`, `removed`, `emailed`,
  `status`). Returns all matching jobs with a *resolved* location,
  grouped by location:
  `[{lat, lng, display_name, jobs: [{key, title, company, url}, ...]}]`.
  Deliberately ignores the table's 25-per-page pagination — showing
  everything at once is the point of a map view.

**Static JS** (`app/web/static/`):

- `map.js` — page glue only: reads current filters from the URL,
  fetches `/jobs/map/data`, hands the result to a renderer.
- `leaflet_renderer.js` — the *only* file that touches the Leaflet API,
  exposing a small contract: `renderMap(containerId, locations)`.
  Swapping rendering libraries later means writing a new file against
  the same contract and changing one line of wiring in `map.js`. This
  is the realistic shape of "abstraction" in a no-build vanilla-JS
  codebase — an isolated module boundary, not a runtime-swappable class
  hierarchy like the Python side.
- Marker popups list the jobs at that location (title + company, each
  linking out via the existing `safe_url_scheme` pattern). Clicking a
  cluster zooms in — standard `Leaflet.markercluster` behavior, no
  custom code needed.

**Vendoring & packaging** (two concrete issues found while reading the
current config):

- Leaflet + Leaflet.markercluster (JS/CSS/images, MIT-licensed) get
  committed under `app/web/static/vendor/leaflet/` and
  `app/web/static/vendor/leaflet.markercluster/`, including their
  LICENSE files. No CDN — consistent with every other script in
  `base.html` being self-hosted.
- `pyproject.toml`'s package-data glob (`"app.web" = ["templates/*.html", "static/*"]`)
  is **non-recursive** and would silently drop everything under
  `static/vendor/leaflet/**` from the built Docker image — works in
  local dev, 404s in prod. Needs to become `"static/**/*"` (or an
  explicit vendor path added).

**CSP** (`app/web/security_headers.py`):

- `img-src` is currently `'self' data:`. Needs
  `https://*.tile.openstreetmap.org` added for map tile images.
  `script-src`/`style-src` need no change — Leaflet's own JS/CSS are
  vendored under `'self'`.

## Testing

TDD per `AGENTS.md`. Positive and negative cases:

**`tests/test_geocoding.py`** (new)
- Positive: `factory` returns the configured provider; a fake
  `Geocoder` stub verifies `geocode_pending` transitions
  `pending → resolved` and writes `display_name`/`lat`/`lng`/`provider`/
  `resolved_at` correctly; a stub that returns `None` transitions to
  `failed`; already-`resolved`/`failed` rows are never re-queried.
- Negative: a `Geocoder` that raises is caught per-location — one
  failure doesn't abort processing of the remaining pending rows.

**`tests/test_db.py`**
- Positive: the FK-enforced migration preserves existing `jobs` rows
  byte-for-byte across the rebuild; `save_jobs` inserts a `pending`
  stub row for a never-before-seen location and reuses the existing row
  for a repeated one; `list_jobs`/`count_jobs` with `location=<display_name>`
  and `location="__unresolved__"` return the expected subsets;
  `list_job_locations` returns distinct resolved names plus the
  unresolved sentinel.
- Negative: inserting a job with a location that has no
  `geocoded_locations` row (bypassing `save_jobs`'s stub-insert step)
  raises the FK violation — proves enforcement is actually on.

**`tests/web/test_jobs.py`**
- Positive: `GET /jobs/map` renders; `GET /jobs/map/data` returns
  correctly grouped/filtered JSON, respects all shared filter params,
  and excludes unresolved-location jobs; `GET /jobs?location=...`
  filters the table correctly.
- Negative: `/jobs/map/data` with filters matching zero resolved jobs
  returns an empty array, not an error.

**Orchestrator**
- Positive: a run's tail step calls `geocode_pending`; a geocoding
  failure is logged but doesn't raise out of the run (matches existing
  per-source failure isolation in `orchestrator.py`).

**e2e (`tests/web/e2e/`)** — one representative scenario: load
`/jobs/map` with seeded resolved locations, confirm markers render and
a marker popup lists the expected job(s), matching the existing e2e
style.

**JS** — no test runner exists in this repo (no `package.json`);
`map.js`/`leaflet_renderer.js` get manual verification in a real
browser, consistent with how the other static JS files are handled
today.

## Documentation + version

- `pyproject.toml`: `0.20.0` → `0.21.0`.
- `CHANGELOG.md`: new `### Added` entry — job location map on a new
  `/jobs/map` view, background geocoding via a swappable provider
  (Nominatim by default), and a Location filter/cleaner display on the
  `/jobs` table (issue #49).
- `docs/USAGE.md`: extend the `/jobs` row to mention the Location
  filter and the Map view link, mirrored into `README.md`'s Web UI
  table and `app/web/templates/guide.html`'s Jobs row — same
  three-place pattern used for prior Jobs-page features.

## Explicitly out of scope

- Deduplicating distinct raw location strings that refer to the same
  real place beyond what the geocoding provider's own normalization
  already does (e.g. `"SF"` vs `"San Francisco, CA"` may still cache as
  two separate rows if the provider doesn't normalize them to the same
  `display_name`). A dedicated location-alias system is a separate
  feature.
- Retrying `failed` geocode rows automatically — v1 geocodes each
  pending location once per run cycle; a stuck `failed` row stays
  `failed` until addressed manually (e.g. a future admin action or a
  direct DB edit). No exponential backoff or retry-count column.
- Per-job markers — markers are grouped by resolved location, not one
  marker per job. Clustering handles *nearby distinct* locations at low
  zoom; it does not apply within a single already-grouped location.
- Reverse geocoding, radius search, or any location-based sort/proximity
  feature — the issue asks only to *see* where jobs are.
- Editing/correcting a bad geocode result through the UI — a wrong
  `display_name`/`lat`/`lng` is corrected by deleting the
  `geocoded_locations` row directly (or a future admin tool), not part
  of this feature.
- Any change to the digest email — this is a Jobs-page/map feature, not
  a change to what the scheduled digest reports.
