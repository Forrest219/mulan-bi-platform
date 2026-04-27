"""add_auth_password_reset_tokens_and_ip_ua

Revision ID: 20260426_0002
Revises: ba52b50f68f8
Create Date: 2026-04-26 00:00:00.000000

Spec 27 - Account & Settings:
- auth_password_reset_tokens: password reset token table (SHA-256 hashed, 15min expiry, one-time use)
- Add ip_address, user_agent to auth_refresh_tokens

Revision notes:
- Token storage: SHA-256 hash (never store plaintext token)
- 15-minute expiry for password reset tokens
- One-time use: is_used=true after successful reset
- ip_address supports IPv6 (VARCHAR 45)
- user_agent stores browser User-Agent (VARCHAR 512)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260426_0002"
down_revision: Union[str, None] = "ba52b50f68f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add ip_address and user_agent columns to auth_refresh_tokens
    op.add_column(
        "auth_refresh_tokens",
        sa.Column("ip_address", sa.String(45), nullable=True),
    )
    op.add_column(
        "auth_refresh_tokens",
        sa.Column("user_agent", sa.String(512), nullable=True),
    )

    # 2. Create auth_password_reset_tokens table
    op.create_table(
        "auth_password_reset_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "is_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_password_reset_tokens_user_id",
        "auth_password_reset_tokens",
        ["user_id"],
    )
    op.create_index(
        "ix_password_reset_tokens_token_hash",
        "auth_password_reset_tokens",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_password_reset_tokens_token_hash", table_name="auth_password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="auth_password_reset_tokens")
    op.drop_table("auth_password_reset_tokens")
    op.drop_column("auth_refresh_tokens", "user_agent")
    op.drop_column("auth_refresh_tokens", "ip_address")
