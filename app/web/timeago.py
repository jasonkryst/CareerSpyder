"""Jinja2 filter: convert an ISO-8601 datetime string to a human-readable
relative string such as "3 hours ago" or "just now".

The filter is registered in app.web.templating and used in templates as
``{{ value | timeago }}``.
"""

from datetime import UTC, datetime


def timeago(value: str | None) -> str:
    if value is None:
        return ""
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return str(value)
    now = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        m = seconds // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if seconds < 86400:
        h = seconds // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    if seconds < 7 * 86400:
        d = seconds // 86400
        return f"{d} day{'s' if d != 1 else ''} ago"
    if seconds < 30 * 86400:
        w = seconds // (7 * 86400)
        return f"{w} week{'s' if w != 1 else ''} ago"
    m = seconds // (30 * 86400)
    return f"{m} month{'s' if m != 1 else ''} ago"
