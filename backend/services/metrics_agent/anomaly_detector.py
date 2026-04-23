"""Metrics Agent — 异常检测算法层（纯计算，无数据库依赖）

提供三种异常检测算法：
- Z-Score：基于均值和标准差的统计偏差检测
- 分位数：基于历史数据分布区间的异常检测
- 趋势偏离：基于线性趋势外推的偏差检测
"""

import statistics
from dataclasses import dataclass

# 最少需要 3 个数据点（含当前值），即历史窗口至少 2 个点
_MIN_POINTS = 3


@dataclass
class AnomalyResult:
    is_anomaly: bool
    metric_value: float       # 当前值（最新数据点）
    expected_value: float     # 期望值（算法计算）
    deviation_score: float    # 偏差分数（z-score / 分位距离 / 趋势偏差）
    deviation_threshold: float


def _not_enough_data(current: float) -> AnomalyResult:
    """数据点不足时返回无异常的默认结果。"""
    return AnomalyResult(
        is_anomaly=False,
        metric_value=current,
        expected_value=current,
        deviation_score=0.0,
        deviation_threshold=0.0,
    )


def detect_zscore(values: list[float], threshold: float = 3.0) -> AnomalyResult:
    """Z-Score 异常检测。

    values[-1] 为当前值，其余为历史窗口。最少需 3 个数据点。

    算法：
    - mean = mean(values[:-1])
    - std = stdev(values[:-1])
    - z = abs(current - mean) / std（std==0 时视为无异常，z=0）
    - is_anomaly = z > threshold
    """
    if len(values) < _MIN_POINTS:
        return _not_enough_data(values[-1] if values else 0.0)

    current = values[-1]
    history = values[:-1]

    mean = statistics.mean(history)
    # stdev 需要至少 2 个样本
    if len(history) < 2:
        return _not_enough_data(current)

    std = statistics.stdev(history)
    if std == 0:
        z = 0.0
    else:
        z = abs(current - mean) / std

    return AnomalyResult(
        is_anomaly=z > threshold,
        metric_value=current,
        expected_value=mean,
        deviation_score=z,
        deviation_threshold=threshold,
    )


def detect_quantile(
    values: list[float],
    lower_q: float = 0.05,
    upper_q: float = 0.95,
) -> AnomalyResult:
    """分位数异常检测。

    当前值落在历史数据 [lower_q, upper_q] 区间外视为异常。

    算法：
    - 对 values[:-1] 排序
    - lower = sorted_vals[int(lower_q * n)]（向下取整）
    - upper = sorted_vals[int(upper_q * n) - 1]（向上取整边界）
    - deviation_score = max(lower - current, current - upper, 0)
    """
    if len(values) < _MIN_POINTS:
        return _not_enough_data(values[-1] if values else 0.0)

    current = values[-1]
    history = values[:-1]
    n = len(history)

    mean = statistics.mean(history)
    sorted_vals = sorted(history)

    # 计算分位数边界
    lower_idx = max(0, int(lower_q * n))
    upper_idx = min(n - 1, max(0, int(upper_q * n) - 1))

    lower = sorted_vals[lower_idx]
    upper = sorted_vals[upper_idx]

    # 若 lower > upper（极少量数据时可能发生），互换
    if lower > upper:
        lower, upper = upper, lower

    deviation_score = max(lower - current, current - upper, 0.0)
    is_anomaly = deviation_score > 0

    return AnomalyResult(
        is_anomaly=is_anomaly,
        metric_value=current,
        expected_value=mean,
        deviation_score=deviation_score,
        deviation_threshold=0.0,  # 分位数方法无固定阈值，用 0 表示"在区间外即异常"
    )


def detect_trend_deviation(
    values: list[float],
    threshold_pct: float = 20.0,
) -> AnomalyResult:
    """趋势偏离异常检测。

    用历史数据（values[:-1]）做线性回归，外推预测当前值，
    实际值与预测值偏差超过 threshold_pct% 则视为异常。

    算法（Python 3.10+ statistics.linear_regression）：
    - x = [0, 1, 2, ..., n-1]，y = values[:-1]
    - 线性回归得到 slope, intercept
    - expected = slope * n + intercept（预测第 n 个点，即当前值位置）
    - deviation_pct = abs(current - expected) / max(abs(expected), 1) * 100
    - is_anomaly = deviation_pct > threshold_pct
    """
    if len(values) < _MIN_POINTS:
        return _not_enough_data(values[-1] if values else 0.0)

    current = values[-1]
    history = values[:-1]
    n = len(history)

    x = list(range(n))
    y = history

    # 使用 statistics.linear_regression（Python 3.10+）
    try:
        regression = statistics.linear_regression(x, y)
        slope = regression.slope
        intercept = regression.intercept
    except AttributeError:
        # 回退：手动实现最小二乘线性回归
        slope, intercept = _manual_linear_regression(x, y)

    # 预测当前位置（索引 n）
    expected = slope * n + intercept

    # 计算偏差百分比，避免除零
    denominator = max(abs(expected), 1.0)
    deviation_pct = abs(current - expected) / denominator * 100.0

    return AnomalyResult(
        is_anomaly=deviation_pct > threshold_pct,
        metric_value=current,
        expected_value=expected,
        deviation_score=deviation_pct,
        deviation_threshold=threshold_pct,
    )


def _manual_linear_regression(x: list[float], y: list[float]) -> tuple[float, float]:
    """手动实现最小二乘线性回归，返回 (slope, intercept)。

    不依赖 numpy/scipy，纯 Python 实现。
    """
    n = len(x)
    if n == 0:
        return 0.0, 0.0

    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    sum_xx = sum(xi * xi for xi in x)

    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        # 所有 x 值相同（退化情况），斜率为 0
        return 0.0, sum_y / n

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    return slope, intercept
