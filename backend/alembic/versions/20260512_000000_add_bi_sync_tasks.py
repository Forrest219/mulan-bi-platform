"""add bi_sync_tasks table (Spec 43)

Revision ID: 20260512_000000
Revises: 31b9d407f9d3
Create Date: 2026-05-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260512_000000"
down_revision = "31b9d407f9d3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bi_sync_tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "schedule_id",
            sa.Integer(),
            sa.ForeignKey("bi_sync_schedules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("tableau_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("trigger_type", sa.String(16), nullable=False, server_default="scheduled"),
        sa.Column(
            "sync_log_id",
            sa.BigInteger(),
            sa.ForeignKey("tableau_sync_logs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("schedule_id", "connection_id", "scheduled_at", name="uq_sync_task"),
    )

    op.create_index("ix_sync_tasks_connection", "bi_sync_tasks", ["connection_id", "scheduled_at"])
    op.create_index("ix_sync_tasks_schedule", "bi_sync_tasks", ["schedule_id", "scheduled_at"])
    op.create_index("ix_sync_tasks_status", "bi_sync_tasks", ["status", "scheduled_at"])


def downgrade():
    op.drop_index("ix_sync_tasks_status", table_name="bi_sync_tasks")
    op.drop_index("ix_sync_tasks_schedule", table_name="bi_sync_tasks")
    op.drop_index("ix_sync_tasks_connection", table_name="bi_sync_tasks")
    op.drop_table("bi_sync_tasks")
