"""add_skill_version_id_to_agent_steps

Revision ID: 20260508_skill_version_id
Revises: 20260508_skills_tables
Create Date: 2026-05-08 12:00:01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '20260508_skill_version_id'
down_revision: Union[str, None] = '20260508_skills_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'bi_agent_steps',
        sa.Column(
            'skill_version_id',
            UUID(as_uuid=True),
            sa.ForeignKey('agent_skill_versions.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('bi_agent_steps', 'skill_version_id')
