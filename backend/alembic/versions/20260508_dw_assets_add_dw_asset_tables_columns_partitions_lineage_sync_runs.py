"""add_dw_asset_tables_columns_partitions_lineage_sync_runs

Revision ID: 20260508_dw_assets
Revises: 20260508_kb_metric_ids
Create Date: 2026-05-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = '20260508_dw_assets'
down_revision: Union[str, None] = '20260508_kb_metric_ids'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dw_asset_tables',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('asset_uid', sa.String(192), nullable=False),
        sa.Column('datasource_id', sa.Integer(), nullable=False),
        sa.Column('database_name', sa.String(128), nullable=False),
        sa.Column('schema_name', sa.String(128), server_default=sa.text("''"), nullable=False),
        sa.Column('table_name', sa.String(256), nullable=False),
        sa.Column('table_type', sa.String(32), nullable=False),
        sa.Column('business_name', sa.String(256), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('table_comment', sa.Text(), nullable=True),
        sa.Column('domain', sa.String(64), nullable=True),
        sa.Column('layer', sa.String(32), nullable=True),
        sa.Column('tags_json', JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('owner_name', sa.String(128), nullable=True),
        sa.Column('row_count_estimate', sa.BigInteger(), nullable=True),
        sa.Column('storage_bytes', sa.BigInteger(), nullable=True),
        sa.Column('partition_type', sa.String(64), nullable=True),
        sa.Column('partition_key', sa.String(256), nullable=True),
        sa.Column('partition_count', sa.Integer(), nullable=True),
        sa.Column('last_partition_name', sa.String(256), nullable=True),
        sa.Column('last_partition_at', sa.DateTime(), nullable=True),
        sa.Column('heat_score', sa.Float(), server_default=sa.text('0'), nullable=False),
        sa.Column('query_count_7d', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('query_count_30d', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('last_queried_at', sa.DateTime(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('raw_metadata_json', JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('synced_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['datasource_id'], ['bi_data_sources.id'], name='fk_dw_table_datasource'),
        sa.ForeignKeyConstraint(['updated_by'], ['auth_users.id'], name='fk_dw_table_updated_by'),
        sa.UniqueConstraint('asset_uid', name='uq_dw_table_asset_uid'),
        sa.UniqueConstraint('datasource_id', 'database_name', 'schema_name', 'table_name', name='uq_dw_table_identity'),
    )
    op.create_index('ix_dw_table_ds_deleted', 'dw_asset_tables', ['datasource_id', 'is_deleted'])
    op.create_index('ix_dw_table_search', 'dw_asset_tables', ['table_name', 'business_name'])
    op.create_index('ix_dw_table_domain_layer', 'dw_asset_tables', ['domain', 'layer'])
    op.create_index('ix_dw_table_heat', 'dw_asset_tables', [sa.text('heat_score DESC')])

    op.create_table(
        'dw_asset_columns',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('table_id', sa.Integer(), nullable=False),
        sa.Column('column_name', sa.String(256), nullable=False),
        sa.Column('ordinal_position', sa.Integer(), nullable=False),
        sa.Column('data_type', sa.String(128), nullable=False),
        sa.Column('normalized_type', sa.String(64), nullable=True),
        sa.Column('is_nullable', sa.Boolean(), nullable=True),
        sa.Column('is_primary_key', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_partition_key', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('default_value', sa.Text(), nullable=True),
        sa.Column('column_comment', sa.Text(), nullable=True),
        sa.Column('business_name', sa.String(256), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sensitivity_level', sa.String(32), server_default=sa.text("'internal'"), nullable=False),
        sa.Column('sample_values_json', JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('stats_json', JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('raw_metadata_json', JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['table_id'], ['dw_asset_tables.id'], name='fk_dw_col_table', ondelete='CASCADE'),
        sa.UniqueConstraint('table_id', 'column_name', name='uq_dw_col_identity'),
    )
    op.create_index('ix_dw_col_table', 'dw_asset_columns', ['table_id', 'ordinal_position'])
    op.create_index('ix_dw_col_name', 'dw_asset_columns', ['column_name'])

    op.create_table(
        'dw_asset_partitions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('table_id', sa.Integer(), nullable=False),
        sa.Column('partition_name', sa.String(256), nullable=False),
        sa.Column('partition_value', sa.Text(), nullable=True),
        sa.Column('row_count_estimate', sa.BigInteger(), nullable=True),
        sa.Column('storage_bytes', sa.BigInteger(), nullable=True),
        sa.Column('visible_version', sa.String(64), nullable=True),
        sa.Column('raw_metadata_json', JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['table_id'], ['dw_asset_tables.id'], name='fk_dw_partition_table', ondelete='CASCADE'),
        sa.UniqueConstraint('table_id', 'partition_name', name='uq_dw_partition_identity'),
    )
    op.create_index('ix_dw_partition_table', 'dw_asset_partitions', ['table_id', 'partition_name'])

    op.create_table(
        'dw_asset_lineage_edges',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('lineage_type', sa.String(32), nullable=False),
        sa.Column('source_table_id', sa.Integer(), nullable=True),
        sa.Column('source_column_id', sa.Integer(), nullable=True),
        sa.Column('target_table_id', sa.Integer(), nullable=False),
        sa.Column('target_column_id', sa.Integer(), nullable=True),
        sa.Column('relation_type', sa.String(32), nullable=False),
        sa.Column('confidence', sa.Float(), server_default=sa.text('1.0'), nullable=False),
        sa.Column('source_system', sa.String(64), nullable=False),
        sa.Column('transformation_logic', sa.Text(), nullable=True),
        sa.Column('raw_metadata_json', JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['source_table_id'], ['dw_asset_tables.id'], name='fk_dw_lineage_source_table'),
        sa.ForeignKeyConstraint(['source_column_id'], ['dw_asset_columns.id'], name='fk_dw_lineage_source_col'),
        sa.ForeignKeyConstraint(['target_table_id'], ['dw_asset_tables.id'], name='fk_dw_lineage_target_table'),
        sa.ForeignKeyConstraint(['target_column_id'], ['dw_asset_columns.id'], name='fk_dw_lineage_target_col'),
        sa.CheckConstraint("lineage_type IN ('table', 'column')", name='ck_lineage_type_valid'),
        sa.CheckConstraint("lineage_type != 'table' OR source_table_id IS NOT NULL", name='ck_lineage_table_has_source'),
        sa.CheckConstraint(
            "lineage_type != 'column' OR (source_table_id IS NOT NULL AND source_column_id IS NOT NULL AND target_column_id IS NOT NULL)",
            name='ck_lineage_column_complete',
        ),
        sa.CheckConstraint("source_table_id IS NULL OR source_table_id != target_table_id", name='ck_lineage_no_self_loop'),
    )
    op.create_index('ix_dw_lineage_source', 'dw_asset_lineage_edges', ['source_table_id'])
    op.create_index('ix_dw_lineage_target', 'dw_asset_lineage_edges', ['target_table_id'])

    op.create_table(
        'dw_asset_sync_runs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('datasource_id', sa.Integer(), nullable=False),
        sa.Column('trigger_type', sa.String(32), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('tables_found', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('tables_upserted', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('columns_upserted', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('partitions_upserted', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('details_json', JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('operator_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['datasource_id'], ['bi_data_sources.id'], name='fk_dw_sync_datasource'),
    )
    op.create_index('ix_dw_sync_ds_started', 'dw_asset_sync_runs', ['datasource_id', sa.text('started_at DESC')])


def downgrade() -> None:
    op.drop_table('dw_asset_sync_runs')
    op.drop_table('dw_asset_lineage_edges')
    op.drop_table('dw_asset_partitions')
    op.drop_table('dw_asset_columns')
    op.drop_table('dw_asset_tables')
