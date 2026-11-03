"""Password policy (#269): NIST SP 800-63B-style checks plus the optional
Have I Been Pwned k-anonymity range lookup. No live network -- every HIBP
call goes through an injected fake ``http_get``."""
import hashlib

import pytest
import requests

from app.security import password_policy as pp

GOOD = "correct horse battery staple"


def _sha1(pw: str) -> str:
    return hashlib.sha1(pw.encode()).hexdigest().upper()  # noqa: S324 -- HIBP's format


class FakeResp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class Recorder:
    """Fake http_get that records every call and returns a canned body."""

    def __init__(self, body: str = "", status: int = 200, exc: Exception | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.body, self.status, self.exc = body, status, exc

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.exc is not None:
            raise self.exc
        return FakeResp(self.body, self.status)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("CHECK_BREACHED_PASSWORDS", raising=False)
    monkeypatch.delenv("PASSWORD_MIN_LENGTH", raising=False)


# --- configuration -----------------------------------------------------------

def test_breach_check_is_off_by_default():
    assert pp.breach_check_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_breach_check_truthy_values_enable_it(monkeypatch, value):
    monkeypatch.setenv("CHECK_BREACHED_PASSWORDS", value)
    assert pp.breach_check_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "garbage"])
def test_breach_check_other_values_leave_it_off(monkeypatch, value):
    monkeypatch.setenv("CHECK_BREACHED_PASSWORDS", value)
    assert pp.breach_check_enabled() is False


def test_min_length_defaults_to_8():
    assert pp.min_length() == 8


def test_min_length_is_configurable(monkeypatch):
    monkeypatch.setenv("PASSWORD_MIN_LENGTH", "15")
    assert pp.min_length() == 15


@pytest.mark.parametrize("value", ["4", "0", "-3", "7"])
def test_min_length_never_drops_below_nist_floor(monkeypatch, value):
    monkeypatch.setenv("PASSWORD_MIN_LENGTH", value)
    assert pp.min_length() == 8


def test_min_length_capped_below_bcrypt_limit(monkeypatch):
    # bcrypt only sees 72 bytes; a minimum above that would reject everything.
    monkeypatch.setenv("PASSWORD_MIN_LENGTH", "500")
    assert pp.min_length() == 64


@pytest.mark.parametrize("value", ["abc", "8.5", " "])
def test_min_length_invalid_falls_back_to_default(monkeypatch, value):
    monkeypatch.setenv("PASSWORD_MIN_LENGTH", value)
    assert pp.min_length() == 8


# --- HIBP k-anonymity lookup -------------------------------------------------

def test_pwned_count_sends_only_the_5_char_hash_prefix():
    pw = "hunter2hunter2"
    digest = _sha1(pw)
    rec = Recorder(body=f"{digest[5:]}:42\r\n")
    assert pp.pwned_count(pw, http_get=rec) == 42
    (url, kwargs), = rec.calls
    assert url == f"https://api.pwnedpasswords.com/range/{digest[:5]}"
    # Neither the plaintext nor the rest of the hash leaves the process.
    assert pw not in url and digest[5:] not in url
    assert kwargs["headers"]["Add-Padding"] == "true"
    assert "User-Agent" in kwargs["headers"]
    assert kwargs["timeout"] <= 5


def test_pwned_count_zero_when_suffix_absent():
    rec = Recorder(body="0000000000000000000000000000000000A:3\r\nFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF:9")
    assert pp.pwned_count(GOOD, http_get=rec) == 0


def test_pwned_count_matches_suffix_case_insensitively():
    digest = _sha1(GOOD)
    rec = Recorder(body=f"{digest[5:].lower()}:7")
    assert pp.pwned_count(GOOD, http_get=rec) == 7


def test_pwned_count_ignores_padding_entries():
    # With Add-Padding, HIBP returns decoy suffixes with a count of 0.
    digest = _sha1(GOOD)
    rec = Recorder(body=f"{digest[5:]}:0\r\n")
    assert pp.pwned_count(GOOD, http_get=rec) == 0


def test_pwned_count_tolerates_malformed_lines():
    digest = _sha1(GOOD)
    rec = Recorder(body=f"garbage\r\n:\r\nABC:notanumber\r\n{digest[5:]}:5\r\n")
    assert pp.pwned_count(GOOD, http_get=rec) == 5


@pytest.mark.parametrize("exc", [
    requests.ConnectionError("no egress"),
    requests.Timeout("slow"),
    OSError("dns"),
])
def test_pwned_count_returns_none_on_network_error(exc):
    assert pp.pwned_count(GOOD, http_get=Recorder(exc=exc)) is None


def test_pwned_count_returns_none_on_http_error():
    assert pp.pwned_count(GOOD, http_get=Recorder(status=503)) is None


# --- check_new_password: local rules ---------------------------------------

def test_accepts_a_good_passphrase():
    assert pp.check_new_password(GOOD, GOOD) is None


def test_rejects_empty():
    assert "required" in pp.check_new_password("", "").lower()


def test_rejects_too_short_with_the_configured_minimum(monkeypatch):
    assert "at least 8 characters" in pp.check_new_password("abc", "abc")
    monkeypatch.setenv("PASSWORD_MIN_LENGTH", "15")
    msg = pp.check_new_password("fourteen-chars", "fourteen-chars")
    assert "at least 15 characters" in msg


def test_length_counts_characters_not_bytes():
    # NIST: count Unicode code points. 8 "é" is 8 characters (16 bytes).
    pw = "éàüößçñø"
    assert pp.check_new_password(pw, pw) is None


def test_rejects_over_72_bytes():
    pw = "é" * 40  # 40 chars, 80 bytes
    assert "72 bytes" in pp.check_new_password(pw, pw)


def test_rejects_mismatch():
    assert "do not match" in pp.check_new_password(GOOD, GOOD + "x").lower()


@pytest.mark.parametrize("pw", ["password", "Password1", "football", "qwerty123", "iloveyou"])
def test_rejects_common_passwords(pw):
    msg = pp.check_new_password(pw, pw)
    assert msg is not None and "common" in msg.lower()


@pytest.mark.parametrize("pw", ["aaaaaaaa", "11111111", "abcdefgh", "87654321", "zyxwvuts"])
def test_rejects_repetitive_or_sequential(pw):
    msg = pp.check_new_password(pw, pw)
    assert msg is not None and ("repeat" in msg.lower() or "sequence" in msg.lower())


def test_rejects_password_containing_username():
    msg = pp.check_new_password("Jordan-2026-x", "Jordan-2026-x", username="jordan")
    assert msg is not None and "username" in msg.lower()


def test_rejects_password_containing_email_local_part():
    msg = pp.check_new_password("xx.kestrel.99", "xx.kestrel.99", email="Kestrel@example.com")
    assert msg is not None and "email" in msg.lower()


def test_rejects_password_containing_the_app_name():
    msg = pp.check_new_password("MyCareerSpyder!", "MyCareerSpyder!")
    assert msg is not None and "careerspyder" in msg.lower()


def test_two_char_usernames_do_not_trigger_containment():
    # A 1-2 char username would match far too many innocent passwords.
    assert pp.check_new_password("joplin river lamp", "joplin river lamp", username="jo") is None


def test_three_char_username_triggers_containment():
    msg = pp.check_new_password("bobcat river lamp", "bobcat river lamp", username="bob")
    assert msg is not None and "username" in msg.lower()


def test_password_equal_to_short_username_is_rejected():
    # Exact match is always rejected, even under the containment floor --
    # 8 chars can't be shorter than 3, so exercise via the email local part.
    assert pp._contains_context("ab", "ab") is True
    assert pp._contains_context("abc", "") is False


def test_common_list_is_the_bundled_seclists_file():
    words = pp._common_passwords()
    assert len(words) > 9000
    assert "password" in words and "qwerty" in words


def test_user_agent_identifies_the_app():
    assert pp._user_agent().startswith("CareerSpyder")


def test_no_composition_rules():
    # NIST: no "must contain a digit/symbol/uppercase" rules.
    assert pp.check_new_password("plainlowercasewords", "plainlowercasewords") is None


# --- check_new_password: breach check --------------------------------------

def test_breach_check_not_called_when_disabled():
    rec = Recorder(body="")
    assert pp.check_new_password(GOOD, GOOD, http_get=rec) is None
    assert rec.calls == []


def test_breached_password_rejected_with_explanation(monkeypatch):
    monkeypatch.setenv("CHECK_BREACHED_PASSWORDS", "true")
    digest = _sha1(GOOD)
    rec = Recorder(body=f"{digest[5:]}:1234")
    msg = pp.check_new_password(GOOD, GOOD, http_get=rec)
    assert msg is not None
    assert "data breach" in msg.lower()
    assert "1,234" in msg
    assert "never sent" in msg.lower()


def test_unbreached_password_accepted_when_check_enabled(monkeypatch):
    monkeypatch.setenv("CHECK_BREACHED_PASSWORDS", "true")
    rec = Recorder(body="0000000000000000000000000000000000A:3")
    assert pp.check_new_password(GOOD, GOOD, http_get=rec) is None
    assert len(rec.calls) == 1


def test_breach_check_fails_open_and_logs(monkeypatch, caplog):
    monkeypatch.setenv("CHECK_BREACHED_PASSWORDS", "true")
    # Alembic's fileConfig() (run by the pg_dsn fixture in earlier tests)
    # disables pre-existing loggers; re-enable for this test only.
    monkeypatch.setattr(pp.logger, "disabled", False)
    monkeypatch.setattr(pp.logger, "propagate", True)
    rec = Recorder(exc=requests.ConnectionError("no egress"))
    with caplog.at_level("WARNING", logger="app.security.password_policy"):
        assert pp.check_new_password(GOOD, GOOD, http_get=rec) is None
    assert "Have I Been Pwned" in caplog.text
    # The plaintext must never appear in logs.
    assert GOOD not in caplog.text


def test_breach_check_skipped_when_local_rules_already_fail(monkeypatch):
    monkeypatch.setenv("CHECK_BREACHED_PASSWORDS", "true")
    rec = Recorder(body="")
    assert pp.check_new_password("short", "short", http_get=rec) is not None
    assert pp.check_new_password(GOOD, "different", http_get=rec) is not None
    assert rec.calls == []


def test_default_http_get_is_patchable(monkeypatch):
    """Routes call check_new_password without http_get; tests (and nothing
    else) swap the module-level default."""
    monkeypatch.setenv("CHECK_BREACHED_PASSWORDS", "true")
    rec = Recorder(body=f"{_sha1(GOOD)[5:]}:2")
    monkeypatch.setattr(pp, "_http_get", rec)
    assert "data breach" in pp.check_new_password(GOOD, GOOD).lower()
    assert len(rec.calls) == 1


def test_bundled_common_list_matches_pinned_hash():
    """docs/third-party-notices.md pins this file's SHA-256; a change to the
    list must update the notice (source commit, hash) too."""
    data = pp._COMMON_PASSWORDS_FILE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == (
        "68782d6a4a19a4768d5f15dd66bd534e7a33055cc755411e33f16d18c50fdcce"
    )


def test_invalid_min_length_warning_does_not_echo_the_value(monkeypatch, caplog):
    # CodeQL py/clear-text-logging-sensitive-data: PASSWORD_* env values stay
    # out of logs even though this one is only a length.
    monkeypatch.setattr(pp.logger, "disabled", False)
    monkeypatch.setattr(pp.logger, "propagate", True)
    monkeypatch.setenv("PASSWORD_MIN_LENGTH", "s3cr3t-looking")
    with caplog.at_level("WARNING", logger="app.security.password_policy"):
        assert pp.min_length() == 8
    assert "not an integer" in caplog.text
    assert "s3cr3t-looking" not in caplog.text
