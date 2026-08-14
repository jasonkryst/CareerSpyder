import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

_SAFE_URL_SCHEMES = {"http", "https"}

# C0 controls, space, DEL, and a range of Unicode whitespace/invisible code
# points that can split a dangerous scheme name (e.g. "javascript:") so
# urlparse fails to detect any scheme at all, letting the raw string through
# unchecked. Stripped only for scheme *detection* -- the original url is
# still what is returned once it is judged safe.
_SCHEME_NOISE = re.compile("[\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f\x20\x7f\xa0\u1680\u2028\u2029\u202f\u205f\u3000\ufeff\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u200b]")


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
    return plain[:limit].rstrip() + "\u2026"


def safe_url_scheme(url: str) -> str:
    cleaned = _SCHEME_NOISE.sub("", url)
    try:
        scheme = urlparse(cleaned).scheme.lower()
    except ValueError:
        return "#"
    if scheme and scheme not in _SAFE_URL_SCHEMES:
        return "#"
    return url
