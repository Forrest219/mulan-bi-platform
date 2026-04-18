"""add mcp credentials column

Revision ID: 20260417_010000
Revises: 20260417_000000
Create Date: 2026-04-17

"""
revision = '20260417_010000'
down_revision = '20260417_000000'
branch_labels = None
depends_on = None

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


def upgrade():
    op.add_column('mcp_servers',
        sa.Column('credentials', postgresql.JSONB(), nullable=True)
    )


def downgrade():
    op.drop_column('mcp_servers', 'credentials')
