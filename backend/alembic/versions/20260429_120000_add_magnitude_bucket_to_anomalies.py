"""add_magnitude_bucket_to_anomalies

Revision ID: 20260429_120000
Revises: 20260429_000001
Create Date: 2026-04-29 12:00:00.000000

Add fields to bi_metric_anomalies for Spec 30 §4.6 anomaly dedup and feedback learning:
- direction: VARCHAR(8), nullable - "up" or "down", direction of the anomaly
- dimension_context_hash: VARCHAR(64), nullable - SHA256 hash of dimension_context for dedup
- magnitude_bucket: VARCHAR(16), nullable - "tiny"|"small"|"medium"|"large"|"extreme"
- last_seen_at: TIMESTAMP, nullable - last time this anomaly was seen (for dedup window refresh)

Also adds composite index ix_bma_dedup for efficient dedup window queries.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260429_120000"
down_revision: str = "20260429_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add direction column (VARCHAR(8))
    op.add_column(
        "bi_metric_anomalies",
        sa.Column("direction", sa.String(length=8), nullable=True, comment="up | down"),
    )
    # Add dimension_context_hash column (VARCHAR(64))
    op.add_column(
        "bi_metric_anomalies",
        sa.Column(
            "dimension_context_hash",
            sa.String(length=64),
            nullable=True,
            comment="SHA256 hash of dimension_context",
        ),
    )
    # Add magnitude_bucket column (VARCHAR(16))
    op.add_column(
        "bi_metric_anomalies",
        sa.Column(
            "magnitude_bucket",
            sa.String(length=16),
            nullable=True,
            comment="tiny | small | medium | large | extreme",
        ),
    )
    # Add last_seen_at column (TIMESTAMP)
    op.add_column(
        "bi_metric_anomalies",
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
    )
    # Composite index for efficient dedup window queries
    op.create_index(
        "ix_bma_dedup",
        "bi_metric_anomalies",
        ["metric_id", "algorithm", "direction", "dimension_context_hash", "detected_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_bma_dedup", table_name="bi_metric_anomalies")
    op.drop_column("bi_metric_anomalies", "last_seen_at")
    op.drop_column("bi_metric_anomalies", "magnitude_bucket")
    op.drop_column("bi_metric_anomalies", "dimension_context_hash")
    op.drop_column("bi_metric_anomalies", "direction")
