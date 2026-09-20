import logging
import time
from datetime import UTC, datetime

import psycopg

from app.geocoding.base import Geocoder, GeocoderTransientError

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def geocode_pending(conn: psycopg.Connection, geocoder: Geocoder) -> None:
    rows = conn.execute(
        "SELECT location FROM geocoded_locations WHERE status = 'pending'"
    ).fetchall()

    for i, (location,) in enumerate(rows):
        if i > 0:
            time.sleep(geocoder.min_interval_seconds)
        try:
            result = geocoder.geocode(location)
        except GeocoderTransientError:
            logger.warning("Transient geocoding error for %r; will retry next run", location)
            continue
        except Exception:
            logger.exception("Geocoding failed for location %r", location)
            result = None

        now = _now()
        if result is None:
            conn.execute(
                "UPDATE geocoded_locations SET status = 'failed', resolved_at = %s WHERE location = %s",
                (now, location),
            )
        else:
            conn.execute(
                "UPDATE geocoded_locations SET status = 'resolved', display_name = %s, city = %s, "
                "region = %s, country = %s, lat = %s, lng = %s, provider = %s, resolved_at = %s "
                "WHERE location = %s",
                (result.display_name, result.city, result.region, result.country,
                 result.lat, result.lng, geocoder.name, now, location),
            )
        conn.commit()
