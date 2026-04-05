"""Add nlq_query_logs table (PRD §10.1)

Revision ID: add_nlq_query_logs
Revises: add_knowledge_base
Create Date: 2026-04-05

Revision notes:
- nlq_query_logs: NL-to-Query 审计日志表
  - 每次 NL-to-Query 请求（成功或失败）均记录一条
  - vizql_json 仅记录查询结构，不记录结果数据（PRD §10.4 数据隔离）
  - 复合索引 (user_id, created_at) 支持按用户查历史
  - 单字段索引 datasource_luid 支持按数据源统计
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "add_nlq_query_logs"
down_revision: Union[str, None] = "add_knowledge_base"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nlq_query_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False, index=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=32), nullable=True),
        sa.Column("datasource_luid", sa.String(length=256), nullable=True),
        sa.Column("vizql_json", JSONB, nullable=True),  # 仅记录查询结构，不记录结果
        sa.Column("response_type", sa.String(length=16), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=16), nullable=True),  # 成功时为 NULL
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # 复合索引：按用户查历史
    op.create_index("ix_nlq_log_user_created", "nlq_query_logs", ["user_id", "created_at"])
    # 单字段索引：按数据源统计
    op.create_index("ix_nlq_log_datasource", "nlq_query_logs", ["datasource_luid"])


def downgrade() -> None:
    op.drop_index("ix_nlq_log_datasource", table_name="nlq_query_logs")
    op.drop_index("ix_nlq_log_user_created", table_name="nlq_query_logs")
    op.drop_table("nlq_query_logs")
