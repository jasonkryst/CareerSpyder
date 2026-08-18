import os

from app.geocoding.base import Geocoder
from app.geocoding.nominatim import NominatimGeocoder

_PROVIDERS: dict[str, type] = {
    "nominatim": NominatimGeocoder,
}


def get_geocoder() -> Geocoder:
    provider = os.environ.get("GEOCODER_PROVIDER", "nominatim")
    try:
        provider_cls = _PROVIDERS[provider]
    except KeyError:
        raise ValueError(f"Unknown GEOCODER_PROVIDER: {provider!r}") from None
    return provider_cls()
