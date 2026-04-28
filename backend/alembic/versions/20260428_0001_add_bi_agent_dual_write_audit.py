"""add_bi_agent_dual_write_audit — Spec 36 §15

双写审计表（按月分区，30天保留）：
- trace_id: 唯一追踪 ID（API 入口生成，双写路径共用）
- mode: HOMEPAGE_AGENT_MODE 四态
- agent_result / agent_result_hash: Agent 结果及哈希
- nlq_result / nlq_result_hash: NLQ 结果及哈希（dual_write 模式下必填）
- is_success: 是否成功
- error_message: 错误信息

Revision ID: add_bi_agent_dual_write_audit
Revises: 20260426_0002
Create Date: 2026-04-28
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "add_bi_agent_dual_write_audit"
down_revision: Union[str, None] = "20260426_0002"
branch_labels: Union[str, tuple[str], None] = None
depends_on: Union[str, tuple[str], None] = None


def upgrade() -> None:
    # 先给 platform_settings 加 extra_settings JSON 字段（如果不存在）
    # 注意：这会与 model 定义保持一致
    op.execute("""
        ALTER TABLE platform_settings
        ADD COLUMN IF NOT EXISTS extra_settings JSONB DEFAULT '{}'::jsonb
    """)
    op.execute("COMMENT ON COLUMN platform_settings.extra_settings IS 'Spec 36 §15: KV 扩展字段（homepage_agent_mode 等）'")

    # 创建 bi_agent_dual_write_audit 表
    op.create_table(
        "bi_agent_dual_write_audit",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # 追踪 ID（API 入口生成，双写路径共用）
        sa.Column("trace_id", sa.String(64), nullable=False, index=True),
        # HOMEPAGE_AGENT_MODE 四态
        sa.Column("mode", sa.String(32), nullable=False),
        # 原始问题
        sa.Column("question", sa.Text(), nullable=False),
        # Agent 结果（JSON）
        sa.Column("agent_result", postgresql.JSONB(), nullable=True),
        sa.Column("agent_result_hash", sa.String(64), nullable=True),
        # NLQ 结果（dual_write 模式下必填）
        sa.Column("nlq_result", postgresql.JSONB(), nullable=True),
        sa.Column("nlq_result_hash", sa.String(64), nullable=True),
        # 执行结果
        sa.Column("is_success", sa.Boolean(), nullable=False, default=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        # 审计字段
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        # 按月分区键（用于分区裁剪）
        sa.Column("partition_key", sa.String(6), nullable=False, index=True),
    )

    # 索引
    op.create_index(
        "ix_bi_agent_dual_write_audit_trace_id",
        "bi_agent_dual_write_audit",
        ["trace_id"],
    )
    op.create_index(
        "ix_bi_agent_dual_write_audit_created_at",
        "bi_agent_dual_write_audit",
        ["created_at"],
    )
    op.create_index(
        "ix_bi_agent_dual_write_audit_mode",
        "bi_agent_dual_write_audit",
        ["mode"],
    )

    # 30 天自动清理（事件触发器，或使用 pg_cron）
    # 注意：生产环境需要在数据库端配置 pg_cron 或事件触发器
    # 这里仅记录清理策略，实际清理由 DBA 配置


def downgrade() -> None:
    op.drop_table("bi_agent_dual_write_audit")
    # 保留 extra_settings 列（可能有其他用途）