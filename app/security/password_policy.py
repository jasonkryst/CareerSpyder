"""New-password policy (#269), modelled on NIST SP 800-63B section 3.1.1.2:

- a minimum length (``PASSWORD_MIN_LENGTH``, default and floor 8), counted in
  characters, with no composition rules (no "must contain a digit");
- bcrypt's 72-byte ceiling as the only maximum;
- rejection of repetitive/sequential strings, the bundled SecLists top-10k
  common passwords, and context-specific words (the app name, the user's
  username and email local part);
- optionally (``CHECK_BREACHED_PASSWORDS=true``, off by default so installs
  with no outbound internet never try) a Have I Been Pwned "range" lookup.

The HIBP lookup uses k-anonymity: only the first 5 hex characters of the
password's SHA-1 are sent; the API returns every breached suffix sharing
that prefix and the match happens locally. ``Add-Padding`` makes every
response a similar size so the prefix's real bucket size isn't observable.
If the API can't be reached the check fails *open* (the password is
accepted on the local rules alone) and a warning is logged -- an HIBP
outage must not lock anyone out of registration or a password reset.

The HIBP URL is a fixed constant, never user-supplied, so it doesn't go
through ``app/security/ssrf_guard.py``. Tests swap ``_http_get`` or pass
``http_get=`` -- they never reach the real API.

Every user-facing string lives in ``MESSAGES`` so a future i18n layer has
one place to translate.
"""
import functools
import hashlib
import itertools
import logging
import os
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

NIST_MIN_LENGTH = 8
# bcrypt hashes only the first 72 bytes; leave headroom for multi-byte chars.
MAX_CONFIGURABLE_MIN_LENGTH = 64
MAX_PASSWORD_BYTES = 72

HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/"
HIBP_TIMEOUT_SECONDS = 3
_APP_NAME = "careerspyder"
# Containment needs 3+ chars, or a 1-2 letter username would reject nearly
# every password; an exact match is always rejected.
_CONTEXT_MIN_LEN = 3

MESSAGES = {
    "required": "Password is required.",
    "too_short": "Password must be at least {n} characters. A passphrase of a few "
                 "unrelated words is easy to remember and hard to guess.",
    "too_long": "Password must be at most 72 bytes.",
    "mismatch": "Passwords do not match.",
    "common": "That password is one of the most common passwords and would be "
              "guessed almost immediately. Please choose something less predictable.",
    "pattern": "That password is a repeated character or a simple sequence "
               "(like 'abcdefgh' or '87654321'). Please choose something less predictable.",
    "app_name": "Password must not contain the site name (CareerSpyder).",
    "username": "Password must not contain your username.",
    "email": "Password must not contain your email address.",
    "breached": "This password has appeared in a known data breach ({count} times in "
                "the Have I Been Pwned database), so attackers try it early. Please "
                "choose a different password. Your password itself was never sent "
                "anywhere: only the first 5 characters of its SHA-1 hash were used "
                "for the lookup.",
}

# The SecLists "10k most common" list (MIT; see docs/third-party-notices.md),
# bundled unmodified so the check works with no egress. The HIBP lookup,
# when enabled, covers the long tail.
_COMMON_PASSWORDS_FILE = Path(__file__).parent / "wordlists" / "common-passwords.txt"


@functools.cache
def _common_passwords() -> frozenset[str]:
    text = _COMMON_PASSWORDS_FILE.read_text(encoding="utf-8")
    return frozenset(line.strip().casefold() for line in text.splitlines() if line.strip())


def breach_check_enabled() -> bool:
    return os.environ.get("CHECK_BREACHED_PASSWORDS", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def min_length() -> int:
    raw = os.environ.get("PASSWORD_MIN_LENGTH", "").strip()
    if not raw:
        return NIST_MIN_LENGTH
    try:
        value = int(raw)
    except ValueError:
        # Don't echo the raw value: it's config, but scanners (rightly) treat
        # anything named PASSWORD_* as possibly secret.
        logger.warning("PASSWORD_MIN_LENGTH is not an integer; using %d.", NIST_MIN_LENGTH)
        return NIST_MIN_LENGTH
    clamped = max(NIST_MIN_LENGTH, min(value, MAX_CONFIGURABLE_MIN_LENGTH))
    if clamped != value:
        logger.warning("PASSWORD_MIN_LENGTH=%d is outside %d-%d; using %d.",
                       value, NIST_MIN_LENGTH, MAX_CONFIGURABLE_MIN_LENGTH, clamped)
    return clamped


def _user_agent() -> str:
    try:
        return f"CareerSpyder/{version('careerspyder')}"
    except PackageNotFoundError:
        return "CareerSpyder"


def _default_http_get(url: str, **kwargs: Any) -> Any:
    return requests.get(url, **kwargs)  # noqa: S113 -- timeout is always passed


_http_get: Callable[..., Any] = _default_http_get


def pwned_count(password: str, *, http_get: Callable[..., Any] | None = None) -> int | None:
    """How many times HIBP has seen ``password`` in a breach (0 = never), or
    ``None`` if the lookup failed. Only the 5-char SHA-1 prefix is sent."""
    # SHA-1 is the HIBP range API's bucketing key, not password storage (that's
    # bcrypt, in app/web/auth.py); the digest is never persisted or logged.
    digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    get = http_get or _http_get
    try:
        resp = get(
            HIBP_RANGE_URL + prefix,
            headers={"Add-Padding": "true", "User-Agent": _user_agent()},
            timeout=HIBP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        body = resp.text
    except (requests.RequestException, OSError) as exc:
        logger.warning("Have I Been Pwned range lookup failed (%s); accepting the "
                       "password on local rules only.", type(exc).__name__)
        return None
    for line in body.splitlines():
        candidate, _, count = line.strip().partition(":")
        if candidate.upper() != suffix:
            continue
        try:
            return int(count)  # padding entries carry a count of 0
        except ValueError:
            continue
    return 0


def _is_repetitive_or_sequential(password: str) -> bool:
    if len(set(password)) == 1:
        return True
    steps = {ord(b) - ord(a) for a, b in itertools.pairwise(password)}
    return steps in ({1}, {-1})


def _contains_context(folded_password: str, word: str) -> bool:
    w = word.strip().casefold()
    if not w:
        return False
    return folded_password == w or (len(w) >= _CONTEXT_MIN_LEN and w in folded_password)


def check_new_password(
    password: str,
    confirm: str,
    *,
    username: str = "",
    email: str = "",
    http_get: Callable[..., Any] | None = None,
) -> str | None:
    """The first reason ``password`` is unacceptable as a new password, or
    ``None`` if it's fine. Cheap local checks run first; the HIBP lookup
    (network) runs only if they all pass and the check is enabled."""
    if not password:
        return MESSAGES["required"]
    n = min_length()
    if len(password) < n:
        return MESSAGES["too_short"].format(n=n)
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        return MESSAGES["too_long"]
    if password != confirm:
        return MESSAGES["mismatch"]

    folded = password.casefold()
    if _is_repetitive_or_sequential(folded):
        return MESSAGES["pattern"]
    if folded in _common_passwords():
        return MESSAGES["common"]
    if _APP_NAME in folded:
        return MESSAGES["app_name"]
    if _contains_context(folded, username):
        return MESSAGES["username"]
    if _contains_context(folded, email.strip().split("@", 1)[0]):
        return MESSAGES["email"]

    if breach_check_enabled():
        count = pwned_count(password, http_get=http_get)
        if count:
            return MESSAGES["breached"].format(count=f"{count:,}")
    return None
