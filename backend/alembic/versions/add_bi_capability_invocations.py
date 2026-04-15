"""add bi_capability_invocations for homepage Ask audit (Append-Only)

Revision ID: add_bi_capability_invocations
Revises: add_field_semantics_embedding
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "add_bi_capability_invocations"
down_revision = "add_field_semantics_embedding"


def upgrade():
    op.create_table(
        "bi_capability_invocations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("trace_id", sa.String(64), nullable=False, index=True),
        sa.Column("principal_id", sa.Integer, nullable=False, index=True),
        sa.Column("principal_role", sa.String(32), nullable=False),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("params_jsonb", JSONB, nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("mcp_call_id", sa.BigInteger, nullable=True),
        sa.Column("llm_tokens_in", sa.Integer, nullable=True),
        sa.Column("llm_tokens_out", sa.Integer, nullable=True),
        sa.Column("redacted_fields", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_cap_inv_created_at", "bi_capability_invocations", ["created_at"])
    op.create_index("ix_cap_inv_trace_status", "bi_capability_invocations", ["trace_id", "status"])


def downgrade():
    op.drop_index("ix_cap_inv_trace_status", table_name="bi_capability_invocations")
    op.drop_index("ix_cap_inv_created_at", table_name="bi_capability_invocations")
    op.drop_table("bi_capability_invocations")
