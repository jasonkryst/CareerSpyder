from starlette.staticfiles import StaticFiles
from starlette.types import Scope

# Templates reference JS/CSS as /static/<file>?v={{ app_version }}, so a deploy
# (which bumps the version) changes the URL and a long max-age is safe.
_LONG_CACHE = "public, max-age=604800"
# Files fetched by a fixed, unversioned URL -- the web app manifest and the
# service worker's offline page -- must revalidate so a deploy reaches them.
_REVALIDATE = "no-cache"
_REVALIDATE_SUFFIXES = (".html", ".json")


class CachedStaticFiles(StaticFiles):
    """StaticFiles that sets an explicit Cache-Control (issue #167)."""

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304):
            response.headers["Cache-Control"] = (
                _REVALIDATE if path.endswith(_REVALIDATE_SUFFIXES) else _LONG_CACHE
            )
        return response
