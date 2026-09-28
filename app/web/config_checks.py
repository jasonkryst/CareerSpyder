"""Startup/configuration checks that must fail closed (audit 2026-09-27 H5, M5, M6)."""
import os

# Values that are published in this repo (code default, .env.example) or
# obviously placeholders -- a session/reset-token key must never be one.
_INSECURE_SECRET_KEYS = frozenset({
    "", "dev-insecure-secret-change-me", "change-me-generate-a-real-secret", "change-me",
})
_MIN_SECRET_KEY_LENGTH = 32


def validate_secret_key(key: str) -> None:
    if key in _INSECURE_SECRET_KEYS or len(key) < _MIN_SECRET_KEY_LENGTH:
        raise RuntimeError(
            "SECRET_KEY is missing, a published placeholder, or shorter than "
            f"{_MIN_SECRET_KEY_LENGTH} characters. Generate one with: "
            'python -c "import secrets; print(secrets.token_hex(32))"'
        )


def public_base_url() -> str | None:
    """The canonical external URL, or None. Security-sensitive links (password
    reset, invites) are built from this, never from the request's Host header."""
    value = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    return value or None


def session_cookie_secure(base_url: str | None) -> bool:
    # Only mark the cookie Secure when the site is actually served over HTTPS;
    # a plain-HTTP LAN deployment would otherwise be unable to log in.
    return bool(base_url and base_url.startswith("https://"))
