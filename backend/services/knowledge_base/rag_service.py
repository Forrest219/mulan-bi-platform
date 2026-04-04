"""RAG 服务（知识库 §6）"""
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from .embedding_service import embedding_service
from .models import KbGlossaryDatabase, KbEmbeddingDatabase

logger = logging.getLogger(__name__)

# === Token 预算常量（PRD §6.2）===
SYSTEM_PROMPT_TOKENS = 200      # System Prompt 固定开销
USER_INSTRUCTION_TOKENS = 800   # 用户指令固定开销
MIN_CONTEXT_TOKENS = 200        # RAG 可用上下文最低保障
RAG_BUDGET_TOKENS = 3000        # 总 Token 预算上限


class RAGService:
    """RAG 上下文增强服务 — 动态 Token 预算分配"""

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

    async def enrich_context(
        self, db: Session, question: str, scenario: str = "default"
    ) -> Dict[str, Any]:
        """
        RAG 上下文增强主入口（PRD §6.1 + §6.2）。

        流程：
        1. 术语精确匹配（Glossary.match_terms）
        2. 向量相似度检索（EmbeddingService.search）
        3. 动态分配 Token 预算，组装上下文文本
        4. 返回 { "context": str, "terms": [...], "sources": [...], "token_breakdown": {...} }
        """
        # Step 1: 术语精确匹配
        matched_terms = self._glossary_db.match_by_term(db, question)
        term_texts = []
        term_token_est = 0
        for t in matched_terms:
            text = f"[术语] {t['term']}（标准名：{t['canonical_term']}）：{t['definition']}"
            term_texts.append(text)
            # 粗略估算：中文按字符数，英文按单词数，1 token ≈ 0.75 词
            term_token_est += int(len(text) * 0.5)

        # Step 2: 向量相似度检索
        try:
            query_embedding = await embedding_service.embed_text(question)
            vector_results = self._embedding_db.search_by_vector(
                db, query_embedding, top_k=5, threshold=0.7
            )
        except Exception as e:
            logger.warning("向量检索失败: %s", e)
            vector_results = []

        # Step 3: 计算数据上下文实际占用
        context_texts = []
        context_token_est = term_token_est
        source_token_est = 0

        # 添加术语到上下文
        context_texts.extend(term_texts)

        # 添加向量检索结果
        for r in vector_results:
            src_label = f"[来源] {r['source_type']} #{r['source_id']} Chunk-{r['chunk_index']}"
            src_text = f"{src_label}：{r['chunk_text']}"
            context_texts.append(src_text)
            source_token_est += int(len(r['chunk_text']) * 0.5)

        context_token_est += source_token_est

        # Step 4: 动态预算分配
        rag_budget = self._calc_rag_budget(context_token_est)

        # 按预算截断上下文（优先保留术语，再按相关性排序截断向量结果）
        enriched_context = self._truncate_context(context_texts, rag_budget)

        return {
            "context": enriched_context,
            "terms": matched_terms,
            "sources": vector_results,
            "token_breakdown": {
                "system_prompt": SYSTEM_PROMPT_TOKENS,
                "user_instruction": USER_INSTRUCTION_TOKENS,
                "data_context_actual": context_token_est,
                "rag_budget": rag_budget,
                "total_estimate": SYSTEM_PROMPT_TOKENS + USER_INSTRUCTION_TOKENS + context_token_est,
            },
        }

    def _truncate_context(self, context_texts: List[str], max_tokens: int) -> str:
        """
        按 Token 预算截断上下文文本。
        简单估算：按字符数 * 0.5 估算 Token 数。
        """
        selected = []
        current_tokens = 0
        for text in context_texts:
            est_tokens = int(len(text) * 0.5)
            if current_tokens + est_tokens <= max_tokens:
                selected.append(text)
                current_tokens += est_tokens
            else:
                break
        return "\n\n".join(selected) if selected else ""


rag_service = RAGService()
