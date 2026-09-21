"""multi-user auth: users, invite_tokens, sources, user_id on existing tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-20
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- new tables -------------------------------------------------------

    op.execute("""
        CREATE TABLE users (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username      TEXT NOT NULL UNIQUE,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'member',
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE invite_tokens (
            token      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email      TEXT NOT NULL,
            created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            used_at    TIMESTAMPTZ
        )
    """)

    op.execute("""
        CREATE TABLE sources (
            id         TEXT PRIMARY KEY,
            user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type       TEXT NOT NULL,
            name       TEXT NOT NULL,
            secondary  BOOLEAN NOT NULL DEFAULT FALSE,
            config     JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX sources_user_id ON sources(user_id)")

    # --- alter existing tables --------------------------------------------

    op.execute("ALTER TABLE jobs ADD COLUMN user_id UUID REFERENCES users(id)")
    op.execute("ALTER TABLE runs ADD COLUMN user_id UUID REFERENCES users(id)")
    op.execute(
        "ALTER TABLE job_status_history ADD COLUMN user_id UUID REFERENCES users(id)"
    )

    # Redesign settings: remove singleton PK, switch to user_id as PK.
    # Must drop the old primary key before adding the new one; the id column
    # served only to enforce the singleton and is not referenced externally.
    op.execute("ALTER TABLE settings DROP CONSTRAINT settings_pkey")
    op.execute("ALTER TABLE settings DROP COLUMN id")
    op.execute("ALTER TABLE settings ADD COLUMN user_id UUID REFERENCES users(id)")
    op.execute("ALTER TABLE settings ADD PRIMARY KEY (user_id)")

    # --- indexes for per-user range scans ---------------------------------

    op.execute("CREATE INDEX jobs_user_id ON jobs(user_id)")
    op.execute("CREATE INDEX runs_user_id ON runs(user_id)")
    op.execute("CREATE INDEX job_status_history_user_id ON job_status_history(user_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS job_status_history_user_id")
    op.execute("DROP INDEX IF EXISTS runs_user_id")
    op.execute("DROP INDEX IF EXISTS jobs_user_id")

    op.execute("ALTER TABLE job_status_history DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS user_id")

    # Restore settings singleton: drop new PK/column, re-add id column + CHECK.
    op.execute("ALTER TABLE settings DROP CONSTRAINT IF EXISTS settings_pkey")
    op.execute("ALTER TABLE settings DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE settings ADD COLUMN id INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE settings ADD PRIMARY KEY (id)")
    op.execute(
        "ALTER TABLE settings ADD CONSTRAINT settings_id_check CHECK (id = 1)"
    )

    op.execute("DROP INDEX IF EXISTS sources_user_id")
    op.execute("DROP TABLE IF EXISTS sources")
    op.execute("DROP TABLE IF EXISTS invite_tokens")
    op.execute("DROP TABLE IF EXISTS users")
