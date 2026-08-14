import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

_SAFE_URL_SCHEMES = {"http", "https"}


def to_summary(text: str | None, limit: int = 250) -> str | None:
    if not text:
        return None
    plain = BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)
    plain = re.sub(r"\s+", " ", plain).strip()
    plain = re.sub(r"\s+([.,!?;:])", r"\1", plain)
    if not plain:
        return None
    if len(plain) <= limit:
        return plain
    return plain[:limit].rstrip() + "…"


def safe_url_scheme(url: str) -> str:
    try:
        scheme = urlparse(url).scheme.lower()
    except ValueError:
        return "#"
    if scheme and scheme not in _SAFE_URL_SCHEMES:
        return "#"
    return url
