import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# CareerSpyder has no auth (by design, trusted-network-only per ROADMAP.md) —
# these are defense-in-depth headers, not a substitute for that gate.
_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}


def _build_csp() -> str:
    # script-src/style-src allow 'unsafe-inline': base.html and source_form.html
    # have small inline <script> blocks and the app has no nonce plumbing.
    # This CSP's real value is frame-ancestors/object-src, not script whitelisting.
    script_src = "script-src 'self' 'unsafe-inline'"
    connect_src_directive = ""
    # Read per-request (not cached at import time) so GA_MEASUREMENT_ID can be
    # toggled per-test; in production the env var is set once at container
    # start anyway, so this costs nothing extra.
    if os.environ.get("GA_MEASUREMENT_ID"):
        script_src += " https://www.googletagmanager.com"
        connect_src_directive = (
            " connect-src 'self' https://*.google-analytics.com https://*.analytics.google.com;"
        )
    return (
        "default-src 'self'; img-src 'self' data: https://*.tile.openstreetmap.org; "
        f"style-src 'self' 'unsafe-inline'; {script_src};{connect_src_directive} "
        "frame-ancestors 'none'; object-src 'none'"
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for name, value in _HEADERS.items():
            response.headers[name] = value
        response.headers["Content-Security-Policy"] = _build_csp()
        return response
