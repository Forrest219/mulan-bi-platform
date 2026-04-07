"""文档服务（知识库 §4）"""
import re
import logging
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session

from .models import KbDocument, KbDocumentDatabase, KbEmbedding
from .embedding_service import embedding_service

logger = logging.getLogger(__name__)

# === 文档分块常量（Spec 17 §4.4 — tiktoken cl100k_base）===
CHUNK_TOKENS = 512        # 单块最大 Token 数
OVERLAP_TOKENS = 64       # 相邻块重叠 Token 数
# 注意：严禁使用字符数估算（如 len(text) * 1.5），必须使用 tiktoken 精确计数


class DocumentService:
    """知识文档服务 — CRUD + 分块 + Embedding 生成"""

    def __init__(self):
        self._db = KbDocumentDatabase()

    def get_document(self, db: Session, doc_id: int) -> Optional[Dict[str, Any]]:
        """获取文档详情"""
        d = self._db.get(db, doc_id)
        return d.to_dict() if d else None

    def list_documents(
        self, db: Session, page: int = 1, page_size: int = 20,
        category: str = None, status: str = "active"
    ) -> Dict[str, Any]:
        """文档列表"""
        return self._db.list(db, page=page, page_size=page_size, category=category, status=status)

    def create_document(
        self, db: Session, title: str, content: str,
        format: str = "markdown", category: str = "general",
        tags: List[str] = None, created_by: int = None
    ) -> KbDocument:
        """
        创建文档（PRD §4 副作用）：
        创建后立即返回，Embedding 由 Celery Worker 异步生成。
        """
        doc = self._db.create(
            db, title=title, content=content, format=format,
            category=category, tags=tags, created_by=created_by,
        )
        # 触发 Celery 异步任务（不等候完成）
        from services.tasks.knowledge_base_tasks import generate_document_embeddings
        generate_document_embeddings.delay(doc.id)
        return doc

    def update_document(self, db: Session, doc_id: int, **kwargs) -> Optional[Dict[str, Any]]:
        """更新文档"""
        d = self._db.update(db, doc_id, **kwargs)
        return d.to_dict() if d else None

    def delete_document(self, db: Session, doc_id: int, hard: bool = False) -> bool:
        """
        删除文档。
        - hard=False（软删除）：status → archived
        - hard=True（硬删除）：级联清理 kb_embeddings（admin 专属）
        """
        return self._db.delete(db, doc_id, hard=hard)

    def chunk_and_embed(self, db: Session, doc_id: int) -> Dict[str, Any]:
        """
        文档分块 + 向量生成（PRD §4.3 + §5.2）：
        1. 按 CHUNK_SIZE/CHUNK_OVERLAP 滑动窗口分块
        2. 批量生成 Embedding 并存储
        3. 更新 kb_documents.chunk_count 和 last_embedded_at
        """
        doc = self._db.get(db, doc_id)
        if not doc:
            return {"error": f"文档 {doc_id} 不存在"}

        # 分块
        chunks = self._split_into_chunks(doc.content)
        if not chunks:
            return {"error": "文档内容为空，无法分块"}

        # 批量生成 Embedding（同步调用异步服务）
        return self._chunk_and_embed_sync(db, doc, chunks)

    def _chunk_and_embed_sync(self, db: Session, doc: KbDocument, chunks: List[str]) -> Dict[str, Any]:
        """同步分块嵌入实现"""
        import asyncio

        async def _batch_embed():
            return await embedding_service.batch_generate_and_store(
                db=db,
                source_type="document",
                source_id=doc.id,
                chunks=[{"chunk_index": i, "chunk_text": c} for i, c in enumerate(chunks)],
            )

        count = asyncio.run(_batch_embed())

        # 更新文档元数据
        self._db.update_embedding_meta(db, doc.id, chunk_count=count)

        return {
            "doc_id": doc.id,
            "chunk_count": count,
            "message": f"成功生成 {count} 个 Chunk 的 Embedding",
        }

    def _split_into_chunks(self, text: str) -> List[str]:
        """
        按 Token 数量分块（Spec 17 §4.4 — P0 强制约束）：
        - 必须使用 tiktoken (cl100k_base) 精确计数
        - 每块 CHUNK_TOKENS=512，最大不超过
        - 相邻块重叠 OVERLAP_TOKENS=64
        - 优先按段落边界分割，最后回退到固定长度截断
        """
        if not text or not text.strip():
            return []

        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            raise RuntimeError(
                "tiktoken 未安装，请执行: pip install tiktoken"
            )

        # 按段落+句子分割（保留语义边界）
        segments = re.split(r'(?<=[。！？.!?\n])\s*', text)

        chunks: List[str] = []
        current_tokens: List[int] = []
        current_text_parts: List[str] = []

        def _finish_chunk() -> None:
            """将当前累积的文本作为一个 chunk 并入结果列表"""
            if current_text_parts:
                chunks.append("".join(current_text_parts))
                current_text_parts.clear()
                current_tokens.clear()

        def _token_count(text_parts: List[str]) -> int:
            return len(enc.encode("".join(text_parts)))

        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue

            seg_tokens = enc.encode(seg)
            seg_len = len(seg_tokens)

            # 单段超过 CHUNK_TOKENS：强制固定长度截断
            if seg_len > CHUNK_TOKENS:
                _finish_chunk()
                # 固定长度滑动窗口截断
                for i in range(0, seg_len, CHUNK_TOKENS - OVERLAP_TOKENS):
                    window = seg_tokens[i:i + CHUNK_TOKENS]
                    if window:
                        chunks.append(enc.decode(window))
                continue

            # 累加到当前块
            if not current_tokens:
                current_tokens.extend(seg_tokens)
                current_text_parts.append(seg)
                continue

            # 加上本段后超限
            if len(current_tokens) + seg_len > CHUNK_TOKENS:
                # 当前块结束，押入结果
                _finish_chunk()
                # 重叠部分：从上一块末尾取 OVERLAP_TOKENS tokens
                if chunks:
                    last_chunk_tokens = enc.encode(chunks[-1])
                    overlap = last_chunk_tokens[-OVERLAP_TOKENS:]
                    current_tokens = list(overlap)
                    current_text_parts = [enc.decode(overlap)]
                else:
                    current_tokens = []
                    current_text_parts = []
                # 重新加入本段
                current_tokens.extend(seg_tokens)
                current_text_parts.append(seg)
            else:
                current_tokens.extend(seg_tokens)
                current_text_parts.append(seg)

        _finish_chunk()
        return chunks


document_service = DocumentService()
