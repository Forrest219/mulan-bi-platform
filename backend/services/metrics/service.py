import logging

from services.metrics_agent.anomaly_detector import (
    AnomalyResult,
    detect_quantile,
    detect_trend_deviation,
    detect_zscore,
)
from services.metrics_agent.anomaly_service import (
    run_anomaly_detection as _run_detection,
    update_anomaly_status,
)

logger = logging.getLogger(__name__)


# =============================================================================
# detect_anomalies — IQR-based sliding window anomaly detection
# =============================================================================


def detect_anomalies(
    series: list[float],
    *,
    method: str = "zscore",
    window_size: int = 7,
    k: float = 1.5,
    min_periods: int = 3,
) -> dict:
    """
    IQR-based sliding window anomaly detection.

    Parameters
    ----------
    series : list[float]
        数值数组
    method : str
        zscore | quantile
    window_size : int
        滑动窗口大小（默认 7）
    k : float
        IQR 倍数（默认 1.5）
    min_periods : int
        最小数据点数（默认 3），数据点 < min_periods 时返回空

    Returns
    -------
    dict with keys:
        anomalies: [{index, value, score}]
        lower_bound, upper_bound, q1, q3, iqr, method
    """
    if len(series) < min_periods:
        return {
            "anomalies": [],
            "lower_bound": 0.0,
            "upper_bound": 0.0,
            "q1": 0.0,
            "q3": 0.0,
            "iqr": 0.0,
            "method": method,
        }

    if method == "zscore":
        return _detect_zscore_sliding(series, window_size=window_size, min_periods=min_periods)
    elif method == "quantile":
        return _detect_quantile_sliding(series, window_size=window_size, k=k, min_periods=min_periods)
    else:
        raise ValueError(f"Unsupported method: {method}, valid: zscore | quantile")


def _detect_zscore_sliding(series: list[float], window_size: int, min_periods: int) -> dict:
    """Z-Score sliding window detection."""
    import statistics

    anomalies = []
    lower_bound = upper_bound = q1 = q3 = iqr = 0.0

    for i in range(min_periods - 1, len(series)):
        window = series[max(0, i - window_size + 1): i]
        if len(window) < 2:
            continue

        mean = statistics.mean(window)
        if len(window) < 2:
            std = 0.0
        else:
            std = statistics.stdev(window)

        current = series[i]
        if std > 0:
            z = abs(current - mean) / std
        else:
            z = 0.0

        if z > 3.0:
            anomalies.append({"index": i, "value": current, "score": round(z, 4)})

    # Compute final bounds for response
    if len(series) >= min_periods:
        tail = series[-(window_size):]
        q1_val = statistics.quantiles(tail, n=4)[0]
        q3_val = statistics.quantiles(tail, n=4)[2]
        iqr = q3_val - q1_val
        q1 = q1_val
        q3 = q3_val
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr

    # Apply false positive window: need 3 consecutive anomalies
    filtered = _filter_false_positives(anomalies)

    return {
        "anomalies": filtered,
        "lower_bound": round(lower_bound, 4),
        "upper_bound": round(upper_bound, 4),
        "q1": round(q1, 4),
        "q3": round(q3, 4),
        "iqr": round(iqr, 4),
        "method": "zscore",
    }


def _detect_quantile_sliding(series: list[float], window_size: int, k: float, min_periods: int) -> dict:
    """IQR-based quantile sliding window detection."""
    import statistics

    anomalies = []
    lower_bound = upper_bound = q1 = q3 = iqr = 0.0

    for i in range(min_periods - 1, len(series)):
        window = series[max(0, i - window_size + 1): i]
        if len(window) < 3:
            continue

        sorted_win = sorted(window)
        n = len(sorted_win)

        # Q1 = 25th percentile, Q3 = 75th percentile
        q1_val = sorted_win[int(0.25 * (n - 1))]
        q3_val = sorted_win[int(0.75 * (n - 1))]
        iqr_val = q3_val - q1_val

        current = series[i]
        lower = q1_val - k * iqr_val
        upper = q3_val + k * iqr_val

        if current < lower or current > upper:
            score = max(lower - current, current - upper, 0.0)
            anomalies.append({"index": i, "value": current, "score": round(score, 4)})

        # Update running bounds for final response
        q1 = q1_val
        q3 = q3_val
        iqr = iqr_val
        lower_bound = q1 - k * iqr
        upper_bound = q3 + k * iqr

    # Apply false positive window: need 3 consecutive anomalies
    filtered = _filter_false_positives(anomalies)

    return {
        "anomalies": filtered,
        "lower_bound": round(lower_bound, 4),
        "upper_bound": round(upper_bound, 4),
        "q1": round(q1, 4),
        "q3": round(q3, 4),
        "iqr": round(iqr, 4),
        "method": "quantile",
    }


def _filter_false_positives(anomalies: list[dict]) -> list[dict]:
    """Filter anomalies: require at least 3 consecutive to be real anomalies."""
    if not anomalies:
        return []

    filtered = []
    run = []

    for a in anomalies:
        if not run:
            run = [a]
        else:
            if a["index"] == run[-1]["index"] + 1:
                run.append(a)
            else:
                if len(run) >= 3:
                    filtered.extend(run)
                run = [a]

    if len(run) >= 3:
        filtered.extend(run)

    return filtered
