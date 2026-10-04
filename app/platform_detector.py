from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlparse

import requests

from app.security.ssrf_guard import UnsafeUrlError, safe_get

logger = logging.getLogger(__name__)

# Form field name for the primary input of each adapter type.
# These are template names (e.g. "infor_url"), not model field names.
_FORM_FIELD: dict[str, str] = {
    "greenhouse": "board_token",
    "lever": "board_token",
    "linkedin": "url",
    "indeed": "url",
    "generic_html": "url",
    "infor": "infor_url",
    "healthcaresource": "site_id",
    "talentbrew": "base_url",
    "workday": "career_site_url",
    "phenompeople": "phenompeople_career_site_url",
    "findly": "findly_career_site_url",
}

SUPPORTED_PLATFORMS = frozenset(_FORM_FIELD)


@dataclass
class DetectionResult:
    platform_type: str | None      # adapter key, or None if unrecognized
    confidence: str                # "url" | "page" | "none"
    fields: dict[str, str] = field(default_factory=dict)  # form field → prefill value
    message: str = ""


# URL rules: (compiled pattern, platform type, capture-group name for the primary field)
# More specific patterns first — greenhouse API URL before generic boards.greenhouse.io.
_URL_RULES: list[tuple[re.Pattern[str], str, str | None]] = [
    (re.compile(r"boards-api\.greenhouse\.io/v1/boards/(?P<board_token>[^/?#]+)", re.IGNORECASE), "greenhouse", "board_token"),
    (re.compile(r"boards\.greenhouse\.io/(?P<board_token>[^/?#]+)", re.IGNORECASE), "greenhouse", "board_token"),
    (re.compile(r"api\.lever\.co/v0/postings/(?P<board_token>[^/?#]+)", re.IGNORECASE), "lever", "board_token"),
    (re.compile(r"jobs\.lever\.co/(?P<board_token>[^/?#]+)", re.IGNORECASE), "lever", "board_token"),
    (re.compile(r"linkedin\.com/(?:jobs|company)/", re.IGNORECASE), "linkedin", None),
    (re.compile(r"(?:www\.)?indeed\.com/", re.IGNORECASE), "indeed", None),
    (re.compile(r"[\w-]+\.myworkdayjobs\.com/", re.IGNORECASE), "workday", None),
    (re.compile(r"[\w-]+\.myworkday\.com/", re.IGNORECASE), "workday", None),
    (re.compile(r"pm\.healthcaresource\.com/(?:cs|CS)/(?P<site_id>[^/?#]+)", re.IGNORECASE), "healthcaresource", "site_id"),
    (re.compile(r"[\w.-]+\.phenompeople\.com/", re.IGNORECASE), "phenompeople", None),
    (re.compile(r"findly\.com(?:\.au)?/", re.IGNORECASE), "findly", None),
]

# Page-content signatures: (lowercase substring, platform type).
# More specific strings first to avoid false positives.
_PAGE_SIGNATURES: list[tuple[str, str]] = [
    ("boards-api.greenhouse.io", "greenhouse"),
    ("api.lever.co/v0/postings", "lever"),
    ("jobs.lever.co", "lever"),
    ("myworkdayjobs.com", "workday"),
    ("myworkday.com/wday/cxs", "workday"),
    ("talentbrew.com", "talentbrew"),
    ("pm.healthcaresource.com", "healthcaresource"),
    ("phenompeople.com", "phenompeople"),
    ("jobsapi-internal.m-cloud.io", "findly"),
    ("infortalentscience.com", "infor"),
    ("infor talent science", "infor"),
]

_REPORT_REPO = "jasonkryst/CareerSpyder"
_REPORT_LABELS = ["platform-request"]
_GITHUB_API = "https://api.github.com"
_NEW_ISSUE_URL = f"https://github.com/{_REPORT_REPO}/issues/new"
_USER_AGENT = "CareerSpyder/1.8 (platform-detector; +https://github.com/jasonkryst/CareerSpyder)"


def detect(url: str, *, http_get=safe_get) -> DetectionResult:
    """Identify the HR platform at `url`.

    Tries URL-pattern matching first (no network).  Falls back to fetching
    the page and scanning for known platform signatures.  The result's
    `fields` dict is keyed by template form-field names so callers can
    pre-fill the Add Source form directly.
    """
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return DetectionResult(None, "none", {}, "Invalid URL")

    if parsed.scheme not in ("http", "https"):
        return DetectionResult(None, "none", {}, "URL must start with http:// or https://")
    if not parsed.netloc:
        return DetectionResult(None, "none", {}, "URL has no host")

    # 1. URL-pattern pass — no network call
    for pattern, ptype, capture_name in _URL_RULES:
        m = pattern.search(url)
        if m:
            return DetectionResult(ptype, "url", _build_fields(ptype, url, m, capture_name), f"Detected {ptype}")

    # 2. Page-content pass — uses guarded http_get (SSRF-safe by default)
    try:
        resp = http_get(url, timeout=15, headers={"User-Agent": _USER_AGENT})
    except UnsafeUrlError:
        return DetectionResult(None, "none", {}, "URL points to a private or internal address")
    except Exception:  # noqa: BLE001
        return DetectionResult(None, "none", {}, "Could not fetch page to detect platform")

    html_lower = resp.text.lower()
    for signature, ptype in _PAGE_SIGNATURES:
        if signature in html_lower:
            return DetectionResult(ptype, "page", _build_fields(ptype, url, None, None), f"Detected {ptype} from page content")

    return DetectionResult(None, "none", {}, "Platform not recognized")


def _build_fields(
    ptype: str, url: str, match: re.Match[str] | None, capture_name: str | None
) -> dict[str, str]:
    """Return the form-field prefill dict for the detected platform."""
    form_field = _FORM_FIELD.get(ptype)
    if not form_field:
        return {}
    # Token fields (board_token, site_id) are extracted from the URL pattern.
    if capture_name and match:
        try:
            return {form_field: match.group(capture_name)}
        except IndexError:
            pass
    # URL-valued fields: prefill with the submitted URL.
    return {form_field: url}


def report_unsupported(url: str, *, http_post=requests.post) -> dict[str, str | None]:
    """File a GitHub issue requesting support for an unrecognized platform.

    Returns {"issue_url": <url>} when GITHUB_TOKEN is set and the API call
    succeeds, or {"new_issue_url": <prefilled new-issue URL>} as a fallback.
    Raises requests.HTTPError on API failure.
    """
    token = os.environ.get("GITHUB_TOKEN")
    domain = urlparse(url).netloc or url
    title = f"Platform request: {domain}"
    body = (
        "A CareerSpyder user pasted a URL that the platform detector did not recognize.\n\n"
        f"**URL:** `{url}`\n\n"
        "If this is a job board that CareerSpyder should support, please consider adding an adapter.\n\n"
        "_Filed automatically by the source-add platform detector._"
    )

    if not token:
        params = urlencode({"title": title, "body": body, "labels": ",".join(_REPORT_LABELS)})
        return {"issue_url": None, "new_issue_url": f"{_NEW_ISSUE_URL}?{params}"}

    resp = http_post(
        f"{_GITHUB_API}/repos/{_REPORT_REPO}/issues",
        json={"title": title, "body": body, "labels": _REPORT_LABELS},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return {"issue_url": resp.json()["html_url"], "new_issue_url": None}
