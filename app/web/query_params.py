from urllib.parse import urlencode

from starlette.requests import Request


def query_url(request: Request, path: str, **overrides: str | int | None) -> str:
    params = dict(request.query_params)
    for key, value in overrides.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = str(value)
    query = urlencode(params)
    return f"{path}?{query}" if query else path


def sort_url(request: Request, path: str, field: str) -> str:
    current_field = request.query_params.get("sort", "")
    current_dir = request.query_params.get("dir", "")
    if current_field == field:
        new_dir = "asc" if current_dir == "desc" else "desc"
    else:
        new_dir = "asc"
    return query_url(request, path, sort=field, dir=new_dir, page=None)
