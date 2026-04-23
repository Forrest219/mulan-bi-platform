"""Metrics Agent — 血缘解析引擎（T3）

血缘解析流程：
  1. manual_override=True → 直接写入手动血缘，lineage_status="manual"
  2. manual_override=False → 调用 LLM 解析公式血缘，confidence>=0.7 则 lineage_status="resolved"

LLM 返回值说明：
  complete_for_semantic() 返回 { "content": str } 或 { "error": str }
  其中 content 是 JSON 字符串，直接 json.loads() 解析。
"""

import asyncio
import json
import logging
import uuid
from typing import Literal, Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.errors import MulanError
from models.metrics import BiMetricDefinition, BiMetricLineage
from services.llm.service import llm_service

logger = logging.getLogger(__name__)


# =============================================================================
# LLM 输出 Pydantic Schema
# =============================================================================

class LineageFieldItem(BaseModel):
    table_name: str
    column_name: str
    column_type: Optional[str] = None
    relationship_type: Literal["source", "upstream_joined", "upstream_calculated"]
    hop_number: int = 0
    transformation_logic: Optional[str] = None


class LineageExtractionResult(BaseModel):
    source_tables: list[str]
    source_metrics: list[str]
    fields: list[LineageFieldItem]
    confidence: float  # 0.0-1.0
    notes: Optional[str] = None


# =============================================================================
# Prompt 常量
# =============================================================================

LINEAGE_SYSTEM_PROMPT = """你是一个专业的数据血缘分析助手。

你的任务是：分析给定的指标计算公式，提取出该指标直接或间接依赖的所有底层数据库字段和上游指标。

## 输出规则

必须严格返回以下 JSON 结构，不得包含任何额外文字：

{
  "source_tables": ["表名1", "表名2"],
  "source_metrics": ["上游指标名（如有）"],
  "fields": [
    {
      "table_name": "orders",
      "column_name": "order_amount",
      "column_type": "DECIMAL",
      "relationship_type": "source",
      "hop_number": 0,
      "transformation_logic": null
    }
  ],
  "confidence": 0.95,
  "notes": null
}

## 关系类型说明
- source：公式直接引用的字段（如 SUM(orders.amount)）
- upstream_joined：通过 JOIN 关联进来的字段
- upstream_calculated：通过子查询、表达式或上游指标计算得到的值

## 重要约束
- 若公式使用了参数占位符（如 {{status}}），将其视为过滤条件，不作为字段血缘
- 若无法从公式中确定 column_type，填 null，不要猜测
- source_metrics 仅在指标类型为 derived 或 ratio 时填写"""


def _build_lineage_prompt(metric: BiMetricDefinition) -> str:
    return f"""## 指标信息

- 指标名称：{metric.name}（{metric.name_zh or '无'}）
- 指标类型：{metric.metric_type}
- 主表：{metric.table_name}（数据源 ID: {metric.datasource_id}）
- 主字段：{metric.column_name}
- 计算公式：{metric.formula or '无'}
- 公式模板：{metric.formula_template or '无'}
- 过滤条件：{metric.filters or '无'}

请提取该指标的完整字段血缘。"""


# =============================================================================
# 辅助函数
# =============================================================================

def _write_lineage_records(
    db: Session,
    metric_id: uuid.UUID,
    tenant_id: uuid.UUID,
    datasource_id: int,
    fields: list[LineageFieldItem],
) -> int:
    """清空旧血缘并批量写入新血缘，返回写入条数。在事务内调用，不自行 commit。"""
    db.query(BiMetricLineage).filter(
        BiMetricLineage.metric_id == metric_id
    ).delete(synchronize_session=False)

    records = []
    for field in fields:
        record = BiMetricLineage(
            tenant_id=tenant_id,
            metric_id=metric_id,
            datasource_id=datasource_id,
            table_name=field.table_name,
            column_name=field.column_name,
            column_type=field.column_type,
            relationship_type=field.relationship_type,
            hop_number=field.hop_number,
            transformation_logic=field.transformation_logic,
        )
        records.append(record)

    if records:
        db.add_all(records)

    return len(records)


# =============================================================================
# 核心函数
# =============================================================================

async def resolve_lineage(
    db: Session,
    metric_id: uuid.UUID,
    tenant_id: uuid.UUID,
    manual_override: bool = False,
    manual_records: list[dict] | None = None,
) -> dict:
    """
    解析指标血缘。

    - manual_override=True 时跳过 LLM，直接写入 manual_records，lineage_status="manual"
    - manual_override=False 时调用 LLM，confidence < 0.7 则 lineage_status 保持 "unknown"

    返回：{"lineage_count": int, "lineage_status": str}

    Raises:
        MulanError(MC_404, 404): 指标不存在
        MulanError(MC_400, 400): manual_override=True 但 manual_records 为空
        MulanError(MC_500, 500): LLM 响应解析失败
        MulanError(MC_429, 429): LLM 调用超时
    """
    # 1. 取指标，不存在 → 404
    metric = (
        db.query(BiMetricDefinition)
        .filter(
            BiMetricDefinition.id == metric_id,
            BiMetricDefinition.tenant_id == tenant_id,
        )
        .first()
    )
    if metric is None:
        raise MulanError("MC_404", f"指标不存在：id={metric_id}", 404)

    # 2. manual_override 分支
    if manual_override:
        if not manual_records:
            raise MulanError("MC_400", "manual_override=True 时 manual_records 不能为空", 400)

        # 将 manual_records（list[dict]）转为 LineageFieldItem
        fields = []
        for i, rec in enumerate(manual_records):
            try:
                fields.append(LineageFieldItem(**rec))
            except Exception as e:
                raise MulanError(
                    "MC_400",
                    f"manual_records[{i}] 字段格式错误：{e}",
                    400,
                    {"index": i, "error": str(e)},
                )

        # P1-2：写库段加 BaseException 保护，确保任何异常（包括 KeyboardInterrupt）都能回滚
        try:
            lineage_count = _write_lineage_records(
                db, metric_id, tenant_id, metric.datasource_id, fields
            )
            metric.lineage_status = "manual"
            db.commit()
        except BaseException:
            db.rollback()
            raise

        logger.info(
            "血缘手动写入完成：metric_id=%s, count=%d",
            metric_id,
            lineage_count,
        )
        return {"lineage_count": lineage_count, "lineage_status": "manual"}

    # 3. LLM 分支
    prompt = _build_lineage_prompt(metric)

    try:
        result = await asyncio.wait_for(
            llm_service.complete_for_semantic(
                prompt=prompt,
                system=LINEAGE_SYSTEM_PROMPT,
                timeout=30,
                purpose="lineage",
            ),
            timeout=35,  # 比 LLM 内部 timeout 多 5s 作为保险
        )
    except asyncio.TimeoutError:
        logger.warning("血缘解析 LLM 调用超时：metric_id=%s", metric_id)
        raise MulanError("MC_429", "LLM 调用超时，请稍后重试", 429)

    # 检查 LLM 返回错误
    if "error" in result:
        logger.error("LLM 血缘解析调用失败：metric_id=%s, error=%s", metric_id, result["error"])
        raise MulanError(
            "MC_500",
            f"LLM 调用失败：{result['error']}",
            500,
            {"llm_error": result["error"]},
        )

    # 解析 LLM 返回的 JSON 字符串
    content = result["content"]
    try:
        raw_json = json.loads(content)
        extraction = LineageExtractionResult.model_validate(raw_json)
    except (json.JSONDecodeError, ValueError, Exception) as e:
        logger.error(
            "血缘解析 LLM 响应解析失败：metric_id=%s, error=%s, content=%.500s",
            metric_id,
            e,
            content,
        )
        raise MulanError(
            "MC_500",
            f"LLM 响应解析失败：{e}",
            500,
            {"parse_error": str(e), "raw_content": content[:200]},
        )

    # 根据 confidence 决定 lineage_status
    if extraction.confidence >= 0.7:
        lineage_status = "resolved"
    else:
        lineage_status = "unknown"

    # P1-2：写库段加 BaseException 保护，确保任何异常（包括 KeyboardInterrupt）都能回滚
    try:
        lineage_count = _write_lineage_records(
            db, metric_id, tenant_id, metric.datasource_id, extraction.fields
        )
        metric.lineage_status = lineage_status
        db.commit()
    except BaseException:
        db.rollback()
        raise

    logger.info(
        "血缘 LLM 解析完成：metric_id=%s, count=%d, confidence=%.2f, status=%s",
        metric_id,
        lineage_count,
        extraction.confidence,
        lineage_status,
    )
    return {"lineage_count": lineage_count, "lineage_status": lineage_status}
