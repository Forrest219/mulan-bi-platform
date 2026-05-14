"""metrics_agent_v04_minimum

Revision ID: 20260514_020000
Revises: f0345f080341
Create Date: 2026-05-14 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260514_020000"
down_revision: Union[str, None] = "f0345f080341"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bi_metric_definitions", sa.Column("metric_code", sa.String(length=32), nullable=True))
    op.execute(
        """
        WITH numbered AS (
            SELECT
                id,
                'MET-' || lpad(
                    row_number() OVER (PARTITION BY tenant_id ORDER BY created_at, id)::text,
                    6,
                    '0'
                ) AS generated_code
            FROM bi_metric_definitions
            WHERE metric_code IS NULL
        )
        UPDATE bi_metric_definitions m
        SET metric_code = numbered.generated_code
        FROM numbered
        WHERE m.id = numbered.id
        """
    )
    op.alter_column("bi_metric_definitions", "metric_code", nullable=False)
    op.create_unique_constraint(
        "uq_bmd_tenant_metric_code",
        "bi_metric_definitions",
        ["tenant_id", "metric_code"],
    )
    op.create_index(
        "ix_bmd_metric_code",
        "bi_metric_definitions",
        ["tenant_id", "metric_code"],
        unique=False,
    )

    op.execute(
        """
        UPDATE bi_metric_definitions
        SET name_zh = COALESCE(NULLIF(name_zh, ''), name, metric_code)
        WHERE name_zh IS NULL OR name_zh = ''
        """
    )
    op.alter_column("bi_metric_definitions", "name", existing_type=sa.String(length=128), nullable=True)
    op.alter_column("bi_metric_definitions", "name_zh", existing_type=sa.String(length=256), nullable=False)
    op.alter_column("bi_metric_definitions", "datasource_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("bi_metric_definitions", "table_name", existing_type=sa.String(length=128), nullable=True)
    op.alter_column("bi_metric_definitions", "column_name", existing_type=sa.String(length=128), nullable=True)

    op.create_table(
        "bi_metric_dependencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("depends_on_metric_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dependency_role", sa.String(length=32), nullable=False),
        sa.Column("expression_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("metric_id <> depends_on_metric_id", name="ck_bmdp_no_self_dependency"),
        sa.ForeignKeyConstraint(["metric_id"], ["bi_metric_definitions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["depends_on_metric_id"], ["bi_metric_definitions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "metric_id",
            "depends_on_metric_id",
            "dependency_role",
            name="uq_bmdp_metric_dep_role",
        ),
    )
    op.create_index("ix_bmdp_metric", "bi_metric_dependencies", ["tenant_id", "metric_id"], unique=False)
    op.create_index(
        "ix_bmdp_depends_on",
        "bi_metric_dependencies",
        ["tenant_id", "depends_on_metric_id"],
        unique=False,
    )
    op.create_index("ix_bmdp_role", "bi_metric_dependencies", ["tenant_id", "dependency_role"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bmdp_role", table_name="bi_metric_dependencies")
    op.drop_index("ix_bmdp_depends_on", table_name="bi_metric_dependencies")
    op.drop_index("ix_bmdp_metric", table_name="bi_metric_dependencies")
    op.drop_table("bi_metric_dependencies")

    op.execute(
        """
        UPDATE bi_metric_definitions
        SET
            name = COALESCE(
                name,
                lower(regexp_replace(metric_code, '[^a-zA-Z0-9]+', '_', 'g'))
            ),
            table_name = COALESCE(table_name, ''),
            column_name = COALESCE(column_name, '')
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM bi_metric_definitions WHERE datasource_id IS NULL)
               AND NOT EXISTS (SELECT 1 FROM bi_data_sources) THEN
                INSERT INTO bi_data_sources
                    (name, db_type, host, port, database_name, username, password_encrypted, owner_id, is_active)
                VALUES
                    ('legacy_metrics_downgrade_placeholder', 'postgresql', 'localhost', 5432,
                     'placeholder', 'placeholder', 'placeholder', 0, false);
            END IF;
        END $$;
        UPDATE bi_metric_definitions
        SET datasource_id = (SELECT id FROM bi_data_sources ORDER BY id LIMIT 1)
        WHERE datasource_id IS NULL
        """
    )
    op.alter_column("bi_metric_definitions", "column_name", existing_type=sa.String(length=128), nullable=False)
    op.alter_column("bi_metric_definitions", "table_name", existing_type=sa.String(length=128), nullable=False)
    op.alter_column("bi_metric_definitions", "name_zh", existing_type=sa.String(length=256), nullable=True)
    op.alter_column("bi_metric_definitions", "name", existing_type=sa.String(length=128), nullable=False)
    op.alter_column("bi_metric_definitions", "datasource_id", existing_type=sa.Integer(), nullable=False)

    op.drop_index("ix_bmd_metric_code", table_name="bi_metric_definitions")
    op.drop_constraint("uq_bmd_tenant_metric_code", "bi_metric_definitions", type_="unique")
    op.drop_column("bi_metric_definitions", "metric_code")
