"""RAG 服务（知识库 §6）"""
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from .embedding_service import embedding_service
from .models import KbGlossaryDatabase, KbEmbeddingDatabase

logger = logging.getLogger(__name__)

# === Token 预算常量（Spec 17 §6.2）===
SYSTEM_PROMPT_TOKENS = 200      # System Prompt 固定开销
USER_INSTRUCTION_TOKENS = 800   # 用户指令固定开销
MIN_CONTEXT_TOKENS = 200        # RAG 可用上下文最低保障
RAG_BUDGET_TOKENS = 3000        # 总 Token 预算上限
# 估算值：数据源字段元数据（表结构、字段描述、计算公式）的典型 Token 数
# v1 阶段硬编码估算；未来应从 datasource 上下文注入精确值
DEFAULT_FIELD_METADATA_TOKENS = 400

# === 敏感度级别常量（PRD §9）===
SENSITIVITY_BLOCKLIST = {"high", "confidential"}


class RAGService:
    """RAG 上下文增强服务 — P0~P4 优先级 + 动态 Token 预算分配"""

    def __init__(self):
        self._glossary_db = KbGlossaryDatabase()
        self._embedding_db = KbEmbeddingDatabase()

    def _calc_rag_budget(self, data_context_tokens: int) -> int:
        """
        动态 RAG Token 预算公式（PRD §6.2）：
        RAG可用预算 = 3000 - SystemPrompt(200) - 数据上下文实际占用 - 用户指令(800)
        最低保障 200 tokens。
        """
        budget = RAG_BUDGET_TOKENS - SYSTEM_PROMPT_TOKENS - data_context_tokens - USER_INSTRUCTION_TOKENS
        return max(budget, MIN_CONTEXT_TOKENS)

    def _token_estimate(self, text: str) -> int:
        """
        估算文本 token 数（Spec 17 §4.4 — 强制 tiktoken cl100k_base）。
        严禁使用字符数估算。P0-P4 各优先级均使用此方法。
        """
        if not text:
            return 0
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            # tiktoken 不可用时的保守回退（中文字符 * 2.0，英文 * 1.3）
            chinese_chars = sum(1 for c in text if ord(c) > 127)
            other_chars = len(text) - chinese_chars
            return int(chinese_chars * 2.0 + other_chars * 1.3)

    async def enrich_context(
        self, db: Session, question: str, scenario: str = "default"
    ) -> Dict[str, Any]:
        """
        RAG 上下文增强主入口（PRD §6.1 + §6.2 + §9）。

        流程：
        1. P0 术语精确匹配（Glossary.match_terms）
        2. 向量相似度检索（EmbeddingService.search）
        3. 按 P0~P4 优先级分组，动态分配 Token 预算
        4. 按 [术语] / [知识] / [模型] 结构化标签组装上下文
        5. 过滤 HIGH/CONFIDENTIAL 敏感度 schema（PRD §9）

        返回：
        {
            "context": str,           # 结构化上下文文本
            "priority_breakdown": {
                "p0": [...],          # P0 术语精确匹配
                "p1": [...],          # P1 glossary 向量
                "p2": [...],          # P2 document 向量
                "p3": [...],          # P3 schema 向量
                "p4": [...],          # P4 field_semantic 向量
            },
            "token_breakdown": {...}
        }
        """
        # Step 1: P0 术语精确匹配
        matched_terms = self._glossary_db.match_by_term(db, question)

        # Step 2: 向量相似度检索（不限制 source_type，一次拉取所有）
        try:
            query_embedding = await embedding_service.embed_text(question)
            # 扩大 top_k 以确保各优先级都有候选
            vector_results = self._embedding_db.search_by_vector(
                db, query_embedding, top_k=20, threshold=0.5
            )
        except Exception as e:
            logger.warning("向量检索失败: %s", e)
            vector_results = []

        # Step 3: 敏感度过滤 — 排除 HIGH/CONFIDENTIAL schema（PRD §9）
        vector_results = await self._filter_sensitivity(db, vector_results)

        # Step 4: 按 P0~P4 优先级分组
        priority_groups = self._group_by_priority(vector_results)

        # Step 5: 计算各优先级 token 占用
        priority_tokens = self._calc_priority_tokens(priority_groups, matched_terms)

        # Step 6: 动态预算分配（P0 不占 RAG 预算，RAG 预算 = P1~P4）
        # data_context_tokens = 字段元数据 Token 估算（表结构、字段描述等）
        # P0 为精确匹配，不消耗 RAG 预算（Spec 17 §6.3）
        rag_budget = self._calc_rag_budget(DEFAULT_FIELD_METADATA_TOKENS)

        # Step 7: 按优先级顺序截断（P0 固定保留，剩余预算按 P1→P4 顺序填充）
        truncated_groups = self._truncate_by_priority(
            priority_groups, matched_terms, rag_budget
        )

        # Step 8: 结构化上下文组装（PRD §6.4）
        enriched_context = self._assemble_structured_context(truncated_groups)

        # 计算实际消费的 token（P0 不受预算限制，P1~P4 受 rag_budget 上限约束）
        p0_tokens = sum(self._token_estimate(f"{t.get('canonical_term', '')}: {t.get('definition', '')}") for t in matched_terms)
        actual_p1_tokens = sum(self._token_estimate(r["chunk_text"]) for r in truncated_groups.get("p1", []))
        actual_p2_tokens = sum(self._token_estimate(r["chunk_text"]) for r in truncated_groups.get("p2", []))
        actual_p3_tokens = sum(self._token_estimate(r["chunk_text"]) for r in truncated_groups.get("p3", []))
        actual_p4_tokens = sum(self._token_estimate(r["chunk_text"]) for r in truncated_groups.get("p4", []))
        actual_rag_tokens = actual_p1_tokens + actual_p2_tokens + actual_p3_tokens + actual_p4_tokens

        return {
            "context": enriched_context,
            "priority_breakdown": {
                "p0": matched_terms,
                "p1": truncated_groups.get("p1", []),
                "p2": truncated_groups.get("p2", []),
                "p3": truncated_groups.get("p3", []),
                "p4": truncated_groups.get("p4", []),
            },
            "token_breakdown": {
                "system_prompt": SYSTEM_PROMPT_TOKENS,
                "user_instruction": USER_INSTRUCTION_TOKENS,
                # data_context_actual = 字段元数据估算（系统外部注入，v1 使用 DEFAULT_FIELD_METADATA_TOKENS）
                "data_context_actual": DEFAULT_FIELD_METADATA_TOKENS,
                # rag_consumed = P1~P4 实际消费（受 rag_budget 截断后的值）
                "rag_consumed": actual_rag_tokens,
                "rag_budget": rag_budget,
                "total_estimate": (
                    SYSTEM_PROMPT_TOKENS
                    + DEFAULT_FIELD_METADATA_TOKENS
                    + USER_INSTRUCTION_TOKENS
                    + p0_tokens
                    + actual_rag_tokens
                ),
                "p0_tokens": p0_tokens,
                "p1_tokens": actual_p1_tokens,
                "p2_tokens": actual_p2_tokens,
                "p3_tokens": actual_p3_tokens,
                "p4_tokens": actual_p4_tokens,
            },
        }

    async def _filter_sensitivity(self, db: Session, results: List[Dict]) -> List[Dict]:
        """
        PRD §9 敏感度隔离：
        过滤掉 HIGH/CONFIDENTIAL 敏感度的 schema 和 field_semantic 记录。

        Schema 过滤：KbSchema.datasource_id → TableauDatasourceSemantics.id → sensitivity_level
        Field_semantic 过滤：TableauFieldSemantics 自带 sensitivity_level 字段
        """
        from services.semantic_maintenance.models import TableauDatasourceSemantics, TableauFieldSemantics

        schema_ids = []
        field_ids = []
        for r in results:
            if r["source_type"] == "schema":
                schema_ids.append(r["source_id"])
            elif r["source_type"] == "field_semantic":
                field_ids.append(r["source_id"])

        # Step 1: 查询 HIGH/CONFIDENTIAL schema
        # KbSchema.datasource_id = TableauDatasourceSemantics.id（内部主键）
        blocked_schema_ids = set()
        if schema_ids:
            blocked = db.query(TableauDatasourceSemantics.id).filter(
                TableauDatasourceSemantics.id.in_(schema_ids),
                TableauDatasourceSemantics.sensitivity_level.in_(SENSITIVITY_BLOCKLIST)
            ).all()
            blocked_schema_ids.update(row[0] for row in blocked)

        # Step 2: 查询 HIGH/CONFIDENTIAL field_semantic
        # TableauFieldSemantics 自带 sensitivity_level
        blocked_field_ids = set()
        if field_ids:
            blocked = db.query(TableauFieldSemantics.id).filter(
                TableauFieldSemantics.id.in_(field_ids),
                TableauFieldSemantics.sensitivity_level.in_(SENSITIVITY_BLOCKLIST)
            ).all()
            blocked_field_ids.update(row[0] for row in blocked)

        return [
            r for r in results
            if not (
                (r["source_type"] == "schema" and r["source_id"] in blocked_schema_ids)
                or (r["source_type"] == "field_semantic" and r["source_id"] in blocked_field_ids)
            )
        ]

    def _group_by_priority(self, results: List[Dict]) -> Dict[str, List[Dict]]:
        """
        按 P1~P4 优先级分组（PRD §6.1）：
        - P1: glossary 向量
        - P2: document 向量
        - P3: schema 向量
        - P4: field_semantic 向量
        P0 精确匹配不经过此分组（直接用 matched_terms）。
        """
        groups = {"p1": [], "p2": [], "p3": [], "p4": []}
        priority_map = {
            "glossary": "p1",
            "document": "p2",
            "schema": "p3",
            "field_semantic": "p4",
        }
        for r in results:
            p = priority_map.get(r["source_type"])
            if p:
                groups[p].append(r)
        return groups

    def _calc_priority_tokens(
        self, priority_groups: Dict[str, List[Dict]], matched_terms: List[Dict]
    ) -> Dict[str, int]:
        """计算各优先级预估 token 数"""
        tokens = {}

        # P0: 术语精确匹配
        p0_tokens = sum(
            self._token_estimate(
                f"{t.get('canonical_term', '')}: {t.get('definition', '')}"
            )
            for t in matched_terms
        )
        tokens["p0"] = p0_tokens

        # P1~P4: 向量结果
        for p in ("p1", "p2", "p3", "p4"):
            tokens[p] = sum(self._token_estimate(r["chunk_text"]) for r in priority_groups.get(p, []))

        tokens["total"] = sum(tokens[p] for p in ("p0", "p1", "p2", "p3", "p4"))
        return tokens

    def _truncate_by_priority(
        self,
        priority_groups: Dict[str, List[Dict]],
        matched_terms: List[Dict],
        rag_budget: int,
    ) -> Dict[str, List[Dict]]:
        """
        按 P0~P4 优先级顺序截断（PRD §6.1）：
        - P0 精确匹配无条件保留（不占 RAG 预算）
        - P1~P4 共享 RAG 预算，按 P1→P2→P3→P4 顺序填充
        """
        result_groups = {}

        # P0 固定保留
        result_groups["p0"] = matched_terms

        # P1~P4 共享 rag_budget，按优先级顺序截断
        remaining_budget = rag_budget
        priority_order = ["p1", "p2", "p3", "p4"]

        for p in priority_order:
            group = priority_groups.get(p, [])
            truncated = []
            for item in group:
                est = self._token_estimate(item["chunk_text"])
                if est <= remaining_budget:
                    truncated.append(item)
                    remaining_budget -= est
                else:
                    break  # 后续相似度更低，不再尝试
            result_groups[p] = truncated

        return result_groups

    def _assemble_structured_context(self, groups: Dict[str, List[Dict]]) -> str:
        """
        结构化上下文组装（PRD §6.4）：
        - [术语] — P0 术语精确匹配
        - [知识] — P1 glossary + P2 document 向量
        - [模型] — P3 schema + P4 field_semantic 向量
        """
        sections = []

        # [术语] — P0 精确匹配
        if groups.get("p0"):
            term_lines = []
            for t in groups["p0"]:
                line = f"{t.get('canonical_term', t.get('term', ''))}: {t.get('definition', '')}"
                term_lines.append(line)
            if term_lines:
                sections.append("[术语]\n" + "\n".join(term_lines))

        # [知识] — P1 glossary + P2 document
        knowledge_items = groups.get("p1", []) + groups.get("p2", [])
        if knowledge_items:
            know_lines = []
            for r in knowledge_items:
                src_tag = "知识" if r["source_type"] == "document" else "知识"
                line = f"[{src_tag}] {r['chunk_text']}"
                know_lines.append(line)
            sections.append("[知识]\n" + "\n".join(know_lines))

        # [模型] — P3 schema + P4 field_semantic
        model_items = groups.get("p3", []) + groups.get("p4", [])
        if model_items:
            model_lines = []
            for r in model_items:
                line = f"[模型] {r['chunk_text']}"
                model_lines.append(line)
            sections.append("[模型]\n" + "\n".join(model_lines))

        return "\n\n".join(sections) if sections else ""


rag_service = RAGService()
