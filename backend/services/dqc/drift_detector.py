"""漂移检测

对每个 (asset_id, dimension) 计算：
- drift_24h = current_score - prev_score（最近一条非本 cycle 的 dimension_score）
- drift_vs_7d_avg = current_score - avg(过去 7 天同维度分)
返回方向为 current - history，负值代表下降。
"""
from datetime import datetime
from typing import Dict, Optional

from sqlalchemy.orm import Session

from .database import DqcDatabase


class DriftDetector:
    def __init__(self, dao: Optional[DqcDatabase] = None):
        self.dao = dao or DqcDatabase()

    def compute_prev_scores(
        self, db: Session, asset_id: int, before: Optional[datetime] = None
    ) -> Dict[str, float]:
        """返回 {dimension: prev_score}

        取严格早于 `before` 的最近一条维度分；未提供 before 则取当前时间。
        """
        ref = before or datetime.utcnow()
        return self.dao.get_prev_dimension_scores(db, asset_id, ref)

    def compute_7d_avg(
        self, db: Session, asset_id: int, now: Optional[datetime] = None
    ) -> Dict[str, float]:
        """返回 {dimension: avg_score}，窗口 [now-7d, now)"""
        return self.dao.get_7d_avg_dimension_scores(db, asset_id, now)

    @staticmethod
    def compute_drift(current_score: float, prev_score: Optional[float]) -> Optional[float]:
        """单点漂移：当前 - 前值。prev 为空返回 None。"""
        if prev_score is None:
            return None
        return round(current_score - prev_score, 4)
