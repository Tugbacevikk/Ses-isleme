"""Add retry and sweeper fields

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-28 10:15:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: str | None = 'b2c3d4e5f6a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('audio_records', sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('audio_records', sa.Column('processing_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('audio_records', sa.Column('last_error_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('audio_records', 'last_error_at')
    op.drop_column('audio_records', 'processing_started_at')
    op.drop_column('audio_records', 'attempts')
