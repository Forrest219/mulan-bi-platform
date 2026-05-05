"""add extra_settings JSONB column to platform_settings

Revision ID: add_extra_settings_platform_settings
Revises: add_intent_log_fields
Create Date: 2026-04-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_extra_settings_ps'
down_revision: Union[str, None] = 'add_intent_log_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add extra_settings JSONB column for key-value feature flags (Spec 36 §15 homepage_agent_mode)
    op.add_column(
        'platform_settings',
        sa.Column('extra_settings', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default=sa.text("'{}'::jsonb"))
    )


def downgrade() -> None:
    op.drop_column('platform_settings', 'extra_settings')
