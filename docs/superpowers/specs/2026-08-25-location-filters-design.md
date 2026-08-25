# Location Filters Design

**Date:** 2026-08-25  
**Branch:** `feat/location-filters` (to be created from `master`)  
**Version bump:** 0.44.0 → 0.45.0

## Summary

Add two new filter dimensions to the Jobs page (and Jobs Map):

1. **State filter** — a dropdown populated from already-geocoded `region` values, letting users restrict results to a single US state (or any region Nominatim returns).
2. **Zip/location + radius filter** — a text input (zip code or city) plus a miles dropdown (10/25/50/100); the input is geocoded inline and jobs are filtered by haversine distance.

Additionally:
- Create a GitHub issue for multi-select filters (deferred, not implemented here).
- Add a ROADMAP entry documenting job-type availability per adapter (not implemented here).

## Context

**"Advocate" uses the Findly adapter.** The Findly API returns `primary_city` + `primary_state` separately, but currently combines them into a single `location` string (e.g., `"Milwaukee, WI"`). After Nominatim geocoding, `geocoded_locations.region` holds the full state name. So state filtering works from existing geocoded data without adapter changes.

**State data already stored.** `geocoded_locations.region` is populated by the Nominatim geocoder for all resolved job locations. No schema migration needed for state filtering.

**Haversine in SQLite.** SQLite has no built-in spherical distance function. We register a Python `_haversine_miles(lat1, lon1, lat2, lon2)` function on the connection at `init_db` time using `conn.create_function(...)`. This allows haversine distance comparisons directly in SQL WHERE clauses.

**Zip geocoding.** Nominatim can resolve a US zip code or city string to lat/lng in ~1s. For a personal tool this latency per filtered request is acceptable. Results are not cached (zip→lat/lng are transient; no extra DB table needed).

## DB Layer (`app/db.py`)

### New haversine function

```python
import math

def _haversine_miles(lat1, lon1, lat2, lon2):
    if any(x is None for x in (lat1, lon1, lat2, lon2)):
        return None
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))
```

Registered in `init_db` via `conn.create_function("haversine_miles", 4, _haversine_miles)`.

### New `list_job_states(conn)` function

```sql
SELECT DISTINCT region
FROM geocoded_locations
WHERE status IN ('resolved', 'manual') AND region IS NOT NULL
ORDER BY region COLLATE NOCASE
```

Returns `list[str]` — full state names as returned by Nominatim (e.g., "Illinois", "Wisconsin").

### `_job_filters_sql` changes

New parameters added:
- `state: str | None` → appends `geocoded_locations.region = ?`
- `zip_lat: float | None`, `zip_lng: float | None`, `radius_miles: float | None` → appends `haversine_miles(geocoded_locations.lat, geocoded_locations.lng, ?, ?) <= ?` only when all three are non-None

The existing `location` filter (matches `geocoded_locations.display_name`) is unchanged.

### Propagation

`list_jobs`, `count_jobs`, and `list_mappable_jobs` all gain `state`, `zip_lat`, `zip_lng`, `radius_miles` keyword params (all defaulting to `None`), which are forwarded to `_job_filters_sql`.

## Route Layer (`app/web/routes_jobs.py`)

### New query params on all three endpoints

- `/jobs` (GET)
- `/jobs/map` (GET)
- `/jobs/map/data` (GET)

New params: `state: str = ""`, `zip: str = ""`, `radius: str = "25"`.

### Zip geocoding

When `zip` is non-empty, the route handler geocodes it via `get_geocoder().geocode(zip)`. If geocoding returns `None`, the zip filter is skipped and the response includes a context key `zip_error=True` so the template can show an inline warning message. On success, the lat/lng + parsed `radius` (clamped to `[10, 25, 50, 100]`) are passed to the DB layer.

The radius param is validated: if not in `{10, 25, 50, 100}`, it defaults to 25.

### Filter dict

The `filters` dict passed to templates gains `state`, `zip`, and `radius` keys (plus optional `zip_error`).

### Context passed to DB

```python
zip_lat, zip_lng, radius_miles = None, None, None
if zip_code:
    result = geocoder.geocode(zip_code)
    if result:
        zip_lat, zip_lng = result.lat, result.lng
        radius_miles = float(radius)
    else:
        zip_error = True
```

## UI (`app/web/templates/jobs.html`, `jobs_map.html`)

### State dropdown

Added after the existing `location` dropdown:

```html
<label>State
  <select name="state">
    <option value="">All states</option>
    {% for s in states %}
    <option value="{{ s }}" {% if filters.state == s %}selected{% endif %}>{{ s }}</option>
    {% endfor %}
  </select>
</label>
```

`states` is provided by the route (from `db.list_job_states(conn)`).

### Zip + radius inputs

Added after the state dropdown, before the Status dropdown:

```html
<label>Near zip/city
  <input type="text" name="zip" value="{{ filters.zip }}" placeholder="e.g. 60148">
</label>
<label>Radius
  <select name="radius">
    {% for mi in [10, 25, 50, 100] %}
    <option value="{{ mi }}" {% if filters.radius|int == mi %}selected{% endif %}>{{ mi }} mi</option>
    {% endfor %}
  </select>
</label>
{% if filters.zip_error %}
<p class="filter-error" role="alert">Could not resolve that zip/location — showing unfiltered results.</p>
{% endif %}
```

### "Clear filters" link

Updated condition to include `or filters.state or filters.zip`.

### `jobs_map.html`

Same two filter controls added to the map's filter form.

## Testing

### `test_db.py`

- `test_list_job_states_returns_distinct_geocoded_regions` — insert two jobs with geocoded locations in IL and WI; assert both states appear in `list_job_states`
- `test_list_job_states_excludes_unresolved` — pending geocoded location not returned
- `test_state_filter_returns_only_matching_region`
- `test_state_filter_with_no_match_returns_empty`
- `test_haversine_filter_includes_nearby_job` — Chicago lat/lng as search center, Chicago job included at 50 mi radius
- `test_haversine_filter_excludes_distant_job` — LA lat/lng excluded at 50 mi radius from Chicago
- `test_haversine_filter_null_coordinates_excluded` — job with null lat/lng not included
- `test_count_jobs_with_state_filter`
- `test_list_mappable_jobs_with_state_filter`

### `tests/web/test_jobs.py`

- `test_jobs_page_state_filter_shows_matching_jobs`
- `test_jobs_page_state_filter_excludes_other_states`
- `test_jobs_page_zip_radius_filter_includes_nearby` — monkeypatch geocoder to return known lat/lng
- `test_jobs_page_zip_radius_filter_excludes_distant`
- `test_jobs_page_invalid_zip_shows_warning_and_all_results`
- `test_jobs_map_data_state_filter`
- `test_jobs_map_data_zip_radius_filter`

### `test_geocoding.py`

- `test_haversine_miles_known_distance` — Chicago to Milwaukee is ~87 miles; verify within ±2 mi
- `test_haversine_miles_with_null_returns_none`
- `test_haversine_miles_same_point_returns_zero`

## Non-Goals (Deferred)

- **Multi-select filters** — filed as a GitHub issue (e.g., select multiple sources at once). Not implemented in this branch.
- **Job type (full/part-time)** — added to ROADMAP with per-adapter availability notes. Not implemented in this branch.
  - Lever: `categories.commitment` (available)
  - Greenhouse: job metadata (available, needs investigation)
  - Findly: `employment_type` field (needs investigation)
  - Workday: needs investigation
  - TalentBrew, Infor, LinkedIn, Indeed (scraping-based): unreliable/unavailable

## Files Changed

| File | Change |
|------|--------|
| `app/db.py` | Add `_haversine_miles`, register in `init_db`, add `list_job_states`, extend `_job_filters_sql` and callers |
| `app/web/routes_jobs.py` | Add `state`/`zip`/`radius` params to 3 endpoints; inline zip geocoding |
| `app/web/templates/jobs.html` | State dropdown + zip/radius inputs |
| `app/web/templates/jobs_map.html` | Same filter controls |
| `tests/test_db.py` | New state + haversine tests |
| `tests/test_geocoding.py` | New haversine unit tests |
| `tests/web/test_jobs.py` | New filter integration tests |
| `ROADMAP.md` | Add job-type adapter notes |
| `CHANGELOG.md` | Entry for 0.45.0 |
| `pyproject.toml` | Bump version to 0.45.0 |

## Version

0.44.0 → **0.45.0**
