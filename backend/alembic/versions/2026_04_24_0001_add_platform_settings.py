"""add platform_settings

Revision ID: add_platform_settings
Revises: 0d7cee7bad2a
Create Date: 2026-04-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_platform_settings'
down_revision: Union[str, None] = '0d7cee7bad2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'platform_settings',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('platform_name', sa.String(length=128), nullable=False,
                  server_default=sa.text("'木兰 BI 平台'")),
        sa.Column('platform_subtitle', sa.String(length=256), nullable=True,
                  server_default=sa.text("'数据建模与治理平台'")),
        sa.Column('logo_url', sa.String(length=512), nullable=False,
                  server_default=sa.text("'https://public.readdy.ai/ai/img_res/d9bf8fa2-dfff-4c50-98cf-7b635309e7d6.png'")),
        sa.Column('favicon_url', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('now()')),
    )
    # Insert default record (idempotent — skips if already exists)
    op.execute("""
        INSERT INTO platform_settings (id, platform_name, platform_subtitle, logo_url, favicon_url, created_at, updated_at)
        VALUES (
            1,
            '木兰 BI 平台',
            '数据建模与治理平台',
            'https://public.readdy.ai/ai/img_res/d9bf8fa2-dfff-4c50-98cf-7b635309e7d6.png',
            NULL,
            now(),
            now()
        )
        ON CONFLICT (id) DO NOTHING
    """)


def downgrade() -> None:
    op.drop_table('platform_settings')
