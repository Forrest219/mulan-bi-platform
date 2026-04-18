revision = '20260417_000000'
down_revision = '20260416_020000'

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.create_table(
        'mcp_servers',
        sa.Column('id',          sa.Integer(),     primary_key=True),
        sa.Column('name',        sa.String(128),   nullable=False),
        sa.Column('type',        sa.String(32),    nullable=False, server_default='custom'),
        sa.Column('server_url',  sa.String(512),   nullable=False),
        sa.Column('description', sa.Text(),        nullable=True),
        sa.Column('is_active',   sa.Boolean(),     nullable=False, server_default='false'),
        sa.Column('created_at',  sa.DateTime(),    nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at',  sa.DateTime(),    nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_mcp_servers_name', 'mcp_servers', ['name'], unique=True)
    op.create_index('ix_mcp_servers_type_active', 'mcp_servers', ['type', 'is_active'])


def downgrade():
    op.drop_table('mcp_servers')
