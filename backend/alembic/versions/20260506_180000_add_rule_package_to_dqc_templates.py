"""add_rule_package_to_dqc_templates

Revision ID: 20260506_180000
Revises: 20260506_000002
Create Date: 2026-05-06 18:00:00.000000

三层数据质量模型：为规则模板添加 rule_package 字段，支持 L1/L2/L3/L4 分层分组。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '20260506_180000'
down_revision: Union[str, None] = '20260506_000002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'bi_dqc_rule_templates',
        sa.Column('rule_package', sa.String(length=8), nullable=True),
    )
    op.create_index('ix_dqc_tmpl_rule_package', 'bi_dqc_rule_templates', ['rule_package'])


def downgrade() -> None:
    op.drop_index('ix_dqc_tmpl_rule_package', table_name='bi_dqc_rule_templates')
    op.drop_column('bi_dqc_rule_templates', 'rule_package')
