"""Metrics Agent — 异常检测服务编排层

负责：
1. 从数据库查出目标指标列表
2. 通过 SQL 执行器拉取历史每日数值
3. 调用算法层执行异常检测
4. 将异常结果写入 bi_metric_anomalies
5. 状态流转管理
"""

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.errors import MulanError
from models.metrics import BiMetricAnomaly, BiMetricDefinition
from .anomaly_detector import (
    AnomalyResult,
    detect_quantile,
    detect_trend_deviation,
    detect_zscore,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 标识符白名单校验（P0-1）
# ---------------------------------------------------------------------------

_IDENTIFIER_RE = re.compile(r'^[a-zA-Z0-9_\.]+$')


def _validate_identifier(value: str, field_name: str) -> None:
    """校验 SQL 标识符（表名/列名），只允许字母、数字、下划线和点。"""
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(f"非法标识符 {field_name}={value!r}，只允许字母、数字、下划线和点")


# ---------------------------------------------------------------------------
# 合法状态流转表
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "detected": {"investigating", "false_positive"},
    "investigating": {"resolved", "false_positive"},
}


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_datasource_config(db: Session, datasource_id: int) -> tuple[str, dict]:
    """
    从 bi_data_sources 读取数据源，解密密码，返回 (db_type, config_dict)。
    config_dict 格式：{"host", "port", "username", "password", "database"}
    """
    from services.datasources.models import DataSource
    from app.core.crypto import get_datasource_crypto

    ds = db.query(DataSource).filter(DataSource.id == datasource_id).first()
    if ds is None:
        raise MulanError("DS_004", f"数据源不存在：id={datasource_id}", 400)

    crypto = get_datasource_crypto()
    try:
        password = crypto.decrypt(ds.password_encrypted)
    except Exception as e:
        logger.warning("数据源密码解密失败：datasource_id=%s, error=%s", datasource_id, e)
        password = ""

    config = {
        "host": ds.host,
        "port": ds.port,
        "username": ds.username,
        "password": password,
        "database": ds.database_name,
    }
    return ds.db_type, config


def _build_daily_sql(metric: BiMetricDefinition, window_days: int) -> str:
    """
    构造按天聚合的 SQL。

    格式：
      SELECT DATE(created_at) as dt, {formula} as val
      FROM {table_name}
      WHERE created_at >= NOW() - INTERVAL '{window_days} days'
      [AND filter_key = 'filter_value' ...]
      GROUP BY DATE(created_at)
      ORDER BY dt ASC

    说明：
    - formula 是 SUM(order_amount) 这样的聚合表达式，直接嵌入 SELECT
    - filters 仅支持简单 key=value（字符串值），不做复杂解析
    """
    # P0-1：标识符白名单校验，拒绝含注入字符的 table_name / column_name
    _validate_identifier(metric.table_name, "table_name")
    _validate_identifier(metric.column_name, "column_name")

    formula = metric.formula or f"COUNT({metric.column_name})"
    table_name = metric.table_name

    where_clauses = [f"created_at >= NOW() - INTERVAL '{window_days} days'"]

    if metric.filters and isinstance(metric.filters, dict):
        for key, value in metric.filters.items():
            # 仅支持简单的字符串/数字过滤，跳过复杂结构
            if isinstance(value, (str, int, float, bool)) and isinstance(key, str):
                # 防止 SQL 注入：key 只允许字母数字下划线
                if key.replace("_", "").isalnum():
                    if isinstance(value, str):
                        safe_val = value.replace("'", "''")
                        where_clauses.append(f"{key} = '{safe_val}'")
                    elif isinstance(value, bool):
                        where_clauses.append(f"{key} = {'TRUE' if value else 'FALSE'}")
                    else:
                        where_clauses.append(f"{key} = {value}")

    where_sql = " AND ".join(where_clauses)

    sql = (
        f"SELECT DATE(created_at) as dt, {formula} as val "
        f"FROM {table_name} "
        f"WHERE {where_sql} "
        f"GROUP BY DATE(created_at) "
        f"ORDER BY dt ASC"
    )

    # P0-1：对完整 SQL 做安全校验（拦截 DDL / 写操作 / 敏感表访问）
    # db_type 在此处无法感知，使用宽松方言 mysql（异常检测不做方言精确限制）
    from services.sql_agent.security import SQLSecurityValidator
    _vr = SQLSecurityValidator("mysql").validate(sql)
    if not _vr.ok:
        raise ValueError(
            f"异常检测 SQL 安全校验失败（{_vr.error_code}）：{_vr.reason}"
        )

    return sql


def _fetch_daily_values(
    db: Session,
    metric: BiMetricDefinition,
    window_days: int,
) -> list[float]:
    """
    执行聚合查询，返回按日期升序的每日数值列表（float）。
    执行失败时记录日志并返回空列表。
    """
    from services.sql_agent.executor import get_executor

    try:
        db_type, config = _get_datasource_config(db, metric.datasource_id)
    except MulanError as e:
        logger.warning(
            "获取数据源配置失败：metric_id=%s, datasource_id=%s, error=%s",
            metric.id,
            metric.datasource_id,
            e.message,
        )
        return []

    sql = _build_daily_sql(metric, window_days)
    logger.debug("异常检测 SQL：metric_id=%s, sql=%s", metric.id, sql)

    try:
        executor = get_executor(db_type, config, timeout_seconds=30)
        rows, _columns = executor.execute(sql)
    except Exception as e:
        logger.warning(
            "异常检测查询执行失败：metric_id=%s, error=%s",
            metric.id,
            str(e),
        )
        return []

    values = []
    for row in rows:
        val = row.get("val")
        if val is not None:
            try:
                values.append(float(val))
            except (TypeError, ValueError):
                pass

    return values


def _call_detection_algorithm(
    values: list[float],
    detection_method: str,
    threshold: float,
) -> AnomalyResult:
    """根据 detection_method 调用对应算法。"""
    if detection_method == "zscore":
        return detect_zscore(values, threshold=threshold)
    elif detection_method == "quantile":
        return detect_quantile(values)
    elif detection_method == "trend_deviation":
        return detect_trend_deviation(values, threshold_pct=threshold)
    elif detection_method == "threshold_breach":
        # 阈值突破：当前值超过 threshold 视为异常
        current = values[-1] if values else 0.0
        is_anomaly = current > threshold
        return AnomalyResult(
            is_anomaly=is_anomaly,
            metric_value=current,
            expected_value=threshold,
            deviation_score=max(current - threshold, 0.0),
            deviation_threshold=threshold,
        )
    else:
        raise MulanError(
            "MC_400",
            f"不支持的检测方法：{detection_method}，"
            "有效值：zscore / quantile / trend_deviation / threshold_breach",
            400,
        )


# ---------------------------------------------------------------------------
# 核心业务函数
# ---------------------------------------------------------------------------

async def run_anomaly_detection(
    db: Session,
    tenant_id: uuid.UUID,
    metric_ids: Optional[List[uuid.UUID]],
    detection_method: str,
    window_days: int = 30,
    threshold: float = 3.0,
) -> dict:
    """
    对指定指标批量执行异常检测。

    Args:
        db: SQLAlchemy Session
        tenant_id: 当前租户 ID
        metric_ids: 要检测的指标 ID 列表；None 表示全 tenant 活跃指标
        detection_method: zscore | quantile | trend_deviation | threshold_breach
        window_days: 历史窗口天数
        threshold: 算法阈值（zscore 的 z 值 / threshold_breach 的绝对值 / trend_deviation 的百分比）

    Returns:
        {"checked_count": int, "anomaly_count": int, "anomaly_ids": list[str]}
    """
    # 验证 detection_method 合法性（提前失败）
    valid_methods = {"zscore", "quantile", "trend_deviation", "threshold_breach"}
    if detection_method not in valid_methods:
        raise MulanError(
            "MC_400",
            f"不支持的检测方法：{detection_method}，有效值：{', '.join(sorted(valid_methods))}",
            400,
        )

    # 查出目标指标列表（is_active=True）
    q = db.query(BiMetricDefinition).filter(
        BiMetricDefinition.tenant_id == tenant_id,
        BiMetricDefinition.is_active == True,  # noqa: E712
    )
    if metric_ids:
        q = q.filter(BiMetricDefinition.id.in_(metric_ids))

    metrics = q.all()

    checked_count = 0
    anomaly_count = 0
    anomaly_ids: list[str] = []
    _pending_anomaly_events: list[dict] = []

    for metric in metrics:
        checked_count += 1

        # 拉取历史数值
        values = _fetch_daily_values(db, metric, window_days)

        if len(values) < 3:
            logger.debug(
                "指标数据点不足，跳过检测：metric_id=%s, points=%d",
                metric.id,
                len(values),
            )
            continue

        # 执行算法
        try:
            result = _call_detection_algorithm(values, detection_method, threshold)
        except MulanError:
            raise
        except Exception as e:
            logger.warning("算法执行异常：metric_id=%s, error=%s", metric.id, str(e))
            continue

        if not result.is_anomaly:
            continue

        # 写入异常记录
        anomaly = BiMetricAnomaly(
            tenant_id=tenant_id,
            metric_id=metric.id,
            datasource_id=metric.datasource_id,
            detection_method=detection_method,
            metric_value=result.metric_value,
            expected_value=result.expected_value,
            deviation_score=result.deviation_score,
            deviation_threshold=result.deviation_threshold,
            detected_at=_now(),
            status="detected",
        )
        db.add(anomaly)
        db.flush()  # 让 anomaly.id 生成

        anomaly_count += 1
        anomaly_ids.append(str(anomaly.id))

        logger.info(
            "检测到异常：metric_id=%s, method=%s, value=%.4f, expected=%.4f, score=%.4f",
            metric.id,
            detection_method,
            result.metric_value,
            result.expected_value,
            result.deviation_score,
        )

        # 暂存待发射的事件数据（flush 后 id 已生成，但 commit 在循环外）
        _pending_anomaly_events.append({
            "anomaly_id": anomaly.id,
            "metric_id": metric.id,
            "metric_name": metric.name,
            "detection_method": detection_method,
            "deviation_score": result.deviation_score,
            "tenant_id": tenant_id,
        })

    # P1-3：批量 commit 失败保护，commit 失败时回滚并抛 500，不返回已失效的 anomaly_ids
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise MulanError(
            "MC_500",
            "异常记录写入失败，请重试",
            500,
            {"error_code": "INTERNAL", "message": "异常记录写入失败，请重试"},
        )

    # commit 成功后批量发射事件（失败不阻断）
    from services.metrics_agent.events import emit_anomaly_detected as _emit_anomaly
    for _evt in _pending_anomaly_events:
        try:
            _emit_anomaly(
                db=db,
                anomaly_id=_evt["anomaly_id"],
                metric_id=_evt["metric_id"],
                metric_name=_evt["metric_name"],
                detection_method=_evt["detection_method"],
                deviation_score=_evt["deviation_score"],
                tenant_id=_evt["tenant_id"],
            )
        except Exception as _exc:
            logger.warning(
                "emit_anomaly_detected 失败（已忽略）：anomaly_id=%s, error=%s",
                _evt["anomaly_id"],
                _exc,
            )

    return {
        "checked_count": checked_count,
        "anomaly_count": anomaly_count,
        "anomaly_ids": anomaly_ids,
    }


def update_anomaly_status(
    db: Session,
    anomaly_id: uuid.UUID,
    tenant_id: uuid.UUID,
    new_status: str,
    resolved_by: Optional[int] = None,
    resolution_note: Optional[str] = None,
) -> BiMetricAnomaly:
    """
    更新异常记录状态，执行状态机校验。

    合法流转：
      detected → investigating
      detected → false_positive
      investigating → resolved
      investigating → false_positive

    Args:
        db: SQLAlchemy Session
        anomaly_id: 异常记录 UUID
        tenant_id: 当前租户 ID（用于隔离校验）
        new_status: 目标状态
        resolved_by: 处理人 user_id（resolved 时建议填写）
        resolution_note: 处理备注

    Raises:
        MulanError(MC_404, 404): 异常记录不存在
        MulanError(MC_400, 400): 非法状态流转
    """
    anomaly = (
        db.query(BiMetricAnomaly)
        .filter(
            BiMetricAnomaly.id == anomaly_id,
            BiMetricAnomaly.tenant_id == tenant_id,
        )
        .first()
    )
    if anomaly is None:
        raise MulanError("MC_404", f"异常记录不存在：id={anomaly_id}", 404)

    current_status = anomaly.status
    allowed_targets = _VALID_TRANSITIONS.get(current_status, set())

    if new_status not in allowed_targets:
        raise MulanError(
            "MC_400",
            f"非法状态流转：{current_status} → {new_status}，"
            f"当前状态允许流转至：{sorted(allowed_targets) or '（无）'}",
            400,
            {
                "current_status": current_status,
                "requested_status": new_status,
                "allowed_transitions": sorted(allowed_targets),
            },
        )

    anomaly.status = new_status

    if new_status == "resolved":
        anomaly.resolved_by = resolved_by
        anomaly.resolved_at = _now()
        anomaly.resolution_note = resolution_note
    elif resolution_note is not None:
        # false_positive / investigating 也可以记录备注
        anomaly.resolution_note = resolution_note

    db.commit()
    db.refresh(anomaly)
    return anomaly
