"""add source_count to runs

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('runs', sa.Column('source_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('runs', 'source_count')
