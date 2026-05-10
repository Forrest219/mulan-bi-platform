"""create_agent_skills_tables

Revision ID: 20260508_skills_tables
Revises: 20260508_kb_metric_ids
Create Date: 2026-05-08 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = '20260508_skills_tables'
down_revision: Union[str, None] = '20260508_kb_metric_ids'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- agent_skills 表 ---
    op.create_table(
        'agent_skills',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column('skill_key', sa.String(128), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('category', sa.String(64), nullable=False,
                  server_default=sa.text("'general'")),
        sa.Column('is_enabled', sa.Boolean, nullable=False,
                  server_default=sa.text("true")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column('created_by', sa.Integer,
                  sa.ForeignKey('auth_users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.UniqueConstraint('skill_key', name='uq_agent_skills_skill_key'),
    )
    op.create_index('idx_agent_skills_skill_key', 'agent_skills', ['skill_key'])
    op.create_index('idx_agent_skills_category', 'agent_skills', ['category'])

    # --- agent_skill_versions 表 ---
    op.create_table(
        'agent_skill_versions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column('skill_id', UUID(as_uuid=True),
                  sa.ForeignKey('agent_skills.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('version_number', sa.String(16), nullable=False),
        sa.Column('description', sa.Text, nullable=False),
        sa.Column('input_schema', JSONB, nullable=False),
        sa.Column('endpoint_type', sa.String(32), nullable=False,
                  server_default=sa.text("'static'")),
        sa.Column('code_ref', sa.Text, nullable=True),
        sa.Column('change_notes', sa.Text, nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False,
                  server_default=sa.text("false")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column('created_by', sa.Integer,
                  sa.ForeignKey('auth_users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.UniqueConstraint('skill_id', 'version_number',
                            name='uq_skill_version_number'),
    )
    op.create_index('idx_skill_versions_skill_id', 'agent_skill_versions', ['skill_id'])

    # Partial unique index: 每个 skill 最多一个 is_active=true 版本
    op.create_index(
        'uq_skill_versions_one_active',
        'agent_skill_versions',
        ['skill_id'],
        unique=True,
        postgresql_where=sa.text('is_active = TRUE'),
    )


def downgrade() -> None:
    op.drop_index('uq_skill_versions_one_active', table_name='agent_skill_versions')
    op.drop_index('idx_skill_versions_skill_id', table_name='agent_skill_versions')
    op.drop_table('agent_skill_versions')

    op.drop_index('idx_agent_skills_category', table_name='agent_skills')
    op.drop_index('idx_agent_skills_skill_key', table_name='agent_skills')
    op.drop_table('agent_skills')
