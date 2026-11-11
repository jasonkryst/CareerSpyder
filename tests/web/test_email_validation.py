"""Digest-recipient email validation (``app/web/routes_settings._is_valid_email``).

CodeQL alert #15 (py/polynomial-redos): the old pattern
``^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$`` let both domain groups match dots, so a
string like ``"!@!." + "!." * n`` that fails at the end backtracked in O(n^2).
Any signed-in user reaches it via /settings/preferences or a settings import.
"""

import time

import pytest

from app.web.routes_settings import MAX_EMAIL_LENGTH, _is_valid_email


@pytest.mark.parametrize(
    "addr",
    [
        "good@x.test",
        "first.last+tag@sub.example.co.uk",
        "o'brien@example.com",
        "a@b.c",
        "x" * 64 + "@" + "d" * 180 + ".com",  # 249 chars, under the cap
    ],
)
def test_accepts_well_formed_addresses(addr):
    assert _is_valid_email(addr)


@pytest.mark.parametrize(
    "addr",
    [
        "",
        "not-an-email",
        "@example.com",
        "user@",
        "user@localhost",  # no dot in the domain
        "user@@example.com",
        "us er@example.com",
        "user@exa mple.com",
        "user@example.com ",
        "user@.example.com",  # empty leading label
        "user@example..com",  # empty middle label
        "user@example.com.",  # empty trailing label
        "a@b@c.com",
    ],
)
def test_rejects_malformed_addresses(addr):
    assert not _is_valid_email(addr)


def test_rejects_addresses_over_the_length_cap():
    addr = "x" * 64 + "@" + "d" * (MAX_EMAIL_LENGTH - 64 - 1 - 4 + 1) + ".com"
    assert len(addr) == MAX_EMAIL_LENGTH + 1
    assert not _is_valid_email(addr)


@pytest.mark.parametrize("n", [10_000, 200_000])
def test_hostile_input_is_rejected_in_linear_time(n):
    # The CodeQL-reported attack shape; the old regex took ~1.5 s at n=8,000
    # and grows quadratically. Both the length cap and the regex must hold up.
    hostile = "!@!." + "!." * n + " "
    start = time.perf_counter()
    assert not _is_valid_email(hostile)
    assert time.perf_counter() - start < 0.5


def test_regex_alone_is_linear_on_hostile_input():
    # Guard the regex itself too, in case the length cap is ever relaxed.
    from app.web.routes_settings import EMAIL_RE

    hostile = "!@!." + "!." * 50_000 + " "
    start = time.perf_counter()
    assert EMAIL_RE.match(hostile) is None
    assert time.perf_counter() - start < 0.5
