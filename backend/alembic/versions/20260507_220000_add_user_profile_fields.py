"""add user profile fields (position, department, phone)

Revision ID: 20260507_220000
Revises: 20260506_233000
Create Date: 2026-05-07 22:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '20260507_220000'
down_revision = '20260506_233000'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('auth_users', sa.Column('position', sa.String(128), nullable=True))
    op.add_column('auth_users', sa.Column('department', sa.String(128), nullable=True))
    op.add_column('auth_users', sa.Column('phone', sa.String(32), nullable=True))


def downgrade():
    op.drop_column('auth_users', 'phone')
    op.drop_column('auth_users', 'department')
    op.drop_column('auth_users', 'position')
