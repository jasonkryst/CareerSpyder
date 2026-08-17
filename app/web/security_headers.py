from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# CareerSpyder has no auth (by design, trusted-network-only per ROADMAP.md) —
# these are defense-in-depth headers, not a substitute for that gate.
_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    # script-src/style-src allow 'unsafe-inline': base.html and source_form.html
    # have small inline <script> blocks and the app has no nonce plumbing.
    # This CSP's real value is frame-ancestors/object-src, not script whitelisting.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'; object-src 'none'"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for name, value in _HEADERS.items():
            response.headers[name] = value
        return response
