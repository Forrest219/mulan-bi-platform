"""merge_two_heads

Revision ID: 20260420_000000
Revises: ('20260417_010000', 'add_llm_api_key_updated_at')
Create Date: 2026-04-20

合并历史遗留双头：mcp_credentials 链 + llm_purpose 链
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = '20260420_000000'
down_revision: Union[str, None] = ('20260417_010000', 'add_llm_api_key_updated_at')
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    pass  # 纯合并节点，不做表结构变更


def downgrade() -> None:
    pass
