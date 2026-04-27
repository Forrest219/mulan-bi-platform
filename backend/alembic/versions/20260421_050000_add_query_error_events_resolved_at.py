"""add resolved_at to query_error_events

Revision ID: 20260421_050000
Revises: 20260421_040000
Create Date: 2026-04-21

Spec 14 T-10 — 为 query_error_events 表追加 resolved_at 列，
记录管理员标记已解决时的 UTC 时间戳。

变更说明：
- 新增列 resolved_at（DateTime, nullable）
- 无数据回填（历史告警 resolved_at=NULL 表示解决时间未知）
- 零破坏性：现有列/索引不受影响
"""
from alembic import op, context
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260421_050000"
down_revision = "20260421_040000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode():
        conn = op.get_bind()
        result = conn.execute(sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='query_error_events' AND column_name='resolved_at'"
        ))
        if result.fetchone():
            return  # column already exists
    op.add_column(
        "query_error_events",
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("query_error_events", "resolved_at")
