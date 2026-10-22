"""add send_weekly_checkin to settings

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'settings',
        sa.Column('send_weekly_checkin', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('settings', 'send_weekly_checkin')
