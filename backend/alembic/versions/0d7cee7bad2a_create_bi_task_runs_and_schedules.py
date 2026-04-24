"""create_bi_task_runs_and_schedules

Revision ID: 0d7cee7bad2a
Revises: 04e780a305b9
Create Date: 2026-04-24 12:18:58.500107

Tables bi_task_runs and bi_task_schedules were created outside Alembic.
This migration stamps the revision without schema changes.
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '0d7cee7bad2a'
down_revision: Union[str, None] = '04e780a305b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
