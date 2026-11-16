"""Admin command line (#291).

    python -m app.cli reset-password <username>
    docker compose exec careerspyder python -m app.cli reset-password <username>

Sets a new password without SMTP. It applies the same password policy as
sign-up. Changing the stored hash signs out every existing session (sessions
carry a fingerprint of the hash) and voids every outstanding reset link
(those are bound to the hash too).

The password is read twice from the terminal, or once from stdin with
``--password-stdin`` for scripts. Exit codes: 0 done, 1 no such user,
2 password rejected, 3 couldn't read a password.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Callable
from typing import TextIO

import psycopg

from app import db
from app.security import password_policy
from app.web.auth import hash_password

DEFAULT_DSN = "postgresql://careerspyder:dev@localhost:5432/careerspyder"


def _prompt_twice() -> tuple[str, str]:
    return getpass.getpass("New password: "), getpass.getpass("Confirm new password: ")


def _from_stdin() -> tuple[str, str]:
    line = sys.stdin.readline().rstrip("\r\n")
    return line, line


def reset_password(
    username: str,
    *,
    dsn: str,
    read_password: Callable[[], tuple[str, str]],
    out: TextIO,
) -> int:
    with psycopg.connect(dsn) as conn:
        user = db.get_user_by_username(conn, username)
        if user is None:
            print(f"No user named {username!r}.", file=out)
            return 1
        try:
            password, confirm = read_password()
        except (EOFError, KeyboardInterrupt):
            print("No password entered; nothing changed.", file=out)
            return 3
        error = password_policy.check_new_password(
            password, confirm, username=user["username"], email=user["email"],
        )
        if error:
            print(f"Password rejected: {error}", file=out)
            return 2
        db.update_password(conn, user["id"], hash_password(password))
    print(
        f"Password reset for {user['username']}. Existing sessions and reset "
        "links for this account no longer work.",
        file=out,
    )
    if not user["is_active"]:
        print("Note: this account is deactivated, so it still can't sign in.", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="CareerSpyder admin tools")
    sub = parser.add_subparsers(dest="command", required=True)
    reset = sub.add_parser("reset-password", help="set a user's password without email")
    reset.add_argument("username", help="the user's username (case-insensitive)")
    reset.add_argument(
        "--password-stdin", action="store_true",
        help="read the new password from the first line of stdin instead of prompting",
    )
    args = parser.parse_args(argv)

    dsn = os.environ.get("DATABASE_URL", DEFAULT_DSN)
    reader = _from_stdin if args.password_stdin else _prompt_twice
    return reset_password(args.username, dsn=dsn, read_password=reader, out=sys.stdout)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
