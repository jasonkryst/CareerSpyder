import logging
import sqlite3
import time
from datetime import UTC, datetime

from app.geocoding.base import Geocoder

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def geocode_pending(conn: sqlite3.Connection, geocoder: Geocoder) -> None:
    rows = conn.execute(
        "SELECT location FROM geocoded_locations WHERE status = 'pending'"
    ).fetchall()

    for i, (location,) in enumerate(rows):
        if i > 0:
            time.sleep(geocoder.min_interval_seconds)
        try:
            result = geocoder.geocode(location)
        except Exception:
            logger.exception("Geocoding failed for location %r", location)
            result = None

        now = _now()
        if result is None:
            conn.execute(
                "UPDATE geocoded_locations SET status = 'failed', resolved_at = ? WHERE location = ?",
                (now, location),
            )
        else:
            conn.execute(
                "UPDATE geocoded_locations SET status = 'resolved', display_name = ?, city = ?, "
                "region = ?, country = ?, lat = ?, lng = ?, provider = ?, resolved_at = ? "
                "WHERE location = ?",
                (result.display_name, result.city, result.region, result.country,
                 result.lat, result.lng, geocoder.name, now, location),
            )
        conn.commit()
