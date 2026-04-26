"""
图表推荐器 — Chart Recommender (Spec 26 附录 A §2.1)

接收 SQL 查询结果 schema + 用户意图，
通过 LLM 语义推理输出最优图表类型与推荐理由。

输入：
  schema: { columns: [{name, dtype, role}], row_count_estimate, sample_values }
  user_intent: 自然语言意图
  connection_id: Tableau 连接 ID（可选，用于获取语义上下文）

输出：
  recommendations: [{ chart_type, confidence, reason, field_mapping, tableau_mark_type, suggested_title }]
  meta: { columns_analyzed, columns_truncated, llm_provider, latency_ms }
"""

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

from services.llm.service import LLMService

from .prompts import (
    CHART_TYPE_TO_TABLEAU_MARK,
    FALLBACK_CHART_TYPE,
    SCHEMA_BUILDING_HINTS,
    VIZ_RECOMMEND_TEMPLATE,
    VIZ_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


class ChartRecommender:
    """
    图表推荐主逻辑。

    调用 LLM 推理最优图表类型，支持：
    - Schema 过滤（高敏感字段自动移除）
    - 列数截断（最多 50 列）
    - 重试 1 次（JSON 解析失败时）
    - 降级 fallback（无法确定时退回 bar）
    """

    MAX_COLUMNS = 50
    MAX_SAMPLE_VALUES_PER_COLUMN = 5

    def __init__(self, llm_service: Optional[LLMService] = None):
        self._llm = llm_service or LLMService()

    # ── Public API ──────────────────────────────────────────────────────────────

    async def recommend(
        self,
        schema: Dict[str, Any],
        user_intent: str = "",
        connection_id: Optional[int] = None,
        datasource_luid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        图表推荐主入口。

        Args:
            schema: {
                "columns": [{"name": str, "dtype": str, "role": str}],
                "row_count_estimate": str,
                "sample_values": {col_name: [val1, val2]} (optional)
            }
            user_intent: 自然语言意图（可选）
            connection_id: Tableau 连接 ID（可选）
            datasource_luid: Tableau 数据源 LUID（可选）

        Returns:
            {
                "recommendations": [...],
                "meta": { columns_analyzed, columns_truncated, llm_provider, latency_ms }
            }
        """
        start_time = time.time()

        # Step 1: Schema 预处理（过滤 + 截断）
        filtered_schema = self._preprocess_schema(schema)
        columns_analyzed = len(filtered_schema["columns"])

        # Step 2: 构建 LLM prompt
        schema_json = json.dumps(filtered_schema, ensure_ascii=False)
        user_prompt = VIZ_RECOMMEND_TEMPLATE.format(
            schema_json=schema_json,
            user_intent=user_intent or "根据数据特征自动推断合适图表类型",
        )

        # Step 3: 调用 LLM（带重试）
        raw_response = await self._call_llm_with_retry(user_prompt)

        # Step 4: 解析 LLM 响应
        if "error" in raw_response:
            return self._error_response(
                code="VIZ_004",
                message="LLM 服务不可用",
                details=raw_response,
                latency_ms=self._elapsed_ms(start_time),
            )

        content = raw_response.get("content", "")
        recommendations = self._parse_recommendations(content, filtered_schema)

        # Step 5: 补充 meta
        meta = {
            "columns_analyzed": columns_analyzed,
            "columns_truncated": max(0, len(schema.get("columns", [])) - columns_analyzed),
            "llm_provider": self._llm._load_config().provider if hasattr(self._llm, "_load_config") else "unknown",
            "latency_ms": self._elapsed_ms(start_time),
        }

        return {
            "recommendations": recommendations,
            "meta": meta,
        }

    # ── Schema 预处理 ──────────────────────────────────────────────────────────

    def _preprocess_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Schema 预处理：
        1. 高敏感字段过滤（high/confidential）
        2. 列数截断（最多 50 列）
        3. sample_values 每列最多 5 个
        """
        columns = schema.get("columns", [])
        if not columns:
            return schema

        # Step 1: 过滤高敏感字段
        filtered_columns = [
            col for col in columns
            if col.get("sensitivity_level") not in ("high", "confidential")
        ]

        # Step 2: 截断超限列
        truncated = False
        if len(filtered_columns) > self.MAX_COLUMNS:
            filtered_columns = filtered_columns[: self.MAX_COLUMNS]
            truncated = True
            logger.warning(
                "ChartRecommender: schema 列数 %d → 截断至 %d",
                len(columns),
                self.MAX_COLUMNS,
            )

        # Step 3: 限制 sample_values 每列最多 5 个
        sample_values = schema.get("sample_values") or {}
        if sample_values:
            sample_values = {
                k: v[: self.MAX_SAMPLE_VALUES_PER_COLUMN]
                for k, v in sample_values.items()
            }

        return {
            "columns": filtered_columns,
            "row_count_estimate": schema.get("row_count_estimate", ""),
            "sample_values": sample_values,
        }

    # ── LLM 调用 ──────────────────────────────────────────────────────────────

    async def _call_llm_with_retry(self, user_prompt: str, max_retries: int = 1) -> Dict[str, Any]:
        """
        调用 LLM，支持解析失败时重试 1 次。
        """
        attempt = 0
        last_error: Optional[str] = None

        while attempt <= max_retries:
            result = await self._llm.complete(
                prompt=user_prompt,
                system=VIZ_SYSTEM_PROMPT,
                timeout=15,
                purpose="default",
            )

            if "error" not in result:
                # 清理可能包含的 markdown 代码块标记
                content = result.get("content", "").strip()
                if content.startswith("```"):
                    lines = content.split("\n")
                    content = "\n".join(lines[1:] if lines[0].startswith("```") else lines)
                    if content.endswith("```"):
                        content = content[:-3].strip()
                result["content"] = content
                return result

            last_error = result.get("error", str(result))
            attempt += 1
            if attempt <= max_retries:
                logger.warning("ChartRecommender LLM 重试（attempt %d）: %s", attempt, last_error)
                time.sleep(0.5)

        return {"error": last_error or "LLM 调用失败"}

    # ── 响应解析 ──────────────────────────────────────────────────────────────

    def _parse_recommendations(
        self,
        raw_content: str,
        schema: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        解析 LLM JSON 响应，提取 recommendations。
        解析失败时返回 bar 降级推荐。
        """
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError as e:
            logger.warning("ChartRecommender JSON 解析失败: %s，raw: %s", e, raw_content[:200])
            return [self._fallback_recommendation(schema, reason=f"JSON 解析失败，降级为{FALLBACK_CHART_TYPE}")]

        recommendations = parsed.get("recommendations", [])
        if not recommendations:
            return [self._fallback_recommendation(schema, reason="LLM 返回空推荐，降级为 bar")]

        # 验证并补充 tableau_mark_type
        enriched = []
        for rec in recommendations[:3]:  # 最多 3 个
            chart_type = rec.get("chart_type", "")
            if chart_type not in CHART_TYPE_TO_TABLEAU_MARK:
                continue  # 跳过非法 chart_type

            rec["tableau_mark_type"] = rec.get(
                "tableau_mark_type",
                CHART_TYPE_TO_TABLEAU_MARK.get(chart_type, "Bar"),
            )
            rec["confidence"] = float(rec.get("confidence", 0.5))
            rec["rank"] = len(enriched) + 1
            rec["field_mapping"] = rec.get("field_mapping", {})
            rec["suggested_title"] = rec.get("suggested_title", "")
            rec["reason"] = rec.get("reason", "")[:50]  # ≤50 字
            enriched.append(rec)

        return enriched or [self._fallback_recommendation(schema)]

    def _fallback_recommendation(
        self,
        schema: Dict[str, Any],
        reason: str = "无法确定图表类型，降级为最通用的柱状图",
    ) -> Dict[str, Any]:
        """
        降级推荐：当 LLM 解析失败或无有效推荐时使用。
        """
        columns = schema.get("columns", [])
        dimension_cols = [c["name"] for c in columns if c.get("role") == "dimension"]
        measure_cols = [c["name"] for c in columns if c.get("role") == "measure"]

        return {
            "rank": 1,
            "chart_type": FALLBACK_CHART_TYPE,
            "confidence": 0.5,
            "reason": reason,
            "field_mapping": {
                "x": dimension_cols[0] if dimension_cols else (columns[0]["name"] if columns else ""),
                "y": measure_cols[0] if measure_cols else "",
                "color": None,
                "size": None,
                "label": None,
                "detail": None,
            },
            "tableau_mark_type": CHART_TYPE_TO_TABLEAU_MARK[FALLBACK_CHART_TYPE],
            "suggested_title": "推荐图表",
        }

    # ── 工具 ──────────────────────────────────────────────────────────────────

    @staticmethod
    def schema_hash(schema: Dict[str, Any]) -> str:
        """计算 schema 的 SHA-256（不存原始数据，仅用于审计日志）"""
        normalized = json.dumps(schema, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(normalized.encode()).hexdigest()

    @staticmethod
    def _elapsed_ms(start_time: float) -> int:
        return int((time.time() - start_time) * 1000)

    @staticmethod
    def _error_response(
        code: str,
        message: str,
        details: Dict[str, Any],
        latency_ms: int,
    ) -> Dict[str, Any]:
        return {
            "error_code": code,
            "message": message,
            "detail": details,
            "recommendations": [],
            "meta": {"latency_ms": latency_ms},
        }
