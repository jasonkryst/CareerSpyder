"""Tests for the admin CLI (app/cli.py, #291): password reset without SMTP."""

import io

import psycopg
import pytest

from app import cli, db
from app.web.auth import (
    generate_reset_token,
    hash_password,
    password_fingerprint,
    verify_password,
    verify_reset_token,
)

GOOD = "a-Long-unique-passphrase-91"


@pytest.fixture(autouse=True)
def _no_hibp(monkeypatch):
    monkeypatch.delenv("CHECK_BREACHED_PASSWORDS", raising=False)
    monkeypatch.delenv("PASSWORD_MIN_LENGTH", raising=False)


@pytest.fixture
def user(pg_conn):
    return db.create_user(pg_conn, "Jason", "jason@x.test", hash_password("old-password-1"))


def _hash(pg_dsn, user_id):
    with psycopg.connect(pg_dsn) as conn:
        return db.get_user_by_id_with_hash(conn, user_id)["password_hash"]


def _run(pg_dsn, username, pw=GOOD, confirm=None):
    out = io.StringIO()
    code = cli.reset_password(
        username, dsn=pg_dsn, read_password=lambda: (pw, pw if confirm is None else confirm), out=out,
    )
    return code, out.getvalue()


def test_reset_password_sets_new_hash(pg_dsn, user):
    code, out = _run(pg_dsn, "jason")  # case-insensitive username
    assert code == 0
    assert "Password reset for Jason" in out
    assert verify_password(GOOD, _hash(pg_dsn, user["id"]))


def test_reset_password_revokes_sessions_and_reset_links(pg_dsn, pg_conn, user):
    old_hash = _hash(pg_dsn, user["id"])
    token = generate_reset_token("k" * 32, user["id"], user["email"], old_hash)
    assert _run(pg_dsn, "Jason")[0] == 0
    new_hash = _hash(pg_dsn, user["id"])
    # Sessions carry pw_fp; a new hash means a new fingerprint, so old sessions fail.
    assert password_fingerprint(new_hash) != password_fingerprint(old_hash)
    assert verify_reset_token("k" * 32, token, pg_conn) is None


def test_reset_password_unknown_user(pg_dsn, user):
    code, out = _run(pg_dsn, "nobody")
    assert code == 1
    assert "No user named" in out


@pytest.mark.parametrize("pw,confirm", [("short", None), (GOOD, GOOD + "x"), ("", None)])
def test_reset_password_rejects_policy_failures_and_keeps_hash(pg_dsn, user, pw, confirm):
    before = _hash(pg_dsn, user["id"])
    code, out = _run(pg_dsn, "Jason", pw, confirm)
    assert code == 2
    assert "Password rejected" in out
    assert _hash(pg_dsn, user["id"]) == before


def test_reset_password_rejects_password_containing_username(pg_dsn, user):
    code, _ = _run(pg_dsn, "Jason", "jason-jason-jason-91")
    assert code == 2


def test_reset_password_eof_changes_nothing(pg_dsn, user):
    before = _hash(pg_dsn, user["id"])

    def _eof():
        raise EOFError

    out = io.StringIO()
    assert cli.reset_password("Jason", dsn=pg_dsn, read_password=_eof, out=out) == 3
    assert _hash(pg_dsn, user["id"]) == before


def test_reset_password_notes_deactivated_account(pg_dsn, pg_conn, user):
    db.deactivate_user(pg_conn, user["id"])
    code, out = _run(pg_dsn, "Jason")
    assert code == 0
    assert "deactivated" in out


def test_main_reads_password_from_stdin(pg_dsn, user, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    monkeypatch.setattr("sys.stdin", io.StringIO(GOOD + "\n"))
    assert cli.main(["reset-password", "JASON", "--password-stdin"]) == 0
    assert "Password reset for Jason" in capsys.readouterr().out
    assert verify_password(GOOD, _hash(pg_dsn, user["id"]))


def test_main_requires_a_command():
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2


def test_reset_password_breached_message_never_prints_count(pg_dsn, user, monkeypatch):
    """CodeQL #20: the CLI prints constant wording only, nothing derived
    from the password (the HIBP breach count included)."""
    from app.security import password_policy

    monkeypatch.setattr(password_policy, "breach_check_enabled", lambda: True)
    monkeypatch.setattr(password_policy, "pwned_count", lambda *a, **k: 4321)
    before = _hash(pg_dsn, user["id"])
    code, out = _run(pg_dsn, "Jason")
    assert code == 2
    assert "data breach" in out.lower()
    assert "4321" not in out and "4,321" not in out
    assert GOOD not in out
    assert _hash(pg_dsn, user["id"]) == before
