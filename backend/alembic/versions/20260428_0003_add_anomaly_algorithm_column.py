"""add_anomaly_algorithm_column — Spec 30 T2.4

bi_metric_anomalies 表新增 algorithm 列（VARCHAR(16)），用于标识异常检测算法：
- zscore：Z-Score 滑动窗口检测
- quantile：IQR 分位数滑动窗口检测

与 detection_method 列的关系：
- detection_method：检测触发方式（zscore/quantile/trend_deviation/threshold_breach）
- algorithm：具体算法实现（zscore / quantile）

Revision ID: add_anomaly_algorithm_column
Revises: add_bi_agent_intent_log
Create Date: 2026-04-28
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "add_anomaly_algorithm_column"
down_revision: Union[str, None] = "add_bi_agent_intent_log"
branch_labels: Union[str, tuple[str], None] = None
depends_on: Union[str, tuple[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bi_metric_anomalies",
        sa.Column("algorithm", sa.String(16), nullable=True, comment="zscore | quantile"),
    )
    # 索引优化：algorithm 列常用于过滤查询
    op.create_index("ix_bma_algorithm", "bi_metric_anomalies", ["algorithm"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bma_algorithm", table_name="bi_metric_anomalies")
    op.drop_column("bi_metric_anomalies", "algorithm")