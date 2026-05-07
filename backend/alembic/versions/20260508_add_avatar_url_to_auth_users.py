"""add avatar_url to auth_users

Revision ID: 20260508_000003
Revises: f28340403f9f
Create Date: 2026-05-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '20260508_000003'
down_revision = 'f28340403f9f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('auth_users', sa.Column('avatar_url', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('auth_users', 'avatar_url')
