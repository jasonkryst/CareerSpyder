"""normalize stored emails to trimmed lowercase (#291)

Account recovery compares normalized addresses, and new rows are stored that
way. This brings existing rows in line. A user row whose normalized email
would collide with another account's is left unchanged: lookups are already
case-insensitive, so it still works, and the admin can resolve the duplicate.
Idempotent. The downgrade is a no-op, since the original casing isn't kept.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-16
"""
from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE users u SET email = lower(btrim(u.email))
        WHERE u.email <> lower(btrim(u.email))
          AND NOT EXISTS (
              SELECT 1 FROM users o
              WHERE o.id <> u.id AND lower(btrim(o.email)) = lower(btrim(u.email))
          )
        """
    )
    op.execute(
        "UPDATE invite_tokens SET email = lower(btrim(email)) "
        "WHERE email <> lower(btrim(email))"
    )


def downgrade() -> None:
    pass
