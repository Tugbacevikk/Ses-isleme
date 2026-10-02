"""Add webhook callback fields

Revision ID: b2c3d4e5f6a7
Revises: afdd9c4069af
Create Date: 2026-09-21 15:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: str | None = 'afdd9c4069af'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('audio_records', sa.Column('callback_url', sa.String(length=1024), nullable=True))
    op.add_column('audio_records', sa.Column('webhook_status', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('audio_records', 'webhook_status')
    op.drop_column('audio_records', 'callback_url')
