"""add message_feedback table for chat thumbs up/down

Revision ID: add_message_feedback_table
Revises: add_query_feedback_table
"""
from alembic import op
import sqlalchemy as sa

revision = "add_message_feedback_table"
down_revision = "add_query_feedback_table"


def upgrade():
    op.create_table(
        "message_feedback",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("username", sa.String(128), nullable=False, server_default=""),
        sa.Column("conversation_id", sa.String(128), nullable=True),
        sa.Column("message_index", sa.Integer, nullable=True),
        sa.Column("question", sa.Text, nullable=True),
        sa.Column("answer_summary", sa.String(100), nullable=True),
        sa.Column("rating", sa.String(4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("rating IN ('up', 'down')", name="ck_message_feedback_rating"),
    )
    op.create_index("ix_message_feedback_user_id", "message_feedback", ["user_id"])
    op.create_index("ix_message_feedback_conversation_id", "message_feedback", ["conversation_id"])


def downgrade():
    op.drop_table("message_feedback")
