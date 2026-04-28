"""DQC LLM 根因分析器（Layer 3）

职责：
- P0/P1 事件触发 LLM 分析（root_cause + fix_suggestion + fix_sql）
- 写入 bi_dqc_llm_analyses 表
- 支持手动触发分析
"""
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from .constants import ALL_DIMENSIONS, LlmTrigger, SignalLevel
from .database import DqcDatabase
from .models import DqcAssetSnapshot, DqcLlmAnalysis, DqcMonitoredAsset, DqcQualityRule, DqcRuleResult

logger = logging.getLogger(__name__)

DQC_LLM_ANALYSIS_PROMPT = """你是一个数据质量专家。请分析以下数据质量问题并给出修复建议。

## 资产信息
- 数据源: {datasource_id}
- Schema: {schema_name}
- 表名: {table_name}
- 显示名称: {display_name}

## 质量评分
- 综合评分: {confidence_score}
- 信号灯: {signal}
- 各维度评分: {dimension_scores}

## 失败的维度
{failing_dimensions_detail}

## 最近检测结果
{recent_results_detail}

## 任务
1. 分析根因（root_cause）：为什么这个表的数据质量会下降？给出2-3条可能的根本原因。
2. 修复建议（fix_suggestion）：针对每条根因，给出具体的修复步骤。
3. 修复 SQL（fix_sql）：如果适用，给出可用于修复问题的 SQL 语句（仅 SELECT 查询，不要包含修改数据的 SQL）。

请用 JSON 格式返回：
{{
  "root_cause": ["原因1", "原因2", "原因3"],
  "fix_suggestion": ["建议1", "建议2", "建议3"],
  "fix_sql": ["SQL1", "SQL2"],
  "confidence": "high/medium/low"
}}

只返回 JSON，不要有其他文字。
"""


@dataclass
class LlmAnalysisResult:
    """LLM 分析结果"""
    root_cause: List[str]
    fix_suggestion: List[str]
    fix_sql: List[str]
    confidence: str
    raw_response: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    latency_ms: Optional[int] = None


class DqcLlmAnalyzer:
    """DQC LLM 根因分析器"""

    def __init__(self, dao: Optional[DqcDatabase] = None):
        self.dao = dao or DqcDatabase()

    def analyze_asset(
        self,
        db: Session,
        asset_id: int,
        cycle_id: UUID,
        trigger: str,
        actor_id: Optional[int] = None,
    ) -> Optional[DqcLlmAnalysis]:
        """执行 LLM 分析并写入数据库"""
        asset = self.dao.get_asset(db, asset_id)
        if not asset:
            logger.warning("llm_analyzer: asset %s not found", asset_id)
            return None

        snapshot = self.dao.get_latest_snapshot(db, asset_id)
        if not snapshot:
            logger.warning("llm_analyzer: no snapshot for asset %s", asset_id)
            return None

        # 判断是否需要分析
        if snapshot.signal not in (SignalLevel.P0.value, SignalLevel.P1.value):
            logger.info("llm_analyzer: asset %s signal is %s, skip analysis", asset_id, snapshot.signal)
            return None

        # 构建失败维度详情
        failing_dims = self._get_failing_dimensions(snapshot)
        if not failing_dims:
            logger.info("llm_analyzer: no failing dimensions for asset %s", asset_id)
            return None

        # 获取最近检测结果
        recent_results = self._get_recent_failed_results(db, cycle_id, asset_id)

        # 构建分析提示
        prompt = self._build_prompt(asset, snapshot, failing_dims, recent_results)

        # 调用 LLM
        start_time = time.time()
        llm_result = self._call_llm(prompt)
        latency_ms = int((time.time() - start_time) * 1000)

        # 解析结果
        root_cause = llm_result.root_cause or []
        fix_suggestion = llm_result.fix_suggestion or []
        fix_sql = llm_result.fix_sql or []

        # 构建 suggested_rules（从 fix_sql 推断）
        suggested_rules = self._build_suggested_rules(asset, fix_sql)

        # 写入数据库
        analysis = self.dao.insert_llm_analysis(
            db,
            cycle_id=cycle_id,
            asset_id=asset_id,
            trigger=trigger,
            signal=snapshot.signal,
            prompt_tokens=llm_result.prompt_tokens,
            completion_tokens=llm_result.completion_tokens,
            latency_ms=latency_ms,
            root_cause="\n".join(root_cause),
            fix_suggestion="\n".join(fix_suggestion),
            fix_sql="\n".join(fix_sql),
            confidence=llm_result.confidence,
            suggested_rules=suggested_rules,
            raw_response=llm_result.raw_response,
            status="success" if llm_result.root_cause else "failed",
        )
        db.commit()
        return analysis

    def _get_failing_dimensions(self, snapshot: DqcAssetSnapshot) -> List[str]:
        """获取失败的维度列表"""
        if not snapshot.dimension_signals:
            return []
        return [
            dim
            for dim, sig in snapshot.dimension_signals.items()
            if sig in (SignalLevel.P0.value, SignalLevel.P1.value)
        ]

    def _get_recent_failed_results(
        self, db: Session, cycle_id: UUID, asset_id: int, limit: int = 10
    ) -> List[DqcRuleResult]:
        """获取最近失败的检测结果"""
        return self.dao.get_failed_results_for_asset(db, cycle_id, asset_id, limit=limit)

    def _build_prompt(
        self,
        asset: DqcMonitoredAsset,
        snapshot: DqcAssetSnapshot,
        failing_dims: List[str],
        recent_results: List[DqcRuleResult],
    ) -> str:
        """构建 LLM 分析提示词"""
        # 失败维度详情
        dim_scores = snapshot.dimension_scores or {}
        dim_signals = snapshot.dimension_signals or {}
        failing_dims_detail = []
        for dim in failing_dims:
            score = dim_scores.get(dim, "N/A")
            signal = dim_signals.get(dim, "N/A")
            failing_dims_detail.append(f"- {dim}: 评分={score}, 信号={signal}")

        # 最近检测结果详情
        results_detail = []
        for r in recent_results[:5]:
            results_detail.append(
                f"- 规则: {r.rule_type}, 维度: {r.dimension}, "
                f"通过: {r.passed}, 实际值: {r.actual_value}, "
                f"错误: {r.error_message or '无'}"
            )

        return DQC_LLM_ANALYSIS_PROMPT.format(
            datasource_id=asset.datasource_id,
            schema_name=asset.schema_name,
            table_name=asset.table_name,
            display_name=asset.display_name or "",
            confidence_score=snapshot.confidence_score,
            signal=snapshot.signal,
            dimension_scores=json.dumps(dim_scores, ensure_ascii=False),
            failing_dimensions_detail="\n".join(failing_dims_detail) or "无",
            recent_results_detail="\n".join(results_detail) or "无",
        )

    def _call_llm(self, prompt: str) -> LlmAnalysisResult:
        """调用 LLM 服务"""
        import asyncio
        from services.llm.service import LLMService

        async def _async_call():
            service = LLMService()
            system = "你是一个数据质量专家，专注于分析数据质量问题并提供修复建议。"
            result = await service.complete_for_semantic(
                prompt=prompt,
                system=system,
                timeout=30,
                purpose="default",
            )
            return result

        from services.common.async_compat import run_async_safely

        result = run_async_safely(_async_call())

        if "error" in result:
            logger.warning("llm call failed: %s", result["error"])
            return LlmAnalysisResult(
                root_cause=[],
                fix_suggestion=[],
                fix_sql=[],
                confidence="low",
                raw_response=result.get("error", "unknown error"),
            )

        content = result.get("content", "")
        return self._parse_llm_response(content)

    def _parse_llm_response(self, content: str) -> LlmAnalysisResult:
        """解析 LLM 响应"""
        import re

        # 尝试提取 JSON
        json_match = re.search(r"\{[\s\S]*\}", content)
        if not json_match:
            return LlmAnalysisResult(
                root_cause=[],
                fix_suggestion=[],
                fix_sql=[],
                confidence="low",
                raw_response=content,
            )

        try:
            data = json.loads(json_match.group())
            return LlmAnalysisResult(
                root_cause=data.get("root_cause", []),
                fix_suggestion=data.get("fix_suggestion", []),
                fix_sql=data.get("fix_sql", []),
                confidence=data.get("confidence", "medium"),
                raw_response=content,
            )
        except json.JSONDecodeError:
            return LlmAnalysisResult(
                root_cause=[],
                fix_suggestion=[],
                fix_sql=[],
                confidence="low",
                raw_response=content,
            )

    def _build_suggested_rules(
        self, asset: DqcMonitoredAsset, fix_sql: List[str]
    ) -> List[Dict[str, Any]]:
        """从 fix_sql 推断建议规则"""
        suggested = []
        for sql in fix_sql:
            if not sql.strip().upper().startswith("SELECT"):
                continue
            # 简单的规则推断逻辑
            sql_upper = sql.upper()
            if "COUNT" in sql_upper:
                suggested.append({
                    "rule_type": "row_count",
                    "suggestion": "建议添加行数监控规则",
                    "sql_hint": sql[:200],
                })
            elif "NULL" in sql_upper or "IS NULL" in sql_upper:
                suggested.append({
                    "rule_type": "null_rate",
                    "suggestion": "建议添加空值率监控规则",
                    "sql_hint": sql[:200],
                })
        return suggested


def trigger_llm_analysis_for_asset(
    db: Session,
    asset_id: int,
    cycle_id: UUID,
    trigger: str,
    actor_id: Optional[int] = None,
) -> Optional[DqcLlmAnalysis]:
    """触发 LLM 分析的便捷函数"""
    analyzer = DqcLlmAnalyzer()
    return analyzer.analyze_asset(db, asset_id, cycle_id, trigger, actor_id)