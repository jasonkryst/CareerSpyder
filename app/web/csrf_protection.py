from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Blocks cross-origin state-changing requests using the Origin/
    Sec-Fetch-Site headers modern browsers attach even to plain <form>
    POSTs.  This complements the SameSite=Lax session cookie: a cross-origin
    POST from a malicious page is blocked even though the browser would send
    the cookie.  A request carrying neither header (non-browser API clients,
    older browsers) is allowed through because it carries no session cookie
    and therefore has no session to abuse.
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
