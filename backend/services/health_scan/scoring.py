"""数仓健康扫描评分 — 单一权威实现

所有需要健康分的地方都从这里导入，禁止在调用方内联公式。
"""
from typing import Optional


def calculate_health_score(high: int, medium: int, low: int, total_tables: int) -> Optional[float]:
    """密度扣分制：per-table 平均违规密度 × 10 分。

    权重：error=5, warning=2, info=0.5
    total_tables=0 时返回 None（无数据，不出分）。
    """
    if total_tables == 0:
        return None
    density = (high * 5 + medium * 2 + low * 0.5) / total_tables
    return max(0.0, round(100 - density * 10, 1))
