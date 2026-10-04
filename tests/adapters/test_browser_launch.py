import pytest

from app.adapters.browser import chromium_launch_kwargs


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1", {"chromium_sandbox": True}),
        ("true", {"chromium_sandbox": True}),
        ("True", {"chromium_sandbox": True}),
        ("0", {}),
        ("", {}),
    ],
)
def test_chromium_sandbox_is_opt_in(monkeypatch, value, expected):
    monkeypatch.setenv("CHROMIUM_SANDBOX", value)
    assert chromium_launch_kwargs() == expected


def test_chromium_sandbox_defaults_to_off_when_unset(monkeypatch):
    monkeypatch.delenv("CHROMIUM_SANDBOX", raising=False)
    assert chromium_launch_kwargs() == {}
