"""Unit tests for app.web.timeago.timeago filter."""

from datetime import UTC, datetime, timedelta

import pytest

from app.web.timeago import timeago


def _iso(seconds_ago: float) -> str:
    """Return an ISO-8601 UTC string for a datetime that many seconds ago."""
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()


def test_just_now():
    assert timeago(_iso(30)) == "just now"


def test_minutes_ago():
    assert timeago(_iso(90)) == "1 minute ago"


def test_hours_ago():
    assert timeago(_iso(7200)) == "2 hours ago"


def test_days_ago():
    assert timeago(_iso(3 * 86400)) == "3 days ago"


def test_weeks_ago():
    assert timeago(_iso(14 * 86400)) == "2 weeks ago"


def test_months_ago():
    assert timeago(_iso(60 * 86400)) == "2 months ago"


def test_none_returns_empty():
    assert timeago(None) == ""


def test_invalid_string_returns_value():
    assert timeago("not-a-date") == "not-a-date"
