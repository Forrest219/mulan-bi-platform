"""add_bi_metric_bindings_aliases

Revision ID: f0345f080341
Revises: 20260514_010000
Create Date: 2026-05-14 16:48:09.792311

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f0345f080341"
down_revision: Union[str, None] = "20260514_010000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bi_metric_aliases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("metric_id", sa.UUID(), nullable=False),
        sa.Column("alias", sa.String(length=128), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["metric_id"], ["bi_metric_definitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "metric_id", "alias", name="uq_bma_tenant_metric_alias"),
    )
    op.create_index("ix_bma_metric_active", "bi_metric_aliases", ["metric_id", "is_active"], unique=False)
    op.create_index(
        "ix_bma_tenant_alias_active",
        "bi_metric_aliases",
        ["tenant_id", "alias", "is_active"],
        unique=False,
    )

    op.create_table(
        "bi_metric_bindings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("metric_id", sa.UUID(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("datasource_id", sa.Integer(), nullable=True),
        sa.Column("tableau_connection_id", sa.Integer(), nullable=True),
        sa.Column("tableau_asset_id", sa.BigInteger(), nullable=True),
        sa.Column("tableau_datasource_luid", sa.String(length=128), nullable=True),
        sa.Column("field_mappings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("required_base_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("formula_expression", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("queryable_fields_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["metric_id"], ["bi_metric_definitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bmb_datasource", "bi_metric_bindings", ["datasource_id"], unique=False)
    op.create_index(
        "ix_bmb_tableau_source",
        "bi_metric_bindings",
        ["tableau_connection_id", "tableau_datasource_luid"],
        unique=False,
    )
    op.create_index(
        "ix_bmb_tenant_metric_active",
        "bi_metric_bindings",
        ["tenant_id", "metric_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "uq_bmb_primary_tableau_binding",
        "bi_metric_bindings",
        ["tenant_id", "metric_id"],
        unique=True,
        postgresql_where=sa.text(
            "is_active = true AND is_primary = true AND source_type = 'tableau_published_datasource'"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_bmb_primary_tableau_binding", table_name="bi_metric_bindings")
    op.drop_index("ix_bmb_tenant_metric_active", table_name="bi_metric_bindings")
    op.drop_index("ix_bmb_tableau_source", table_name="bi_metric_bindings")
    op.drop_index("ix_bmb_datasource", table_name="bi_metric_bindings")
    op.drop_table("bi_metric_bindings")

    op.drop_index("ix_bma_tenant_alias_active", table_name="bi_metric_aliases")
    op.drop_index("ix_bma_metric_active", table_name="bi_metric_aliases")
    op.drop_table("bi_metric_aliases")
