"""Add status and created_at compound index to audio_records

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-28 11:40:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: str | None = 'd4e5f6a7b8c9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index('idx_audio_records_status_created', 'audio_records', ['status', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_audio_records_status_created', table_name='audio_records')
