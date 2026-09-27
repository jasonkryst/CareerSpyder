"""jobs are owned per user: composite (user_id, key) primary key

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rows left ownerless (single-user install upgraded before an admin was
    # seeded) go to the earliest admin; anything still ownerless has no one
    # who could ever see it.
    op.execute(
        "UPDATE jobs SET user_id = ("
        "SELECT id FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1"
        ") WHERE user_id IS NULL"
    )
    op.execute("DELETE FROM jobs WHERE user_id IS NULL")
    op.execute(
        "UPDATE job_status_history h SET user_id = j.user_id FROM jobs j "
        "WHERE h.user_id IS NULL AND h.job_key = j.key"
    )
    op.execute("DELETE FROM job_status_history WHERE user_id IS NULL")
    op.execute("ALTER TABLE jobs ALTER COLUMN user_id SET NOT NULL")
    op.execute("ALTER TABLE job_status_history ALTER COLUMN user_id SET NOT NULL")
    op.execute("ALTER TABLE jobs DROP CONSTRAINT jobs_pkey")
    op.execute("ALTER TABLE jobs ADD PRIMARY KEY (user_id, key)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_status_history_user_key "
        "ON job_status_history (user_id, job_key)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_job_status_history_user_key")
    op.execute("ALTER TABLE jobs DROP CONSTRAINT jobs_pkey")
    # Collapse per-user copies back to one row per key, keeping the oldest.
    op.execute(
        "DELETE FROM jobs a USING jobs b "
        "WHERE a.key = b.key AND (a.first_seen_at, a.ctid) > (b.first_seen_at, b.ctid)"
    )
    op.execute("ALTER TABLE jobs ADD PRIMARY KEY (key)")
    op.execute("ALTER TABLE jobs ALTER COLUMN user_id DROP NOT NULL")
    op.execute("ALTER TABLE job_status_history ALTER COLUMN user_id DROP NOT NULL")
