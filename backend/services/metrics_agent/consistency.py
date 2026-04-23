"""Metrics Agent — 一致性校验引擎

对同一指标在两个数据源上执行聚合查询，比对结果，
写入 bi_metric_consistency_checks，并在校验失败时发射事件。
"""

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.errors import MulanError
from models.metrics import BiMetricConsistencyCheck, BiMetricDefinition
from services.metrics_agent.events import emit_consistency_failed

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
# 内部辅助
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _build_scalar_sql(metric: BiMetricDefinition) -> str:
    """构造全量聚合 SQL（不按天分组，直接取全量聚合值）。

    格式：
      SELECT {formula} AS val FROM {table_name} [WHERE ...]
    """
    # P0-1：标识符白名单校验，拒绝含注入字符的 table_name / column_name
    _validate_identifier(metric.table_name, "table_name")
    _validate_identifier(metric.column_name, "column_name")

    formula = metric.formula or f"COUNT({metric.column_name})"
    table_name = metric.table_name

    where_clauses: list[str] = []
    if metric.filters and isinstance(metric.filters, dict):
        for key, value in metric.filters.items():
            if isinstance(value, (str, int, float, bool)) and isinstance(key, str):
                if key.replace("_", "").isalnum():
                    if isinstance(value, str):
                        safe_val = value.replace("'", "''")
                        where_clauses.append(f"{key} = '{safe_val}'")
                    elif isinstance(value, bool):
                        where_clauses.append(f"{key} = {'TRUE' if value else 'FALSE'}")
                    else:
                        where_clauses.append(f"{key} = {value}")

    if where_clauses:
        where_sql = " WHERE " + " AND ".join(where_clauses)
    else:
        where_sql = ""

    sql = f"SELECT {formula} AS val FROM {table_name}{where_sql}"

    # P0-1：对完整 SQL 做安全校验（拦截 DDL / 写操作 / 敏感表访问）
    from services.sql_agent.security import SQLSecurityValidator
    _vr = SQLSecurityValidator("mysql").validate(sql)
    if not _vr.ok:
        raise ValueError(
            f"一致性校验 SQL 安全校验失败（{_vr.error_code}）：{_vr.reason}"
        )

    return sql


async def _fetch_metric_value(
    datasource_id: int,
    sql: str,
    db: Session,
    timeout: int = 30,
) -> Optional[float]:
    """从指定数据源执行 SQL，返回第一行第一列的 float 值。

    超时抛 asyncio.TimeoutError；查询失败抛原始异常。
    """
    from services.metrics_agent.anomaly_service import _get_datasource_config  # 复用 T4 数据源解密路径
    from services.sql_agent.executor import get_executor

    db_type, config = _get_datasource_config(db, datasource_id)

    def _sync_execute():
        executor = get_executor(db_type, config, timeout_seconds=timeout)
        rows, _columns = executor.execute(sql)
        return rows

    # P1-7：使用 get_running_loop() 替代已废弃的 get_event_loop()
    loop = asyncio.get_running_loop()
    rows = await asyncio.wait_for(
        loop.run_in_executor(None, _sync_execute),
        timeout=timeout,
    )

    if not rows:
        return None

    first_row = rows[0]
    # rows 可能是 list[dict] 或 list[tuple/list]
    if isinstance(first_row, dict):
        val = first_row.get("val") or next(iter(first_row.values()), None)
    elif isinstance(first_row, (list, tuple)):
        val = first_row[0] if first_row else None
    else:
        val = first_row

    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 核心业务函数
# ---------------------------------------------------------------------------

async def run_consistency_check(
    db: Session,
    metric_id: uuid.UUID,
    tenant_id: uuid.UUID,
    datasource_id_a: int,
    datasource_id_b: int,
    tolerance_pct: float = 5.0,
) -> dict:
    """对两个数据源执行同一指标的聚合查询，比对结果，写入 bi_metric_consistency_checks。

    Args:
        db: SQLAlchemy Session
        metric_id: 目标指标 UUID
        tenant_id: 当前租户 ID（用于隔离）
        datasource_id_a: 数据源 A ID
        datasource_id_b: 数据源 B ID
        tolerance_pct: 允许差异百分比（默认 5.0%）

    Returns:
        完整的 check 记录字段 dict

    Raises:
        MulanError(MC_404, 404): 指标不存在
        MulanError(MC_429, 429): 查询超时
        MulanError(DS_004, 400): 数据源不存在
    """
    from services.metrics_agent.registry import get_metric

    # 1. 取指标（含 404 校验）
    metric = get_metric(db, metric_id=metric_id, tenant_id=tenant_id)

    # 2. 构造 SQL
    sql = _build_scalar_sql(metric)
    logger.debug("一致性校验 SQL：metric_id=%s, sql=%s", metric_id, sql)

    # 3. 并发查询两个数据源
    try:
        value_a, value_b = await asyncio.gather(
            _fetch_metric_value(datasource_id_a, sql, db),
            _fetch_metric_value(datasource_id_b, sql, db),
        )
    except asyncio.TimeoutError:
        raise MulanError(
            "MC_429",
            "一致性校验查询超时（30s），请稍后重试",
            429,
        )
    except MulanError:
        raise
    except Exception as exc:
        logger.warning("一致性校验查询执行失败：metric_id=%s, error=%s", metric_id, exc)
        raise MulanError(
            "MC_500",
            f"一致性校验查询执行失败：{exc}",
            500,
        )

    # 4. 计算差值
    difference: Optional[float] = None
    difference_pct: Optional[float] = None

    if value_a is not None and value_b is not None:
        difference = value_a - value_b
        if value_b != 0:
            difference_pct = (difference / value_b) * 100
        else:
            # 除零保护：value_b=0 时 difference_pct 设为 None（无法计算百分比）
            difference_pct = None

    # 5. 判定状态
    abs_pct = abs(difference_pct) if difference_pct is not None else 0.0
    if difference_pct is None and difference is not None and difference != 0:
        # value_b=0 但 value_a != 0 视为 fail
        check_status = "fail"
    elif abs_pct <= tolerance_pct:
        check_status = "pass"
    elif abs_pct <= tolerance_pct * 2:
        check_status = "warning"
    else:
        check_status = "fail"

    # value_a 和 value_b 均为 None 也视为 pass（无数据）
    if value_a is None and value_b is None:
        check_status = "pass"

    # 6. 写入一致性记录
    check = BiMetricConsistencyCheck(
        tenant_id=tenant_id,
        metric_id=metric_id,
        metric_name=metric.name,
        datasource_id_a=datasource_id_a,
        datasource_id_b=datasource_id_b,
        value_a=value_a,
        value_b=value_b,
        difference=difference,
        difference_pct=difference_pct,
        tolerance_pct=tolerance_pct,
        check_status=check_status,
        checked_at=_now(),
    )
    db.add(check)
    db.commit()
    db.refresh(check)

    logger.info(
        "一致性校验完成：metric_id=%s, status=%s, value_a=%s, value_b=%s, diff_pct=%s",
        metric_id,
        check_status,
        value_a,
        value_b,
        difference_pct,
    )

    # 7. 失败时发射事件（P1-4：异常隔离，不阻断主流程）
    if check_status == "fail":
        try:
            emit_consistency_failed(
                db=db,
                check_id=check.id,
                metric_id=metric_id,
                metric_name=metric.name,
                difference_pct=difference_pct,
                tenant_id=tenant_id,
            )
        except Exception:
            logger.warning("emit_consistency_failed 失败，事件发射异常不阻断主流程", exc_info=True)

    # 8. 返回完整记录
    return {
        "id": str(check.id),
        "tenant_id": str(check.tenant_id),
        "metric_id": str(check.metric_id),
        "metric_name": check.metric_name,
        "datasource_id_a": check.datasource_id_a,
        "datasource_id_b": check.datasource_id_b,
        "value_a": check.value_a,
        "value_b": check.value_b,
        "difference": check.difference,
        "difference_pct": check.difference_pct,
        "tolerance_pct": check.tolerance_pct,
        "check_status": check.check_status,
        "checked_at": check.checked_at.isoformat() if check.checked_at else None,
        "created_at": check.created_at.isoformat() if check.created_at else None,
    }
