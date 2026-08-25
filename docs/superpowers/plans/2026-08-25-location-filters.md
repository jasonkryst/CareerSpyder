# Location Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a State dropdown filter and a Zip/location + radius filter to the Jobs page and Jobs Map.

**Architecture:** Haversine distance is computed inside SQLite via a registered Python function; all filter logic lives in `_job_filters_sql`; routes geocode the zip inline on each request; templates get a new `states` list and two new filter controls.

**Tech Stack:** Python 3.12, FastAPI, SQLite (via `sqlite3`), Jinja2, Nominatim geocoder (already wired)

**Spec:** `docs/superpowers/specs/2026-08-25-location-filters-design.md`

## Global Constraints

- Python ≥ 3.12 (`list[str]`, `str | None`, `float | None` union syntax in signatures)
- No new dependencies — haversine uses stdlib `math`; geocoding uses existing `NominatimGeocoder`
- No DB schema migration — `geocoded_locations.region` already stores state; `lat`/`lng` already store coordinates
- Radius values: only `10`, `25`, `50`, `100` miles are valid; default `25`; anything else coerces to `25`
- Query param name for zip is `zip` (URL); variable name inside handlers is `zip_code` (avoids shadowing builtin)
- `_haversine_miles` starts with underscore — it's a module-level private helper in `app/db.py`
- ruff S608 suppression already covers `app/db.py` (dynamic SQL in `_job_filters_sql`)
- Version bump: `0.44.0` → `0.45.0`

---

## Branch Setup

Before starting any task, create the feature branch:

```bash
git checkout master
git pull
git checkout -b feat/location-filters
```

---

### Task 1: Haversine function + state/zip filters in the DB layer

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces:
  - `db._haversine_miles(lat1, lon1, lat2, lon2) -> float | None` — module-level, registered as SQLite scalar
  - `db.list_job_states(conn) -> list[str]`
  - `db.list_jobs(..., state=None, zip_lat=None, zip_lng=None, radius_miles=None)`
  - `db.count_jobs(..., state=None, zip_lat=None, zip_lng=None, radius_miles=None)`
  - `db.list_mappable_jobs(..., state=None, zip_lat=None, zip_lng=None, radius_miles=None)`

---

- [ ] **Step 1: Write failing tests for `_haversine_miles`**

Add to `tests/test_db.py` (after the existing imports at the top):

```python
from app.db import _haversine_miles
```

Add these tests (anywhere in the file — group them near the geocoded_locations tests):

```python
# ── haversine function ────────────────────────────────────────────────────────

def test_haversine_miles_known_distance():
    # Chicago (41.8781, -87.6298) to Milwaukee (43.0389, -87.9065) is ~87 miles
    dist = _haversine_miles(41.8781, -87.6298, 43.0389, -87.9065)
    assert 85 < dist < 90


def test_haversine_miles_same_point_returns_zero():
    dist = _haversine_miles(41.8781, -87.6298, 41.8781, -87.6298)
    assert dist == pytest.approx(0.0, abs=1e-6)


def test_haversine_miles_null_lat1_returns_none():
    assert _haversine_miles(None, -87.6298, 41.8781, -87.6298) is None


def test_haversine_miles_null_lng2_returns_none():
    assert _haversine_miles(41.8781, -87.6298, 43.0389, None) is None


def test_haversine_registered_on_db_connection(tmp_db_path):
    # Verify init_db registers the function so SQL can call it
    conn = db.init_db(tmp_db_path)
    result = conn.execute(
        "SELECT haversine_miles(41.8781, -87.6298, 43.0389, -87.9065)"
    ).fetchone()[0]
    assert 85 < result < 90
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_db.py -k "haversine" -v
```

Expected: `ImportError` (`_haversine_miles` not in `app.db`) or `OperationalError` (function not registered).

- [ ] **Step 3: Implement `_haversine_miles` and register it in `init_db`**

At the top of `app/db.py`, add `import math` to the existing imports block:

```python
import json
import math
import sqlite3
from datetime import UTC, datetime
```

Add this function directly above `init_db` (before the `def init_db` line):

```python
def _haversine_miles(lat1: float | None, lon1: float | None,
                     lat2: float | None, lon2: float | None) -> float | None:
    if any(x is None for x in (lat1, lon1, lat2, lon2)):
        return None
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))
```

In `init_db`, add `conn.create_function(...)` immediately after `conn = sqlite3.connect(...)`:

```python
def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.create_function("haversine_miles", 4, _haversine_miles)   # ← add this line
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    ...
```

- [ ] **Step 4: Run haversine tests to verify they pass**

```
pytest tests/test_db.py -k "haversine" -v
```

Expected: all 5 PASS.

---

- [ ] **Step 5: Write failing tests for `list_job_states`**

Add to `tests/test_db.py`:

```python
# ── list_job_states ──────────────────────────────────────────────────────────

def test_list_job_states_returns_distinct_geocoded_regions(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    run_id = db.start_run(conn)
    from app.models import Job
    db.save_jobs(conn, [
        Job(key="k1", title="A", url="https://x.test/1", source_name="Board", location="Chicago, IL"),
        Job(key="k2", title="B", url="https://x.test/2", source_name="Board", location="Milwaukee, WI"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', region = 'Illinois' "
        "WHERE location = 'Chicago, IL'"
    )
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', region = 'Wisconsin' "
        "WHERE location = 'Milwaukee, WI'"
    )
    conn.commit()

    states = db.list_job_states(conn)

    assert states == ["Illinois", "Wisconsin"]


def test_list_job_states_excludes_pending_locations(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    run_id = db.start_run(conn)
    from app.models import Job
    db.save_jobs(conn, [
        Job(key="k1", title="A", url="https://x.test/1", source_name="Board", location="Chicago, IL"),
    ], run_id)
    # location stays 'pending', no region set

    states = db.list_job_states(conn)

    assert states == []


def test_list_job_states_deduplicates_same_region(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    run_id = db.start_run(conn)
    from app.models import Job
    db.save_jobs(conn, [
        Job(key="k1", title="A", url="https://x.test/1", source_name="Board", location="Chicago, IL"),
        Job(key="k2", title="B", url="https://x.test/2", source_name="Board", location="Naperville, IL"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', region = 'Illinois' "
        "WHERE location IN ('Chicago, IL', 'Naperville, IL')"
    )
    conn.commit()

    states = db.list_job_states(conn)

    assert states == ["Illinois"]
```

- [ ] **Step 6: Run tests to verify they fail**

```
pytest tests/test_db.py -k "list_job_states" -v
```

Expected: `AttributeError` — `db` has no attribute `list_job_states`.

- [ ] **Step 7: Implement `list_job_states`**

Add this function to `app/db.py` near `list_job_locations` (after it):

```python
def list_job_states(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT region FROM geocoded_locations "
        "WHERE status IN ('resolved', 'manual') AND region IS NOT NULL "
        "ORDER BY region COLLATE NOCASE"
    ).fetchall()
    return [r[0] for r in rows]
```

- [ ] **Step 8: Run tests to verify they pass**

```
pytest tests/test_db.py -k "list_job_states" -v
```

Expected: all 3 PASS.

---

- [ ] **Step 9: Write failing tests for state and zip/radius filters**

Add to `tests/test_db.py`:

```python
# ── state filter ─────────────────────────────────────────────────────────────

def _make_geocoded_job(conn, key, title, location, region, lat=None, lng=None):
    """Helper: save a job and set its geocoded_locations row."""
    from app.models import Job
    run_id = db.start_run(conn)
    db.save_jobs(conn, [Job(key=key, title=title, url=f"https://x.test/{key}",
                             source_name="Board", location=location)], run_id)
    cols = "status = 'resolved', region = ?"
    params = [region]
    if lat is not None:
        cols += ", lat = ?, lng = ?"
        params += [lat, lng]
    conn.execute(f"UPDATE geocoded_locations SET {cols} WHERE location = ?",
                 params + [location])
    conn.commit()


def test_state_filter_narrows_to_matching_region(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    _make_geocoded_job(conn, "k1", "IL Job", "Chicago, IL", "Illinois")
    _make_geocoded_job(conn, "k2", "WI Job", "Milwaukee, WI", "Wisconsin")

    rows = db.list_jobs(conn, state="Illinois")

    assert len(rows) == 1
    assert rows[0]["title"] == "IL Job"


def test_state_filter_with_no_match_returns_empty(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    _make_geocoded_job(conn, "k1", "IL Job", "Chicago, IL", "Illinois")

    rows = db.list_jobs(conn, state="Texas")

    assert rows == []


def test_count_jobs_with_state_filter(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    _make_geocoded_job(conn, "k1", "IL Job", "Chicago, IL", "Illinois")
    _make_geocoded_job(conn, "k2", "WI Job", "Milwaukee, WI", "Wisconsin")

    assert db.count_jobs(conn, state="Illinois") == 1
    assert db.count_jobs(conn, state="Wisconsin") == 1
    assert db.count_jobs(conn) == 2


def test_list_mappable_jobs_with_state_filter(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    _make_geocoded_job(conn, "k1", "IL Job", "Chicago, IL", "Illinois", lat=41.8, lng=-87.6)
    _make_geocoded_job(conn, "k2", "WI Job", "Milwaukee, WI", "Wisconsin", lat=43.0, lng=-87.9)

    rows = db.list_mappable_jobs(conn, state="Illinois")

    assert len(rows) == 1
    assert rows[0]["key"] == "k1"


# ── zip/radius filter ─────────────────────────────────────────────────────────

def test_haversine_filter_includes_job_within_radius(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    # Chicago job at ~0 miles from search center (Chicago)
    _make_geocoded_job(conn, "k1", "Chicago Job", "Chicago, IL", "Illinois",
                       lat=41.8781, lng=-87.6298)

    rows = db.list_jobs(conn, zip_lat=41.8781, zip_lng=-87.6298, radius_miles=50.0)

    assert len(rows) == 1
    assert rows[0]["title"] == "Chicago Job"


def test_haversine_filter_excludes_job_outside_radius(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    # LA is ~1750 miles from Chicago
    _make_geocoded_job(conn, "k1", "LA Job", "Los Angeles, CA", "California",
                       lat=34.0522, lng=-118.2437)

    rows = db.list_jobs(conn, zip_lat=41.8781, zip_lng=-87.6298, radius_miles=50.0)

    assert rows == []


def test_haversine_filter_excludes_job_with_null_coordinates(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    # Save job but leave lat/lng null (pending geocode)
    from app.models import Job
    run_id = db.start_run(conn)
    db.save_jobs(conn, [Job(key="k1", title="No Coords", url="https://x.test/1",
                             source_name="Board", location="Remote")], run_id)
    # geocoded_locations row exists but lat/lng are null

    rows = db.list_jobs(conn, zip_lat=41.8781, zip_lng=-87.6298, radius_miles=50.0)

    assert rows == []


def test_haversine_filter_boundary_at_exact_radius(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    # Milwaukee is ~87 miles from Chicago — inside 100 mi, outside 50 mi
    _make_geocoded_job(conn, "k1", "Milwaukee Job", "Milwaukee, WI", "Wisconsin",
                       lat=43.0389, lng=-87.9065)

    inside = db.list_jobs(conn, zip_lat=41.8781, zip_lng=-87.6298, radius_miles=100.0)
    outside = db.list_jobs(conn, zip_lat=41.8781, zip_lng=-87.6298, radius_miles=50.0)

    assert len(inside) == 1
    assert outside == []


def test_count_jobs_with_radius_filter(tmp_db_path):
    conn = db.init_db(tmp_db_path)
    _make_geocoded_job(conn, "k1", "Chicago Job", "Chicago, IL", "Illinois",
                       lat=41.8781, lng=-87.6298)
    _make_geocoded_job(conn, "k2", "LA Job", "Los Angeles, CA", "California",
                       lat=34.0522, lng=-118.2437)

    assert db.count_jobs(conn, zip_lat=41.8781, zip_lng=-87.6298, radius_miles=50.0) == 1
```

- [ ] **Step 10: Run tests to verify they fail**

```
pytest tests/test_db.py -k "state_filter or haversine_filter or count_jobs_with_state or list_mappable" -v
```

Expected: `TypeError` — `list_jobs()` got unexpected keyword argument `state`.

- [ ] **Step 11: Extend `_job_filters_sql` and its callers**

In `app/db.py`, change `_job_filters_sql` signature and body.

**Before:**
```python
def _job_filters_sql(
    company: str | None, source_name: str | None, removed: str | None, emailed: str | None,
    status: str | None = None, location: str | None = None, duplicates: str | None = None,
) -> tuple[str, list]:
    clauses = []
    params: list = []
    ...
    if duplicates == "only":
        clauses.append("jobs.is_duplicate = 1")
    elif duplicates != "include":
        clauses.append("jobs.is_duplicate = 0")
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params
```

**After** (add two new optional params and their clauses before `where_sql =`):
```python
def _job_filters_sql(
    company: str | None, source_name: str | None, removed: str | None, emailed: str | None,
    status: str | None = None, location: str | None = None, duplicates: str | None = None,
    state: str | None = None,
    zip_lat: float | None = None, zip_lng: float | None = None, radius_miles: float | None = None,
) -> tuple[str, list]:
    clauses = []
    params: list = []
    ...
    if duplicates == "only":
        clauses.append("jobs.is_duplicate = 1")
    elif duplicates != "include":
        clauses.append("jobs.is_duplicate = 0")
    if state:
        clauses.append("geocoded_locations.region = ?")
        params.append(state)
    if zip_lat is not None and zip_lng is not None and radius_miles is not None:
        clauses.append("haversine_miles(geocoded_locations.lat, geocoded_locations.lng, ?, ?) <= ?")
        params.extend([zip_lat, zip_lng, radius_miles])
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params
```

Add the four new keyword params to `list_jobs`, `count_jobs`, and `list_mappable_jobs`, and forward them to `_job_filters_sql`.

**`list_jobs` — before:**
```python
def list_jobs(
    conn: sqlite3.Connection, limit: int = 25, offset: int = 0, *,
    sort: str = "", direction: str = "",
    company: str | None = None, source_name: str | None = None,
    removed: str | None = None, emailed: str | None = None, status: str | None = None,
    location: str | None = None, duplicates: str | None = None,
) -> list[dict]:
    ...
    where_sql, params = _job_filters_sql(company, source_name, removed, emailed, status, location, duplicates)
```

**`list_jobs` — after:**
```python
def list_jobs(
    conn: sqlite3.Connection, limit: int = 25, offset: int = 0, *,
    sort: str = "", direction: str = "",
    company: str | None = None, source_name: str | None = None,
    removed: str | None = None, emailed: str | None = None, status: str | None = None,
    location: str | None = None, duplicates: str | None = None,
    state: str | None = None,
    zip_lat: float | None = None, zip_lng: float | None = None, radius_miles: float | None = None,
) -> list[dict]:
    ...
    where_sql, params = _job_filters_sql(
        company, source_name, removed, emailed, status, location, duplicates,
        state=state, zip_lat=zip_lat, zip_lng=zip_lng, radius_miles=radius_miles,
    )
```

**`count_jobs` — before:**
```python
def count_jobs(
    conn: sqlite3.Connection, *,
    company: str | None = None, source_name: str | None = None,
    removed: str | None = None, emailed: str | None = None, status: str | None = None,
    location: str | None = None, duplicates: str | None = None,
) -> int:
    where_sql, params = _job_filters_sql(company, source_name, removed, emailed, status, location, duplicates)
```

**`count_jobs` — after:**
```python
def count_jobs(
    conn: sqlite3.Connection, *,
    company: str | None = None, source_name: str | None = None,
    removed: str | None = None, emailed: str | None = None, status: str | None = None,
    location: str | None = None, duplicates: str | None = None,
    state: str | None = None,
    zip_lat: float | None = None, zip_lng: float | None = None, radius_miles: float | None = None,
) -> int:
    where_sql, params = _job_filters_sql(
        company, source_name, removed, emailed, status, location, duplicates,
        state=state, zip_lat=zip_lat, zip_lng=zip_lng, radius_miles=radius_miles,
    )
```

**`list_mappable_jobs` — before:**
```python
def list_mappable_jobs(
    conn: sqlite3.Connection, *,
    company: str | None = None, source_name: str | None = None, location: str | None = None,
    removed: str | None = None, emailed: str | None = None, status: str | None = None,
    exclude_status: str | None = None, duplicates: str | None = None,
) -> list[dict]:
    where_sql, params = _job_filters_sql(company, source_name, removed, emailed, status, location, duplicates)
```

**`list_mappable_jobs` — after:**
```python
def list_mappable_jobs(
    conn: sqlite3.Connection, *,
    company: str | None = None, source_name: str | None = None, location: str | None = None,
    removed: str | None = None, emailed: str | None = None, status: str | None = None,
    exclude_status: str | None = None, duplicates: str | None = None,
    state: str | None = None,
    zip_lat: float | None = None, zip_lng: float | None = None, radius_miles: float | None = None,
) -> list[dict]:
    where_sql, params = _job_filters_sql(
        company, source_name, removed, emailed, status, location, duplicates,
        state=state, zip_lat=zip_lat, zip_lng=zip_lng, radius_miles=radius_miles,
    )
```

- [ ] **Step 12: Run all new DB tests**

```
pytest tests/test_db.py -v
```

Expected: all tests PASS (including the full existing suite).

- [ ] **Step 13: Run the full test suite**

```
pytest -v
```

Expected: all PASS. Fix any regressions before continuing.

- [ ] **Step 14: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat(db): add haversine function, list_job_states, and state/zip-radius filters"
```

---

### Task 2: Route layer — new params and inline zip geocoding

**Files:**
- Modify: `app/web/routes_jobs.py`
- Test: `tests/web/test_jobs.py`

**Interfaces:**
- Consumes: `db.list_job_states(conn)`, `db.list_jobs(..., state, zip_lat, zip_lng, radius_miles)`, `db.count_jobs(..., state, zip_lat, zip_lng, radius_miles)`, `db.list_mappable_jobs(..., state, zip_lat, zip_lng, radius_miles)`
- Produces:
  - `/jobs` GET: new params `state`, `zip` (alias for `zip_code`), `radius`; template context gains `states: list[str]`, `filters.state`, `filters.zip`, `filters.radius`, `filters.zip_error`
  - `/jobs/map` GET: same new params and context
  - `/jobs/map/data` GET: same new params, geocodes zip, returns filtered map JSON

---

- [ ] **Step 1: Write failing tests for `/jobs` state and zip/radius params**

Add to `tests/web/test_jobs.py`. The existing `_fake_geocode_response` helper is already defined in this file — reuse it.

```python
# ── State filter (routes) ────────────────────────────────────────────────────

def test_jobs_page_state_filter_narrows_to_matching_region(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        make_job(key="a", title="IL Job", location="Chicago, IL"),
        make_job(key="b", title="WI Job", location="Milwaukee, WI"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', region = 'Illinois' "
        "WHERE location = 'Chicago, IL'"
    )
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', region = 'Wisconsin' "
        "WHERE location = 'Milwaukee, WI'"
    )
    conn.commit()

    resp = client.get("/jobs?state=Illinois")

    assert resp.status_code == 200
    assert "IL Job" in resp.text
    assert "WI Job" not in resp.text


def test_jobs_page_state_dropdown_lists_geocoded_states(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="a", location="Chicago, IL")], db.start_run(conn))
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', region = 'Illinois' "
        "WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    resp = client.get("/jobs")

    assert '<option value="Illinois"' in resp.text


def test_jobs_page_state_filter_shown_in_clear_filters(client):
    resp = client.get("/jobs?state=Illinois")
    assert "Clear filters" in resp.text


# ── Zip/radius filter (routes) ───────────────────────────────────────────────

def test_jobs_page_zip_filter_includes_nearby_job(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="a", title="Chicago Job", location="Chicago, IL")], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', lat = 41.8781, lng = -87.6298 "
        "WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    from unittest.mock import patch
    # geocode("60148") → Chicago-area lat/lng (Lombard, IL is near Chicago)
    with patch("app.geocoding.nominatim.requests.get",
               return_value=_fake_geocode_response(lat="41.8781", lon="-87.6298")):
        resp = client.get("/jobs?zip=60148&radius=25")

    assert resp.status_code == 200
    assert "Chicago Job" in resp.text


def test_jobs_page_zip_filter_excludes_distant_job(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [make_job(key="b", title="LA Job", location="Los Angeles, CA")], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', lat = 34.0522, lng = -118.2437 "
        "WHERE location = 'Los Angeles, CA'"
    )
    conn.commit()

    from unittest.mock import patch
    with patch("app.geocoding.nominatim.requests.get",
               return_value=_fake_geocode_response(lat="41.8781", lon="-87.6298")):
        resp = client.get("/jobs?zip=60148&radius=25")

    assert resp.status_code == 200
    assert "LA Job" not in resp.text


def test_jobs_page_invalid_zip_shows_warning_and_returns_unfiltered_results(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="a", title="Any Job")], db.start_run(conn))

    from unittest.mock import Mock, patch
    empty_resp = Mock()
    empty_resp.raise_for_status = Mock()
    empty_resp.json.return_value = []
    with patch("app.geocoding.nominatim.requests.get", return_value=empty_resp):
        resp = client.get("/jobs?zip=00000&radius=25")

    assert resp.status_code == 200
    assert "Could not resolve" in resp.text
    assert "Any Job" in resp.text  # unfiltered — zip error skips the filter


def test_jobs_page_zip_shown_in_clear_filters(client):
    from unittest.mock import patch
    with patch("app.geocoding.nominatim.requests.get",
               return_value=_fake_geocode_response()):
        resp = client.get("/jobs?zip=60148")

    assert "Clear filters" in resp.text


# ── Map data state and zip/radius (routes) ───────────────────────────────────

def test_jobs_map_data_state_filter(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        make_job(key="a", title="IL Job", location="Chicago, IL"),
        make_job(key="b", title="WI Job", location="Milwaukee, WI"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', region = 'Illinois', "
        "lat = 41.8, lng = -87.6 WHERE location = 'Chicago, IL'"
    )
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', region = 'Wisconsin', "
        "lat = 43.0, lng = -87.9 WHERE location = 'Milwaukee, WI'"
    )
    conn.commit()

    resp = client.get("/jobs/map/data?state=Illinois")

    assert resp.status_code == 200
    data = resp.json()
    all_keys = {j["key"] for loc in data for j in loc["jobs"]}
    assert all_keys == {"a"}


def test_jobs_map_data_zip_radius_filter(client):
    conn = client.app.state.conn
    run_id = db.start_run(conn)
    db.save_jobs(conn, [
        make_job(key="a", title="Chicago Job", location="Chicago, IL"),
        make_job(key="b", title="LA Job", location="Los Angeles, CA"),
    ], run_id)
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', lat = 41.8781, lng = -87.6298 "
        "WHERE location = 'Chicago, IL'"
    )
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', lat = 34.0522, lng = -118.2437 "
        "WHERE location = 'Los Angeles, CA'"
    )
    conn.commit()

    from unittest.mock import patch
    with patch("app.geocoding.nominatim.requests.get",
               return_value=_fake_geocode_response(lat="41.8781", lon="-87.6298")):
        resp = client.get("/jobs/map/data?zip=60148&radius=50")

    assert resp.status_code == 200
    data = resp.json()
    all_keys = {j["key"] for loc in data for j in loc["jobs"]}
    assert all_keys == {"a"}


def test_jobs_map_page_includes_state_dropdown(client):
    resp = client.get("/jobs/map")
    assert resp.status_code == 200
    assert 'name="state"' in resp.text


def test_jobs_map_page_includes_zip_input(client):
    resp = client.get("/jobs/map")
    assert resp.status_code == 200
    assert 'name="zip"' in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/web/test_jobs.py -k "state_filter or zip_filter or zip_shown or map_data_state or map_data_zip or map_page_includes" -v
```

Expected: `KeyError` on `states` in the template context or `TypeError` on route params.

- [ ] **Step 3: Implement route changes**

In `app/web/routes_jobs.py`, update the three endpoints:

**`/jobs` (GET) — full updated signature and body:**

```python
@router.get("/jobs", response_class=HTMLResponse)
def jobs(
    request: Request, page: str = "1", sort: str = "",
    direction: str = Query("", alias="dir"),
    company: str = "", source: str = "", removed: str = "active", emailed: str = "", status: str = "",
    location: str = "", duplicates: str = "", state: str = "",
    zip_code: str = Query("", alias="zip"), radius: str = "25",
):
    conn = request.app.state.conn
    zip_lat: float | None = None
    zip_lng: float | None = None
    radius_miles: float | None = None
    zip_error = False
    if zip_code:
        geocoder = get_geocoder()
        result = geocoder.geocode(zip_code)
        if result:
            zip_lat, zip_lng = result.lat, result.lng
            radius_miles = float(radius) if radius in ("10", "25", "50", "100") else 25.0
        else:
            zip_error = True
    filters = {
        "company": company or None, "source_name": source or None,
        "removed": removed or None, "emailed": emailed or None, "status": status or None,
        "location": location or None, "duplicates": duplicates or None,
        "state": state or None,
    }
    total = db.count_jobs(conn, **filters,
                          zip_lat=zip_lat, zip_lng=zip_lng, radius_miles=radius_miles)
    pagination = paginate(total, page, PAGE_SIZE)
    rows = db.list_jobs(
        conn, limit=PAGE_SIZE, offset=pagination.offset, sort=sort, direction=direction,
        **filters, zip_lat=zip_lat, zip_lng=zip_lng, radius_miles=radius_miles,
    )
    secondary_ids = _secondary_source_ids(request.app.state.sources_path)
    history = db.get_job_status_history(conn, [row["key"] for row in rows])
    for row in rows:
        row["age_days"] = _age_days(row["first_seen_at"], row["removed_at"])
        row["safe_url"] = safe_url_scheme(row["url"])
        row["is_secondary"] = row["source_id"] in secondary_ids
        row["history"] = [
            {"status_label": STATUSES.get(entry["status"], "No status"), "changed_at": entry["changed_at"]}
            for entry in history.get(row["key"], [])
        ]
    source_names = db.list_job_source_names(conn)
    locations = db.list_job_locations(conn)
    states = db.list_job_states(conn)
    return templates.TemplateResponse(request, "jobs.html", {
        "jobs": rows, "pagination": pagination, "source_names": source_names,
        "locations": locations, "states": states,
        "statuses": STATUSES,
        "filters": {
            "company": company, "source": source, "removed": removed, "emailed": emailed,
            "status": status, "location": location, "duplicates": duplicates,
            "state": state, "zip": zip_code, "radius": radius, "zip_error": zip_error,
        },
    })
```

**`/jobs/map` (GET) — add state/zip/radius params and states context:**

```python
@router.get("/jobs/map", response_class=HTMLResponse)
def jobs_map(
    request: Request,
    company: str = "", source: str = "", location: str = "", removed: str = "active",
    emailed: str = "", status: str = "", state: str = "",
    zip_code: str = Query("", alias="zip"), radius: str = "25",
):
    conn = request.app.state.conn
    source_names = db.list_job_source_names(conn)
    locations = db.list_job_locations(conn)
    states = db.list_job_states(conn)
    return templates.TemplateResponse(request, "jobs_map.html", {
        "source_names": source_names, "locations": locations, "states": states,
        "filters": {
            "company": company, "source": source, "location": location,
            "removed": removed, "emailed": emailed, "status": status,
            "state": state, "zip": zip_code, "radius": radius,
        },
    })
```

**`/jobs/map/data` (GET) — add geocoding:**

```python
@router.get("/jobs/map/data")
def jobs_map_data(
    request: Request,
    company: str = "", source: str = "", location: str = "", removed: str = "active",
    emailed: str = "", status: str = "", state: str = "",
    zip_code: str = Query("", alias="zip"), radius: str = "25",
):
    conn = request.app.state.conn
    zip_lat: float | None = None
    zip_lng: float | None = None
    radius_miles: float | None = None
    if zip_code:
        geocoder = get_geocoder()
        result = geocoder.geocode(zip_code)
        if result:
            zip_lat, zip_lng = result.lat, result.lng
            radius_miles = float(radius) if radius in ("10", "25", "50", "100") else 25.0
    settings = db.get_settings(conn)
    hide_not_interested = settings is None or settings["hide_not_interested_on_map"]
    exclude_status = "not_interested" if hide_not_interested and status != "not_interested" else None
    rows = db.list_mappable_jobs(
        conn, company=company or None, source_name=source or None, location=location or None,
        removed=removed or None, emailed=emailed or None, status=status or None,
        exclude_status=exclude_status,
        state=state or None,
        zip_lat=zip_lat, zip_lng=zip_lng, radius_miles=radius_miles,
    )
    grouped: dict[tuple, dict] = {}
    for row in rows:
        key = (row["lat"], row["lng"])
        entry = grouped.setdefault(key, {
            "lat": row["lat"], "lng": row["lng"], "display_name": row["display_name"], "jobs": [],
        })
        entry["jobs"].append({
            "key": row["key"], "title": row["title"], "company": row["company"],
            "url": safe_url_scheme(row["url"]),
            "is_overridden": row["is_overridden"],
        })
    return list(grouped.values())
```

- [ ] **Step 4: Run the new route tests**

```
pytest tests/web/test_jobs.py -k "state_filter or zip_filter or zip_shown or map_data_state or map_data_zip or map_page_includes" -v
```

Expected: most PASS; template tests may still fail until Task 3 adds the controls.

- [ ] **Step 5: Run the full test suite**

```
pytest -v
```

Expected: all PASS. Fix any regressions before continuing.

- [ ] **Step 6: Commit**

```bash
git add app/web/routes_jobs.py tests/web/test_jobs.py
git commit -m "feat(routes): add state and zip/radius filter params to jobs endpoints"
```

---

### Task 3: UI — State dropdown and Zip/radius inputs in templates

**Files:**
- Modify: `app/web/templates/jobs.html`
- Modify: `app/web/templates/jobs_map.html`
- Test: `tests/web/test_jobs.py` (template integration — some tests from Task 2 will now pass)

**Interfaces:**
- Consumes: `filters.state`, `filters.zip`, `filters.radius`, `filters.zip_error`, `states` (list of strings) from template context

---

- [ ] **Step 1: Write failing template tests**

Add to `tests/web/test_jobs.py`:

```python
# ── Template controls ────────────────────────────────────────────────────────

def test_jobs_page_has_state_dropdown(client):
    resp = client.get("/jobs")
    assert 'name="state"' in resp.text
    assert "All states" in resp.text


def test_jobs_page_state_option_marked_selected_when_active(client):
    conn = client.app.state.conn
    db.save_jobs(conn, [make_job(key="a", location="Chicago, IL")], db.start_run(conn))
    conn.execute(
        "UPDATE geocoded_locations SET status = 'resolved', region = 'Illinois' "
        "WHERE location = 'Chicago, IL'"
    )
    conn.commit()

    resp = client.get("/jobs?state=Illinois")

    assert '<option value="Illinois" selected' in resp.text


def test_jobs_page_has_zip_input(client):
    resp = client.get("/jobs")
    assert 'name="zip"' in resp.text


def test_jobs_page_has_radius_dropdown_with_defaults(client):
    resp = client.get("/jobs")
    assert 'name="radius"' in resp.text
    for mi in ("10", "25", "50", "100"):
        assert f'value="{mi}"' in resp.text


def test_jobs_page_zip_value_preserved_in_form(client):
    from unittest.mock import patch
    with patch("app.geocoding.nominatim.requests.get",
               return_value=_fake_geocode_response()):
        resp = client.get("/jobs?zip=60148&radius=50")

    assert 'value="60148"' in resp.text
    assert 'value="50" selected' in resp.text or '>50 mi<' in resp.text


def test_jobs_page_zip_error_warning_shown_on_failed_geocode(client):
    from unittest.mock import Mock, patch
    empty_resp = Mock()
    empty_resp.raise_for_status = Mock()
    empty_resp.json.return_value = []
    with patch("app.geocoding.nominatim.requests.get", return_value=empty_resp):
        resp = client.get("/jobs?zip=00000")

    assert "Could not resolve" in resp.text


def test_jobs_page_no_zip_error_warning_when_zip_not_provided(client):
    resp = client.get("/jobs")
    assert "Could not resolve" not in resp.text


def test_jobs_map_page_has_state_dropdown(client):
    resp = client.get("/jobs/map")
    assert 'name="state"' in resp.text
    assert "All states" in resp.text


def test_jobs_map_page_has_zip_input(client):
    resp = client.get("/jobs/map")
    assert 'name="zip"' in resp.text


def test_jobs_map_page_has_radius_dropdown(client):
    resp = client.get("/jobs/map")
    assert 'name="radius"' in resp.text


def test_jobs_map_clear_filters_shown_when_state_active(client):
    resp = client.get("/jobs/map?state=Illinois")
    assert "Clear filters" in resp.text


def test_jobs_map_clear_filters_shown_when_zip_active(client):
    from unittest.mock import patch
    with patch("app.geocoding.nominatim.requests.get",
               return_value=_fake_geocode_response()):
        resp = client.get("/jobs/map?zip=60148")
    assert "Clear filters" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/web/test_jobs.py -k "has_state or has_zip or has_radius or zip_value or zip_error or map_page_has" -v
```

Expected: various assertion failures because the template doesn't have the controls yet.

- [ ] **Step 3: Add State dropdown and Zip/radius inputs to `jobs.html`**

In `app/web/templates/jobs.html`, find the closing `</label>` of the **Location** filter and add the new controls immediately after it (before the Status `<label>`):

**Before** (the Location block ends with):
```html
  </label>
  <label>Status
```

**After:**
```html
  </label>
  <label>State
    <select name="state">
      <option value="">All states</option>
      {% for s in states %}
      <option value="{{ s }}" {% if filters.state == s %}selected{% endif %}>{{ s }}</option>
      {% endfor %}
    </select>
  </label>
  <label>Near zip/city
    <input type="text" name="zip" value="{{ filters.zip }}" placeholder="e.g. 60148">
  </label>
  <label>Radius
    <select name="radius">
      {% for mi in [10, 25, 50, 100] %}
      <option value="{{ mi }}" {% if (filters.radius | int) == mi %}selected{% endif %}>{{ mi }} mi</option>
      {% endfor %}
    </select>
  </label>
  {% if filters.zip_error %}
  <p class="filter-warning" role="alert">Could not resolve that location — radius filter not applied.</p>
  {% endif %}
  <label>Status
```

Also update the "Clear filters" condition line. **Before:**
```html
  {% if filters.company or filters.source or filters.location or filters.removed != "active" or filters.emailed or filters.status or filters.duplicates %}<a href="/jobs">Clear filters</a>{% endif %}
```

**After:**
```html
  {% if filters.company or filters.source or filters.location or filters.removed != "active" or filters.emailed or filters.status or filters.duplicates or filters.state or filters.zip %}<a href="/jobs">Clear filters</a>{% endif %}
```

- [ ] **Step 4: Add same controls to `jobs_map.html`**

In `app/web/templates/jobs_map.html`, after the closing `</label>` of the **Location** block and before `<label>Status`:

```html
  </label>
  <label>State
    <select name="state">
      <option value="">All states</option>
      {% for s in states %}
      <option value="{{ s }}" {% if filters.state == s %}selected{% endif %}>{{ s }}</option>
      {% endfor %}
    </select>
  </label>
  <label>Near zip/city
    <input type="text" name="zip" value="{{ filters.zip }}" placeholder="e.g. 60148">
  </label>
  <label>Radius
    <select name="radius">
      {% for mi in [10, 25, 50, 100] %}
      <option value="{{ mi }}" {% if (filters.radius | int) == mi %}selected{% endif %}>{{ mi }} mi</option>
      {% endfor %}
    </select>
  </label>
  <label>Status
```

Update the "Clear filters" condition in `jobs_map.html`. **Before:**
```html
  {% if filters.company or filters.source or filters.location or filters.removed != "active" or filters.emailed or filters.status %}<a href="/jobs/map">Clear filters</a>{% endif %}
```

**After:**
```html
  {% if filters.company or filters.source or filters.location or filters.removed != "active" or filters.emailed or filters.status or filters.state or filters.zip %}<a href="/jobs/map">Clear filters</a>{% endif %}
```

- [ ] **Step 5: Run all new template tests**

```
pytest tests/web/test_jobs.py -v
```

Expected: all tests PASS, including the state/zip tests from Task 2 that were failing due to missing template controls.

- [ ] **Step 6: Run the full test suite**

```
pytest -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add app/web/templates/jobs.html app/web/templates/jobs_map.html tests/web/test_jobs.py
git commit -m "feat(ui): add state dropdown and zip/radius filter controls to jobs and map pages"
```

---

### Task 4: Housekeeping — ROADMAP, CHANGELOG, version bump, GitHub issues

**Files:**
- Modify: `ROADMAP.md`
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml`

---

- [ ] **Step 1: Add job-type adapter availability notes to `ROADMAP.md`**

In `ROADMAP.md`, add a new item in the **Features** section (after the existing auto-dedup and official API items):

```markdown
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
  extraction for supported platforms, and a filter UI control.
```

- [ ] **Step 2: Add a CHANGELOG entry for 0.45.0**

At the top of the `## [Unreleased]` section in `CHANGELOG.md`, add:

```markdown
## [0.45.0] — 2026-08-25

### Added

- **State filter:** a State dropdown on the Jobs page and Jobs Map filters results by
  geocoded region (`geocoded_locations.region` as set by Nominatim). Populated dynamically
  from already-resolved job locations — no extra geocoding required.
- **Zip/location + radius filter:** a text input (zip code or city) paired with a miles
  dropdown (10 / 25 / 50 / 100 mi) on the Jobs page and Jobs Map. The input is geocoded
  on each filtered request via the existing Nominatim geocoder; jobs are filtered by
  haversine distance against their geocoded lat/lng. An inline warning is shown when the
  location string cannot be resolved, and the radius filter is skipped gracefully.
  Haversine distance is computed inside SQLite via a registered Python scalar function
  (`haversine_miles`) registered at DB init time.
```

- [ ] **Step 3: Bump version in `pyproject.toml`**

Change:
```toml
version = "0.44.0"
```
To:
```toml
version = "0.45.0"
```

- [ ] **Step 4: Create a GitHub issue for multi-select filters**

```bash
gh issue create \
  --title "Allow multi-select on filter dropdowns (source, state, status)" \
  --body "Currently all filters accept a single value. Allow selecting multiple values simultaneously — e.g. filter by two source names, or two states at once.

**Scope:**
- URL params: repeated keys (e.g. \`?source=A&source=B\`) or comma-separated values
- DB filter: replace \`= ?\` with \`IN (?, ...)\` for multi-value fields
- UI: multi-select \`<select multiple>\` elements or checkboxes in a dropdown

**Priority candidates:** Source name, State, Job status

Deferred from feat/location-filters (0.45.0)."
```

- [ ] **Step 5: Run the full test suite one final time**

```
pytest -v
```

Expected: all PASS.

- [ ] **Step 6: Run linting**

```
ruff check app tests
```

Expected: no new warnings. Fix any that appear.

- [ ] **Step 7: Commit housekeeping**

```bash
git add ROADMAP.md CHANGELOG.md pyproject.toml
git commit -m "chore: bump version to 0.45.0, document job-type adapter availability"
```

---

### Task 5: Commit design doc and open the PR

- [ ] **Step 1: Commit the spec and plan (if not already committed)**

```bash
git add docs/superpowers/specs/2026-08-25-location-filters-design.md
git add docs/superpowers/plans/2026-08-25-location-filters.md
git commit -m "docs: add location-filters design spec and implementation plan"
```

- [ ] **Step 2: Push the branch**

```bash
git push -u origin feat/location-filters
```

- [ ] **Step 3: Open the PR**

```bash
gh pr create \
  --base master \
  --title "feat(filters): state dropdown + zip/radius filter (#NN)" \
  --body "## Summary

- Adds a **State** dropdown to the Jobs page and Jobs Map, populated from geocoded \`region\` values already stored in \`geocoded_locations\`. No extra geocoding or schema changes required.
- Adds a **Zip/location + radius** filter (10/25/50/100 mi) to the Jobs page and Jobs Map. The zip is geocoded inline on each request using the existing Nominatim geocoder; distance filtering uses a \`haversine_miles\` Python function registered as a SQLite scalar at \`init_db\` time.
- Handles unresolvable zip inputs gracefully: shows an inline warning and returns unfiltered results.
- Deferred **multi-select filters** as a new GitHub issue.
- Documented **job-type** adapter availability in ROADMAP.md (not implemented).

## Test plan

- [ ] \`pytest -v\` passes — all new DB tests (haversine function, state filter, zip/radius filter) and route/template tests green
- [ ] \`ruff check app tests\` clean
- [ ] Manual: visit \`/jobs\`, pick a state, confirm results narrow
- [ ] Manual: enter a zip code, pick a radius, confirm only nearby jobs shown
- [ ] Manual: enter an invalid zip, confirm warning appears and all jobs still shown
- [ ] Manual: \`/jobs/map\` — state and zip/radius filter the map pins
- [ ] Manual: clear filters link appears when state or zip is active

## Version

\`0.44.0\` → \`0.45.0\`"
```
