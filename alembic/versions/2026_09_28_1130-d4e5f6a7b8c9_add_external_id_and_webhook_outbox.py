"""Add external_id and webhook_outbox table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-28 11:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: str | None = 'c3d4e5f6a7b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. external_id sütunu ve benzersiz indeks ekle
    op.add_column('audio_records', sa.Column('external_id', sa.String(length=255), nullable=True))
    op.create_index('ix_audio_records_external_id', 'audio_records', ['external_id'], unique=True)

    # 2. webhook_deliveries (Outbox) tablosunu oluştur
    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('job_id', sa.Uuid(), nullable=False),
        sa.Column('url', sa.String(length=1024), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['audio_records.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_webhook_deliveries_status_next', 'webhook_deliveries', ['status', 'next_attempt_at'], unique=False)
    op.create_index('idx_webhook_deliveries_job_id', 'webhook_deliveries', ['job_id'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_webhook_deliveries_job_id', table_name='webhook_deliveries')
    op.drop_index('idx_webhook_deliveries_status_next', table_name='webhook_deliveries')
    op.drop_table('webhook_deliveries')

    op.drop_index('ix_audio_records_external_id', table_name='audio_records')
    op.drop_column('audio_records', 'external_id')
