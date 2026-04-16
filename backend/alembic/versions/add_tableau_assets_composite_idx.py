"""add composite index on tableau_assets(connection_id, is_deleted, asset_type)

Revision ID: add_tableau_assets_composite_idx
Revises: add_bi_capability_invocations

架构审查 R1 §5.2 高严重度问题：
tableau_assets 资产列表（最高频查询）无 (connection_id, is_deleted, asset_type)
复合索引，可能全表扫描。
"""
from typing import Union

from alembic import op

revision = "add_tableau_assets_composite_idx"
down_revision = "add_bi_capability_invocations"


def upgrade():
    op.create_index(
        "ix_tableau_assets_conn_deleted_type",
        "tableau_assets",
        ["connection_id", "is_deleted", "asset_type"],
    )
    # 同时为 bi_health_scan_records 添加 (datasource_id, status) 复合索引
    op.create_index(
        "ix_health_scan_records_ds_status",
        "bi_health_scan_records",
        ["datasource_id", "status"],
    )


def downgrade():
    op.drop_index("ix_health_scan_records_ds_status", table_name="bi_health_scan_records")
    op.drop_index("ix_tableau_assets_conn_deleted_type", table_name="tableau_assets")
