"""add message_feedback table

Revision ID: 20260419_000000
Revises: add_llm_api_key_updated_at
Create Date: 2026-04-19

消息反馈表，记录用户对 AI 回答的点赞/踩反馈。
关联 Spec: docs/specs/feedback-api-spec.md
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260419_000000'
down_revision: Union[str, None] = 'add_llm_api_key_updated_at'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        'message_feedback',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('conversation_id', sa.String(), nullable=True),
        sa.Column('message_index', sa.Integer(), nullable=True),
        sa.Column('question', sa.Text(), nullable=True),
        sa.Column('answer_summary', sa.Text(), nullable=True),
        sa.Column('rating', sa.String(4), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.CheckConstraint("rating IN ('up', 'down')", name='ck_message_feedback_rating'),
    )


def downgrade() -> None:
    op.drop_table('message_feedback')
