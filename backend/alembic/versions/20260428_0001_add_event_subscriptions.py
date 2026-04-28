"""add_event_subscriptions — bi_event_subscriptions 表（Spec 30 异常告警订阅）

Revision ID: 20260428_0001
Revises: ba52b50f68f8
Create Date: 2026-04-28

支持用户订阅特定 metric 的 anomaly.detected 告警通知。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260428_0001"
down_revision: Union[str, None] = "ba52b50f68f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bi_event_subscriptions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_event_sub_user_id", "bi_event_subscriptions", ["user_id"])
    op.create_index("ix_event_sub_event_type", "bi_event_subscriptions", ["event_type"])
    op.create_index("ix_event_sub_target_id", "bi_event_subscriptions", ["target_id"])
    op.create_index(
        "ix_event_sub_user_event_target",
        "bi_event_subscriptions",
        ["user_id", "event_type", "target_id"],
    )
    op.create_index(
        "ix_event_sub_event_active",
        "bi_event_subscriptions",
        ["event_type", "is_active"],
    )


def downgrade() -> None:
    op.drop_table("bi_event_subscriptions")
