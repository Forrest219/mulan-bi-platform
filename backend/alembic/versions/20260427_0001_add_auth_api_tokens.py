"""add_auth_api_tokens

Revision ID: 20260427_0001
Revises: 20260426_0002
Create Date: 2026-04-27 00:00:00.000000

Spec 27 - Account & Settings Week 1:
- auth_api_tokens: API Token table for programmatic/token-based authentication
  - token_hash: SHA-256 hash (never stores plaintext token)
  - prefix: first 8 chars of raw token for user identification
  - scopes: JSONB array of allowed scopes (null = inherit user permissions)
  - expires_at: nullable, null means never expires
  - revoked_at: nullable, non-null means revoked
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "20260427_0001"
down_revision: Union[str, None] = "20260426_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_api_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("scopes", JSONB(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_tokens_user_id", "auth_api_tokens", ["user_id"])
    op.create_index(
        "ix_api_tokens_token_hash", "auth_api_tokens", ["token_hash"], unique=True
    )
    op.create_index("ix_api_tokens_prefix", "auth_api_tokens", ["prefix"])


def downgrade() -> None:
    op.drop_index("ix_api_tokens_prefix", table_name="auth_api_tokens")
    op.drop_index("ix_api_tokens_token_hash", table_name="auth_api_tokens")
    op.drop_index("ix_api_tokens_user_id", table_name="auth_api_tokens")
    op.drop_table("auth_api_tokens")
