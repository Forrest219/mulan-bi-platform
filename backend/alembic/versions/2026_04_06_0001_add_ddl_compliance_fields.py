"""add_ddl_compliance_fields

Revision ID: add_ddl_compliance_fields
Revises: 07c4d16b8335
Create Date: 2026-04-06 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'add_ddl_compliance_fields'
down_revision = '07c4d16b8335'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # === bi_rule_configs 新增字段 ===
    # is_modified_by_user: 用户是否手动修改过（Seed 幂等性保护）
    op.add_column('bi_rule_configs',
        sa.Column('is_modified_by_user', sa.Boolean(), nullable=False, server_default='false')
    )

    # scene_type: 适用场景（ODS/DWD/ADS/ALL）
    op.add_column('bi_rule_configs',
        sa.Column('scene_type', sa.String(length=16), nullable=False, server_default='ALL')
    )

    # === bi_scan_logs 新增字段 ===
    # trace_id: 追踪 ID，关联日志系统
    op.add_column('bi_scan_logs',
        sa.Column('trace_id', sa.String(length=64), nullable=True)
    )
    op.create_index(op.f('ix_bi_scan_logs_trace_id'), 'bi_scan_logs', ['trace_id'], unique=False)

    # results_masked: 脱敏后扫描结果（敏感关键词已处理）
    op.add_column('bi_scan_logs',
        sa.Column('results_masked', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    # bi_rule_configs
    op.drop_column('bi_rule_configs', 'scene_type')
    op.drop_column('bi_rule_configs', 'is_modified_by_user')

    # bi_scan_logs
    op.drop_index(op.f('ix_bi_scan_logs_trace_id'), table_name='bi_scan_logs')
    op.drop_column('bi_scan_logs', 'trace_id')
    op.drop_column('bi_scan_logs', 'results_masked')
