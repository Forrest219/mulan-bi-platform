"""add_dqc_rule_templates

Revision ID: 1aef64171005
Revises: fc37b0a529f5
Create Date: 2026-05-05 21:57:59.796713

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1aef64171005'
down_revision: Union[str, None] = 'fc37b0a529f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('bi_dqc_rule_templates',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('dimension', sa.String(length=32), nullable=False),
        sa.Column('rule_type', sa.String(length=32), nullable=False),
        sa.Column('default_config', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column('match_condition', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column('severity', sa.String(length=16), server_default=sa.text("'MEDIUM'"), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('is_builtin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_modified_by_user', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_dqc_tmpl_dim_type', 'bi_dqc_rule_templates', ['dimension', 'rule_type'], unique=False)
    op.create_index('ix_dqc_tmpl_enabled', 'bi_dqc_rule_templates', ['enabled'], unique=False)

    op.add_column('bi_dqc_quality_rules', sa.Column('template_id', sa.Integer(), nullable=True))
    op.add_column('bi_dqc_quality_rules', sa.Column('is_modified_by_user', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.create_index('ix_bi_dqc_quality_rules_template_id', 'bi_dqc_quality_rules', ['template_id'], unique=False)
    op.create_foreign_key('fk_dqc_rules_template_id', 'bi_dqc_quality_rules', 'bi_dqc_rule_templates', ['template_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_dqc_rules_template_id', 'bi_dqc_quality_rules', type_='foreignkey')
    op.drop_index('ix_bi_dqc_quality_rules_template_id', table_name='bi_dqc_quality_rules')
    op.drop_column('bi_dqc_quality_rules', 'is_modified_by_user')
    op.drop_column('bi_dqc_quality_rules', 'template_id')

    op.drop_index('ix_dqc_tmpl_enabled', table_name='bi_dqc_rule_templates')
    op.drop_index('ix_dqc_tmpl_dim_type', table_name='bi_dqc_rule_templates')
    op.drop_table('bi_dqc_rule_templates')
