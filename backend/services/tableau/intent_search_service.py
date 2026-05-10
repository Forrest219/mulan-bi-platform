"""Tableau 资产意图搜索服务

SPEC 39: 将自然语言查询转化为结构化意图，通过 ILIKE 召回候选资产，
再由 LLM 排序并生成相关性原因。

架构约束：
- 不得 import app.api 层任何内容
- SQL 必须使用 SQLAlchemy text() + 绑定参数
- LLM 调用通过 services.llm.service.llm_service 实例
"""
import json
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.llm.service import llm_service

logger = logging.getLogger(__name__)

_EXTRACT_INTENT_SYSTEM = "你是 BI 助手，擅长从用户查询中提取结构化搜索意图。只输出 JSON，不要解释。"
_EXTRACT_INTENT_PROMPT_TMPL = """从用户查询中提取搜索意图，用 JSON 回答：
{{"keywords": ["关键词1", "关键词2"], "asset_type_hint": "dashboard 或 null", "time_range_hint": "描述 或 null"}}

规则：
- keywords 中提取 2-5 个核心业务关键词
- asset_type_hint 只能是 workbook / dashboard / view / datasource 之一，或 null
- time_range_hint 为时间描述字符串，或 null

用户查询：{query}"""

_RANK_SYSTEM = "你是 BI 助手，负责对候选资产按与用户查询的相关性排序。只输出 JSON 数组，不要解释。"
_RANK_PROMPT_TMPL = """根据用户查询，从候选资产中选出最相关的（最多 8 个），按相关性降序排列，每个给出简洁的中文原因。

时间提示：{time_range_hint}
返回 JSON 数组：[{{"asset_id": "...", "relevance_score": 0-1, "relevance_reason": "..."}}]

用户查询：{query}
候选资产：
{candidates_json}"""


class IntentSearchService:
    """Tableau 资产意图搜索服务（SPEC 39）"""

    def __init__(self, db: Session):
        self.db = db

    async def extract_intent(self, query: str) -> dict:
        """LLM 提取意图：keywords, asset_type_hint, time_range_hint

        失败时 fallback 到 {"keywords": [query], "asset_type_hint": None, "time_range_hint": None}
        """
        prompt = _EXTRACT_INTENT_PROMPT_TMPL.format(query=query)
        try:
            result = await llm_service.complete_for_semantic(
                prompt=prompt,
                system=_EXTRACT_INTENT_SYSTEM,
                timeout=10,
            )
            if "error" in result:
                raise ValueError(result["error"])
            content = result.get("content", "")
            # 从响应中提取 JSON（可能包裹在 markdown 代码块）
            content = content.strip()
            if content.startswith("```"):
                lines = content.splitlines()
                content = "\n".join(
                    line for line in lines
                    if not line.startswith("```")
                )
            parsed = json.loads(content)
            keywords = parsed.get("keywords", [query])
            if not isinstance(keywords, list) or not keywords:
                keywords = [query]
            # 过滤非字符串
            keywords = [str(k) for k in keywords if k]
            asset_type_hint = parsed.get("asset_type_hint")
            if asset_type_hint not in ("workbook", "dashboard", "view", "datasource", None):
                asset_type_hint = None
            return {
                "keywords": keywords,
                "asset_type_hint": asset_type_hint,
                "time_range_hint": parsed.get("time_range_hint"),
            }
        except Exception as exc:
            logger.warning("extract_intent 失败，使用 query 作为 fallback: %s", exc)
            return {
                "keywords": [query],
                "asset_type_hint": None,
                "time_range_hint": None,
            }

    def recall_candidates(
        self,
        connection_id: str,
        keywords: list,
        asset_type_hint: Optional[str],
        health_score_max: Optional[float] = None,
    ) -> list:
        """SQL ILIKE 联合查询 name/project_name/ai_summary/ai_explain

        WHERE ai_summary IS NOT NULL
        AND connection_id = :connection_id
        LIMIT 20
        """
        if not keywords:
            return []

        # 构建 ILIKE 条件：每个关键词在任意字段命中即可
        # 多个关键词之间是 OR；全部条件再和 ai_summary IS NOT NULL AND connection_id = :x 组合
        conditions = []
        params: dict = {"connection_id": connection_id}

        for i, kw in enumerate(keywords[:10]):  # 最多 10 个关键词防过长
            kw_param = f"kw_{i}"
            params[kw_param] = f"%{kw}%"
            conditions.append(
                f"(name ILIKE :{kw_param}"
                f" OR project_name ILIKE :{kw_param}"
                f" OR ai_summary ILIKE :{kw_param}"
                f" OR ai_explain ILIKE :{kw_param})"
            )

        where_keyword = " OR ".join(conditions)
        where_base = (
            "ai_summary IS NOT NULL"
            " AND is_deleted = FALSE"
            " AND connection_id = :connection_id"
        )
        where_full = f"{where_base} AND ({where_keyword})"

        if asset_type_hint:
            where_full += " AND asset_type = :asset_type_hint"
            params["asset_type_hint"] = asset_type_hint

        if health_score_max is not None:
            # 严格小于，不含 unscored（NULL）资产
            where_full += " AND health_score IS NOT NULL AND health_score < :health_score_max"
            params["health_score_max"] = health_score_max

        sql = text(
            f"SELECT id, name, asset_type, project_name, health_score,"  # noqa: S608
            f" ai_summary, ai_explain, view_count"
            f" FROM tableau_assets"
            f" WHERE {where_full}"
            f" LIMIT 20"
        )

        rows = self.db.execute(sql, params).fetchall()
        return [dict(row._mapping) for row in rows]

    async def rank_and_explain(self, query: str, candidates: list) -> list:
        """LLM 排序 + 生成 relevance_reason，返回 top 8

        candidates 为空时直接返回 []，不调用 LLM。
        """
        if not candidates:
            return []

        # 截取每个候选的 ai_summary 前 200 字，避免 prompt 过长
        candidates_summary = [
            {
                "id": str(c["id"]),
                "name": c["name"],
                "asset_type": c.get("asset_type", ""),
                "project_name": c.get("project_name") or "",
                "ai_summary": (c.get("ai_summary") or "")[:200],
            }
            for c in candidates
        ]

        prompt = _RANK_PROMPT_TMPL.format(
            query=query,
            time_range_hint="无",  # SPEC 开放问题 §10: 注入提示词但不执行时间过滤
            candidates_json=json.dumps(candidates_summary, ensure_ascii=False, indent=2),
        )

        try:
            result = await llm_service.complete_for_semantic(
                prompt=prompt,
                system=_RANK_SYSTEM,
                timeout=20,
            )
            if "error" in result:
                raise ValueError(result["error"])
            content = result.get("content", "").strip()
            if content.startswith("```"):
                lines = content.splitlines()
                content = "\n".join(
                    line for line in lines
                    if not line.startswith("```")
                )
            ranked = json.loads(content)
            if not isinstance(ranked, list):
                raise ValueError("LLM 返回非数组")
            # 取 top 8，按 relevance_score 降序
            ranked = sorted(ranked, key=lambda x: float(x.get("relevance_score", 0)), reverse=True)
            return ranked[:8]
        except Exception as exc:
            logger.warning("rank_and_explain 失败，按原始顺序返回前 8: %s", exc)
            # fallback：返回前 8 个候选，relevance_score=0，relevance_reason 为空
            return [
                {
                    "asset_id": str(c["id"]),
                    "relevance_score": 0.5,
                    "relevance_reason": "关键词匹配",
                }
                for c in candidates[:8]
            ]

    async def intent_search(self, query: str, connection_id: str) -> dict:
        """完整流程：extract_intent → recall_candidates → rank_and_explain

        Returns:
            {
                "assets": [...],  # 完整资产字段 + relevance_reason
                "total": int,
                "intent": { "keywords": [...], "asset_type_hint": ..., "time_range_hint": ... }
            }
        """
        # 截断超长 query
        query = query[:200]

        # 1. 提取意图
        intent = await self.extract_intent(query)

        # 2. 召回候选
        candidates = self.recall_candidates(
            connection_id=connection_id,
            keywords=intent["keywords"],
            asset_type_hint=intent.get("asset_type_hint"),
        )

        # 3. 排序 + 原因生成
        ranked = await self.rank_and_explain(query, candidates)

        # 4. 组装响应：合并 ranked 结果与完整资产信息
        candidate_map = {str(c["id"]): c for c in candidates}
        assets_out = []
        for item in ranked:
            asset_id = str(item.get("asset_id", ""))
            cand = candidate_map.get(asset_id)
            if not cand:
                continue
            assets_out.append(
                {
                    "id": cand["id"],
                    "name": cand["name"],
                    "asset_type": cand.get("asset_type"),
                    "project_name": cand.get("project_name"),
                    "health_score": cand.get("health_score"),
                    "ai_summary": cand.get("ai_summary"),
                    "view_count": cand.get("view_count"),
                    "relevance_reason": item.get("relevance_reason", ""),
                    "relevance_score": item.get("relevance_score", 0),
                }
            )

        return {
            "assets": assets_out,
            "total": len(assets_out),
            "intent": intent,
        }

    def recall_and_rank(
        self,
        query: str,
        connection_id: str,
        asset_type: Optional[str] = None,
        health_score_max: Optional[float] = None,
    ) -> list:
        """简化版召回（供 SPEC 41 chat service 直接调用，无 LLM 排序）

        仅执行 recall_candidates + 简单相关性排序（按关键词命中 name 的次数）。
        """
        keywords = query[:200].split()[:10]
        candidates = self.recall_candidates(
            connection_id=connection_id,
            keywords=keywords if keywords else [query],
            asset_type_hint=asset_type,
            health_score_max=health_score_max,
        )

        def _score(c: dict) -> int:
            text_lower = (
                (c.get("name") or "") + " " + (c.get("ai_summary") or "")
            ).lower()
            return sum(1 for kw in keywords if kw.lower() in text_lower)

        return sorted(candidates, key=_score, reverse=True)
