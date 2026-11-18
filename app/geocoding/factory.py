import os

from app.geocoding.base import Geocoder
from app.geocoding.nominatim import NominatimGeocoder

_PROVIDERS: dict[str, type] = {
    "nominatim": NominatimGeocoder,
}


def get_geocoder() -> Geocoder:
    # `or`, not a .get() default: docker-compose passes an unset .env value
    # through as "" (`${GEOCODER_PROVIDER:-}`), which must still mean default.
    provider = os.environ.get("GEOCODER_PROVIDER") or "nominatim"
    try:
        provider_cls = _PROVIDERS[provider]
    except KeyError:
        raise ValueError(f"Unknown GEOCODER_PROVIDER: {provider!r}") from None
    return provider_cls()
