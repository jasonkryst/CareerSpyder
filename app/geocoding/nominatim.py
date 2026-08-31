import re

import requests

from app.geocoding.base import GeocodeResult

_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "CareerSpyder/1.0 (+https://github.com/jasonkryst/CareerSpyder)"
_US_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")


class NominatimGeocoder:
    name = "nominatim"
    min_interval_seconds = 1.0

    def geocode(self, location: str) -> GeocodeResult | None:
        query = location.strip()
        if _US_ZIP_RE.match(query):
            # Use structured params for US ZIP codes so Nominatim searches its
            # postal-code index rather than free-text (which fails on bare numbers).
            params = {
                "postalcode": query[:5],
                "countrycodes": "us",
                "format": "jsonv2",
                "limit": "1",
                "addressdetails": "1",
            }
        else:
            params = {"q": query, "format": "jsonv2", "limit": "1", "addressdetails": "1"}
        try:
            response = requests.get(
                _SEARCH_URL,
                params=params,
                headers={"User-Agent": _USER_AGENT},
                timeout=10,
            )
            response.raise_for_status()
            results = response.json()
        except requests.RequestException:
            return None

        if not results:
            return None

        result = results[0]
        address = result.get("address", {})
        return GeocodeResult(
            display_name=result.get("display_name", location),
            city=address.get("city") or address.get("town") or address.get("village"),
            region=address.get("state"),
            country=address.get("country"),
            lat=float(result["lat"]),
            lng=float(result["lon"]),
        )
