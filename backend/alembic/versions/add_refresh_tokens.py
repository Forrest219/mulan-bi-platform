"""Add auth_refresh_tokens table (JWT Refresh Token 支持)

Revision ID: add_refresh_tokens
Revises: add_nlq_query_logs
Create Date: 2026-04-07

Revision notes:
- auth_refresh_tokens: JWT Refresh Token 存储表
  - token_hash: SHA-256 hash of raw token（不存原始 token）
  - 30 天 Sliding Window 有效期
  - 支持"退出所有设备"功能（revoke_all）
  - CASCADE 删除：用户删除时自动清理其 refresh tokens
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "add_refresh_tokens"
down_revision: Union[str, None] = "add_nlq_query_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id", sa.Integer(), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("device_fingerprint", sa.String(256), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_refresh_tokens_user_id", "auth_refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "auth_refresh_tokens", ["token_hash"], unique=True)


def downgrade():
    op.drop_index("ix_refresh_tokens_token_hash", table_name="auth_refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="auth_refresh_tokens")
    op.drop_table("auth_refresh_tokens")
