"""add_agent_conversations_and_messages

Revision ID: 20260424_010000
Revises: 20260421_060000
Create Date: 2026-04-24

Spec 36 §4.1 — Data Agent 会话表（Phase 1）：
- agent_conversations: 会话元数据（UUID, user_id, title, status）
- agent_conversation_messages: 会话消息（role, content, response_type, tools_used）

索引策略：
- ix_ac_user: (user_id, status, updated_at DESC) — 用户会话列表
- ix_acm_conv: (conversation_id, created_at) — 会话消息时序

迁移顺序（升级）：
  agent_conversations → agent_conversation_messages

回滚顺序（降级）：
  agent_conversation_messages → agent_conversations
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260424_010000"
down_revision: Union[str, None] = "20260421_060000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgcrypto 扩展：gen_random_uuid() 所需（部分新版 PG 默认无此扩展）
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ==================== agent_conversations ====================
    # Data Agent 会话表 — 管理用户与 Agent 的对话会话
    op.create_table(
        "agent_conversations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["tableau_connections.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ac_user",
        "agent_conversations",
        ["user_id", "status", sa.text("updated_at DESC")],
        unique=False,
    )

    # ==================== agent_conversation_messages ====================
    # 会话消息表 — 存储每条 user/assistant 消息
    op.create_table(
        "agent_conversation_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("response_type", sa.String(length=16), nullable=True),
        sa.Column("response_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tools_used", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("steps_count", sa.Integer(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_acm_role"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_acm_conv",
        "agent_conversation_messages",
        ["conversation_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    # 反序 DROP：先删子表/依赖表，最后删基础表
    op.drop_index("ix_acm_conv", table_name="agent_conversation_messages")
    op.drop_table("agent_conversation_messages")

    op.drop_index("ix_ac_user", table_name="agent_conversations")
    op.drop_table("agent_conversations")