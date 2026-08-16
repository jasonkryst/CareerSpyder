from urllib.parse import urlencode

from fastapi.responses import RedirectResponse


def flash_redirect(path: str, message: str, status_code: int = 303) -> RedirectResponse:
    query = urlencode({"flash": message})
    return RedirectResponse(url=f"{path}?{query}", status_code=status_code)
