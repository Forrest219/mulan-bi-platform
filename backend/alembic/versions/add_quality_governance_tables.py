"""add_quality_governance_tables

Revision ID: add_quality_tables_v1
Revises: add_mfa_fields
Create Date: 2026-04-05 00:00:00.000000

遵循 Spec 15 v1.1 数据治理与质量监控技术规格书：
- bi_quality_rules: 质量规则定义
- bi_quality_results: 检测结果（Append-Only，90天保留，月分区）
- bi_quality_scores: 评分快照（Append-Only，90天保留，月分区）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_quality_tables_v1'
down_revision: Union[str, None] = 'add_mfa_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ==================== bi_quality_rules ====================
    op.create_table(
        'bi_quality_rules',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('datasource_id', sa.BigInteger(), nullable=False),
        sa.Column('table_name', sa.String(length=128), nullable=False),
        sa.Column('field_name', sa.String(length=128), nullable=True),
        sa.Column('rule_type', sa.String(length=32), nullable=False),
        sa.Column('operator', sa.String(length=16), nullable=False, server_default='lte'),
        sa.Column('threshold', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('severity', sa.String(length=16), nullable=False, server_default='MEDIUM'),
        sa.Column('execution_mode', sa.String(length=16), nullable=False, server_default='scheduled'),
        sa.Column('cron', sa.String(length=64), nullable=True),
        sa.Column('custom_sql', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('tags_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        sa.Column('updated_by', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['datasource_id'], ['bi_data_sources.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qr_ds_table', 'bi_quality_rules', ['datasource_id', 'table_name'], unique=False)
    op.create_index('ix_qr_enabled', 'bi_quality_rules', ['enabled'], unique=False)

    # ==================== bi_quality_results ====================
    op.create_table(
        'bi_quality_results',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('rule_id', sa.BigInteger(), nullable=False),
        sa.Column('datasource_id', sa.BigInteger(), nullable=False),
        sa.Column('table_name', sa.String(length=128), nullable=False),
        sa.Column('field_name', sa.String(length=128), nullable=True),
        sa.Column('executed_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('passed', sa.Boolean(), nullable=False),
        sa.Column('actual_value', sa.Float(), nullable=True),
        sa.Column('expected_value', sa.String(length=256), nullable=True),
        sa.Column('detail_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('execution_time_ms', sa.BigInteger(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['rule_id'], ['bi_quality_rules.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qres_rule_exec', 'bi_quality_results', ['rule_id', 'executed_at'], unique=False)
    op.create_index('ix_qres_ds_exec', 'bi_quality_results', ['datasource_id', 'executed_at'], unique=False)
    op.create_index('ix_qres_passed', 'bi_quality_results', ['passed'], unique=False)

    # ==================== bi_quality_scores ====================
    op.create_table(
        'bi_quality_scores',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('datasource_id', sa.BigInteger(), nullable=False),
        sa.Column('scope_type', sa.String(length=16), nullable=False),
        sa.Column('scope_name', sa.String(length=256), nullable=False),
        sa.Column('overall_score', sa.Float(), nullable=False),
        sa.Column('completeness_score', sa.Float(), nullable=True),
        sa.Column('consistency_score', sa.Float(), nullable=True),
        sa.Column('uniqueness_score', sa.Float(), nullable=True),
        sa.Column('timeliness_score', sa.Float(), nullable=True),
        sa.Column('conformity_score', sa.Float(), nullable=True),
        sa.Column('health_scan_score', sa.Float(), nullable=True),
        sa.Column('ddl_compliance_score', sa.Float(), nullable=True),
        sa.Column('detail_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('calculated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qs_ds_scope', 'bi_quality_scores', ['datasource_id', 'scope_type', 'scope_name', 'calculated_at'], unique=False)
    op.create_index('ix_qs_calc_at', 'bi_quality_scores', ['calculated_at'], unique=False)

    # NOTE: PostgreSQL 分区（PARTITION BY RANGE）在 Alembic 中需手动执行，
    # 开发/测试环境可使用上述普通表。
    # 生产环境建议执行以下 SQL 创建分区表（以 bi_quality_results 为例）：
    #
    # ALTER TABLE bi_quality_results PARTITION BY RANGE (executed_at);
    # CREATE TABLE bi_quality_results_2026_04 PARTITION OF bi_quality_results
    #     FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
    # CREATE TABLE bi_quality_results_2026_05 PARTITION OF bi_quality_results
    #     FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
    #
    # Celery 清理任务（cleanup_old_quality_results）负责定期 DROP 过期分区。


def downgrade() -> None:
    op.drop_index('ix_qs_calc_at', table_name='bi_quality_scores')
    op.drop_index('ix_qs_ds_scope', table_name='bi_quality_scores')
    op.drop_table('bi_quality_scores')

    op.drop_index('ix_qres_passed', table_name='bi_quality_results')
    op.drop_index('ix_qres_ds_exec', table_name='bi_quality_results')
    op.drop_index('ix_qres_rule_exec', table_name='bi_quality_results')
    op.drop_table('bi_quality_results')

    op.drop_index('ix_qr_enabled', table_name='bi_quality_rules')
    op.drop_index('ix_qr_ds_table', table_name='bi_quality_rules')
    op.drop_table('bi_quality_rules')
