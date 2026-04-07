"""Add MFA fields to auth_users (TOTP MFA 支持)

Revision ID: add_mfa_fields
Revises: add_refresh_tokens
Create Date: 2026-04-07

Revision notes:
- auth_users.mfa_enabled: 是否启用 MFA
- auth_users.mfa_secret_encrypted: Fernet 加密的 TOTP Secret
- auth_users.mfa_backup_codes_encrypted: Fernet 加密的 JSON 备用码数组
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "add_mfa_fields"
down_revision: Union[str, None] = "add_refresh_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column(
        "auth_users",
        sa.Column("mfa_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.add_column(
        "auth_users",
        sa.Column("mfa_secret_encrypted", sa.String(256), nullable=True)
    )
    op.add_column(
        "auth_users",
        sa.Column("mfa_backup_codes_encrypted", sa.String(1024), nullable=True)
    )


def downgrade():
    op.drop_column("auth_users", "mfa_backup_codes_encrypted")
    op.drop_column("auth_users", "mfa_secret_encrypted")
    op.drop_column("auth_users", "mfa_enabled")
