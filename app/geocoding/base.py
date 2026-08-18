from dataclasses import dataclass
from typing import Protocol


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
