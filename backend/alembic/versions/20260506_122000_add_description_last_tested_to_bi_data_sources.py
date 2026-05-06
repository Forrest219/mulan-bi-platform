"""add description last_tested_at last_test_success to bi_data_sources

Revision ID: f7e8d9c0b1a2
Revises: 1aef64171005
Create Date: 2026-05-06 12:20:00

"""
from alembic import op
import sqlalchemy as sa

revision = 'f7e8d9c0b1a2'
down_revision = '1aef64171005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('bi_data_sources', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('bi_data_sources', sa.Column('last_tested_at', sa.DateTime(), nullable=True))
    op.add_column('bi_data_sources', sa.Column('last_test_success', sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column('bi_data_sources', 'last_test_success')
    op.drop_column('bi_data_sources', 'last_tested_at')
    op.drop_column('bi_data_sources', 'description')
