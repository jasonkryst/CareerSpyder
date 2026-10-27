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


def remove_filter_url(request: Request, path: str, *keys: str) -> str:
    """Build a URL identical to the current one but with every value for
    each given key removed entirely -- used for an active-filter chip's "x".
    Unlike query_url, this is multi-value-safe: it rebuilds from
    `multi_items()` instead of `dict(query_params)`, so an unrelated
    multi-valued param (e.g. state=IL&state=NY) isn't collapsed to its last
    value. Also drops `page`, since removing a filter changes the result set."""
    pairs = [(k, v) for k, v in request.query_params.multi_items() if k not in keys and k != "page"]
    query = urlencode(pairs)
    return f"{path}?{query}" if query else path


def remove_filter_value_url(request: Request, path: str, key: str, value: str) -> str:
    """Like remove_filter_url, but removes only one value from a
    multi-valued key (e.g. one selected state out of several), leaving its
    other values intact."""
    pairs = [
        (k, v) for k, v in request.query_params.multi_items()
        if k != "page" and not (k == key and v == value)
    ]
    query = urlencode(pairs)
    return f"{path}?{query}" if query else path


def sort_url(request: Request, path: str, field: str) -> str:
    current_field = request.query_params.get("sort", "")
    current_dir = request.query_params.get("dir", "")
    if current_field == field:
        new_dir = "asc" if current_dir == "desc" else "desc"
    else:
        new_dir = "asc"
    return query_url(request, path, sort=field, dir=new_dir, page=None)
