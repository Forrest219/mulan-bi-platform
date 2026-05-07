"""add_outbox_payload_json

Revision ID: 20260508_000002
Revises: 2026_05_08_0001
Create Date: 2026-05-08 00:02:00.000000

给 bi_notification_outbox 补充 payload_json 列，用于存储出站任务的原始参数快照
（如密码重置邮件的 reset_link / display_name），供 Celery task 重建发送上下文。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '20260508_000002'
down_revision: Union[str, None] = '2026_05_08_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'bi_notification_outbox',
        sa.Column('payload_json', postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('bi_notification_outbox', 'payload_json')
