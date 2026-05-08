"""extract_bi_task_tables_ddl

Revision ID: 20260508_task_ddl
Revises: 20260508_sources
Create Date: 2026-05-08

将 bi_task_runs 和 bi_task_schedules 的完整 DDL 提取到 Alembic 管理。
原始 DDL 曾存在于 app/api/tasks.py POST /seed 端点的内联 SQL 中，
由标记迁移 0d7cee7bad2a 承认其历史存在。本迁移补全规范化 DDL 记录，
并在 tasks.py 中移除内联 DDL（仅保留种子数据写入逻辑）。

upgrade()  使用 IF NOT EXISTS，对已存在表安全幂等。
downgrade() 按依赖顺序删表（bi_task_schedules 无外键，bi_task_runs 有自引用）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260508_task_ddl"
down_revision: Union[str, None] = "20260508_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # bi_task_runs ── 幂等：IF NOT EXISTS 确保已存在时跳过
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS bi_task_runs (
            id BIGSERIAL PRIMARY KEY,
            celery_task_id VARCHAR(256),
            task_name VARCHAR(256) NOT NULL,
            task_label VARCHAR(128),
            trigger_type VARCHAR(16) NOT NULL DEFAULT 'beat',
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            duration_ms INTEGER,
            result_summary JSONB,
            error_message TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            parent_run_id BIGINT REFERENCES bi_task_runs(id) ON DELETE SET NULL,
            triggered_by BIGINT REFERENCES auth_users(id) ON DELETE SET NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT chk_trigger_type CHECK (trigger_type IN ('beat', 'manual', 'api')),
            CONSTRAINT chk_status CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled'))
        )
    """))

    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_task_runs_task_name_started ON bi_task_runs(task_name, started_at)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_task_runs_status_started ON bi_task_runs(status, started_at)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_task_runs_started_at ON bi_task_runs(started_at)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_task_runs_parent ON bi_task_runs(parent_run_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_task_runs_celery_task_id ON bi_task_runs(celery_task_id)"))

    # bi_task_schedules ── 幂等：IF NOT EXISTS
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS bi_task_schedules (
            id SERIAL PRIMARY KEY,
            schedule_key VARCHAR(128) UNIQUE NOT NULL,
            task_name VARCHAR(256) NOT NULL,
            description TEXT,
            schedule_expr VARCHAR(256) NOT NULL,
            cron_expr VARCHAR(64),
            is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            last_run_at TIMESTAMP,
            last_run_status VARCHAR(16),
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))

    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_task_schedules_task_name ON bi_task_schedules(task_name)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_task_schedules_is_enabled ON bi_task_schedules(is_enabled)"))


def downgrade() -> None:
    # bi_task_schedules 无外键，可直接删除
    op.execute(sa.text("DROP TABLE IF EXISTS bi_task_schedules"))
    # bi_task_runs 有自引用 FK，CASCADE 处理
    op.execute(sa.text("DROP TABLE IF EXISTS bi_task_runs CASCADE"))
