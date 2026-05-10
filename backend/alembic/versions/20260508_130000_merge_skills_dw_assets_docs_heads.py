"""merge_skills_dw_assets_docs_heads

将三条并行开发链合并为单一 head：
  - 20260508_skill_version_id  (技能中心：bi_agent_steps.skill_version_id)
  - 20260508_dw_assets         (数仓资产表)
  - 20260508_000001            (kb_documents.doc_type)

Revision ID: 20260508_merge_skills_heads
Revises: 20260508_skill_version_id, 20260508_dw_assets, 20260508_000001
Create Date: 2026-05-08 13:00:00

"""
from typing import Sequence, Union

revision: str = '20260508_merge_skills_heads'
down_revision: Union[tuple, None] = (
    '20260508_skill_version_id',
    '20260508_dw_assets',
    '20260508_000001',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
