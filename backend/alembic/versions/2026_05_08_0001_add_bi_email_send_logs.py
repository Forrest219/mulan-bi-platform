"""add_bi_email_send_logs

Revision ID: 2026_05_08_0001
Revises: ba52b50f68f8
Create Date: 2026-05-08 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '2026_05_08_0001'
down_revision: Union[str, None] = 'ba52b50f68f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bi_email_send_logs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('outbox_id', sa.BigInteger(), nullable=True),
        sa.Column('email_type', sa.String(length=32), nullable=False),
        sa.Column('recipient', sa.String(length=256), nullable=False),
        sa.Column('from_addr', sa.String(length=256), nullable=True),
        sa.Column('subject', sa.String(length=128), nullable=True),
        sa.Column(
            'status', sa.String(length=32), nullable=False,
            server_default=sa.text("'enqueued'")
        ),
        sa.Column('error_detail', sa.Text(), nullable=True),
        sa.Column(
            'attempt_count', sa.Integer(), nullable=False,
            server_default=sa.text('0')
        ),
        sa.Column('scheduled_at', sa.DateTime(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(), nullable=False,
            server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_email_log_outbox_id', 'bi_email_send_logs', ['outbox_id'], unique=False)
    op.create_index('ix_email_log_email_type', 'bi_email_send_logs', ['email_type'], unique=False)
    op.create_index('ix_email_log_recipient', 'bi_email_send_logs', ['recipient'], unique=False)
    op.create_index('ix_email_log_status_created', 'bi_email_send_logs', ['status', 'created_at'], unique=False)
    op.create_index('ix_email_log_recipient_created', 'bi_email_send_logs', ['recipient', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_email_log_recipient_created', table_name='bi_email_send_logs')
    op.drop_index('ix_email_log_status_created', table_name='bi_email_send_logs')
    op.drop_index('ix_email_log_recipient', table_name='bi_email_send_logs')
    op.drop_index('ix_email_log_email_type', table_name='bi_email_send_logs')
    op.drop_index('ix_email_log_outbox_id', table_name='bi_email_send_logs')
    op.drop_table('bi_email_send_logs')
