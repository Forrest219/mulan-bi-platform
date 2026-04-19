"""add auth_password_reset_tokens

Revision ID: 20260420_020000
Revises: 20260420_010000
Create Date: 2026-04-20 02:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '20260420_020000'
down_revision = '20260420_010000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'auth_password_reset_tokens',
        sa.Column(
            'id',
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            'user_id',
            sa.Integer,
            sa.ForeignKey('auth_users.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column('token_hash', sa.VARCHAR(64), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime, server_default=sa.text("now() + interval '15 minutes'"), nullable=False),
        sa.Column('is_used', sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime,
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    op.create_index(
        'ix_auth_password_reset_tokens_user_id',
        'auth_password_reset_tokens',
        ['user_id'],
    )
    op.create_index(
        'ix_auth_password_reset_tokens_token_hash',
        'auth_password_reset_tokens',
        ['token_hash'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_auth_password_reset_tokens_token_hash', table_name='auth_password_reset_tokens')
    op.drop_index('ix_auth_password_reset_tokens_user_id', table_name='auth_password_reset_tokens')
    op.drop_table('auth_password_reset_tokens')
