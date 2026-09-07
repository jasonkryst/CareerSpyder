from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Blocks cross-origin state-changing requests using the Origin/
    Sec-Fetch-Site headers modern browsers attach even to plain <form>
    POSTs. CareerSpyder has no auth or cookies (trusted-network-only, per
    ROADMAP.md), so a per-user CSRF token isn't a natural fit -- this closes
    the gap without adding any session/cookie infrastructure. A request
    carrying neither header (older browsers, direct API/script use on the
    trusted network) is allowed through, matching that threat model.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in _UNSAFE_METHODS and not self._is_same_origin(request):
            return PlainTextResponse("Cross-origin request blocked", status_code=403)
        return await call_next(request)

    @staticmethod
    def _is_same_origin(request: Request) -> bool:
        sec_fetch_site = request.headers.get("sec-fetch-site")
        if sec_fetch_site is not None:
            return sec_fetch_site in ("same-origin", "none")
        origin = request.headers.get("origin")
        if origin is None:
            return True
        return origin == f"{request.url.scheme}://{request.url.netloc}"
