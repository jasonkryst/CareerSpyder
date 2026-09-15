from dataclasses import dataclass
from typing import Protocol


class GeocoderTransientError(Exception):
    """Raised by a Geocoder when a network error makes the result unreliable.

    Callers should treat the location as still-pending rather than permanently
    failed, so it will be retried on the next geocoding pass.
    """


@dataclass
class GeocodeResult:
    display_name: str
    city: str | None
    region: str | None
    country: str | None
    lat: float
    lng: float


class Geocoder(Protocol):
    name: str
    min_interval_seconds: float

    def geocode(self, location: str) -> GeocodeResult | None: ...
