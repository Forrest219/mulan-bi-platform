"""add_query_interface_tables

Revision ID: 20260421_030000
Revises: 20260421_020000
Create Date: 2026-04-21

Spec 14 — 问数模块 4 张核心表（P0）：
- query_connected_app_secrets : Tableau Connected App 密钥存储（Fernet 加密）
- query_sessions               : 用户问数对话 Session（多轮上下文）
- query_messages               : 对话消息记录（user / assistant）
- query_error_events           : Tableau 身份问题告警（管理员监控）

迁移顺序（升级）：
  query_connected_app_secrets → query_sessions → query_messages → query_error_events

回滚顺序（降级）：
  query_error_events → query_messages → query_sessions → query_connected_app_secrets
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260421_030000"
down_revision: Union[str, None] = "20260421_020000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgcrypto 扩展：gen_random_uuid() 所需
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ==================== query_connected_app_secrets ====================
    # Tableau Connected App 密钥配置表，每个连接最多一条 active 记录。
    op.create_table(
        "query_connected_app_secrets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(length=256), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["connection_id"], ["tableau_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["auth_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Partial UNIQUE 索引：每个 connection_id 只允许一条 is_active=TRUE 的记录
    op.create_index(
        "uq_connected_app_active",
        "query_connected_app_secrets",
        ["connection_id"],
        unique=True,
        postgresql_where=sa.text("is_active = TRUE"),
    )
    op.create_index(
        "idx_connected_app_connection",
        "query_connected_app_secrets",
        ["connection_id"],
        unique=False,
    )

    # ==================== query_sessions ====================
    # 用户问数对话 Session，支持多轮对话上下文追踪。
    op.create_table(
        "query_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_query_sessions_user",
        "query_sessions",
        ["user_id", sa.text("created_at DESC")],
        unique=False,
    )

    # ==================== query_messages ====================
    # 对话消息记录，支持多轮追问上下文读取。
    op.create_table(
        "query_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("data_table", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("datasource_luid", sa.String(length=256), nullable=True),
        sa.Column("query_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_query_messages_role"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["query_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["tableau_connections.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_query_messages_session",
        "query_messages",
        ["session_id", "created_at"],
        unique=False,
    )

    # ==================== query_error_events ====================
    # Tableau 身份问题告警表，管理员监控用。
    op.create_table(
        "query_error_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("error_type", sa.String(length=64), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("raw_error", sa.Text(), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["tableau_connections.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Partial 索引：只覆盖未解决的告警，避免全表扫描
    op.create_index(
        "idx_query_error_events_unresolved",
        "query_error_events",
        ["resolved", sa.text("created_at DESC")],
        unique=False,
        postgresql_where=sa.text("resolved = FALSE"),
    )


def downgrade() -> None:
    # 反序 DROP：先删子表 / 依赖表，最后删基础表
    op.drop_index("idx_query_error_events_unresolved", table_name="query_error_events")
    op.drop_table("query_error_events")

    op.drop_index("idx_query_messages_session", table_name="query_messages")
    op.drop_table("query_messages")

    op.drop_index("idx_query_sessions_user", table_name="query_sessions")
    op.drop_table("query_sessions")

    op.drop_index("idx_connected_app_connection", table_name="query_connected_app_secrets")
    op.drop_index("uq_connected_app_active", table_name="query_connected_app_secrets")
    op.drop_table("query_connected_app_secrets")
