"""文档服务（知识库 §4）"""
import re
import logging
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session

from .models import KbDocument, KbDocumentDatabase, KbEmbedding
from .embedding_service import embedding_service

logger = logging.getLogger(__name__)

# === 文档分块常量 ===
CHUNK_SIZE = 500          # 每块目标字符数（中文约 250 tokens）
CHUNK_OVERLAP = 50        # 块间重叠字符数
MAX_CHUNK_TEXT_LEN = 2000 # 单块文本上限


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
        滑动窗口分块（PRD §4.3）：
        - 按句子/段落边界切分（优先句号、换行）
        - 每块目标 CHUNK_SIZE 字符
        - 块间重叠 CHUNK_OVERLAP 字符
        """
        if not text or not text.strip():
            return []

        # 先按段落+句子分割
        segments = re.split(r'(?<=[。！？.!?\n])\s*', text)
        chunks = []
        current_chunk = ""
        current_size = 0

        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue

            seg_len = len(seg)
            # 如果单段就超过 MAX_CHUNK_TEXT_LEN，强制截断
            if seg_len > MAX_CHUNK_TEXT_LEN:
                if current_chunk:
                    chunks.append(current_chunk)
                    # 重叠部分
                    current_chunk = current_chunk[-CHUNK_OVERLAP:] if len(current_chunk) > CHUNK_OVERLAP else current_chunk
                    current_size = len(current_chunk)
                # 强制截断超长段落
                for i in range(0, seg_len, CHUNK_SIZE - CHUNK_OVERLAP):
                    sub = seg[i:i + CHUNK_SIZE]
                    chunks.append(sub)
                    current_chunk = sub
                    current_size = len(sub)
                continue

            if current_size + seg_len <= CHUNK_SIZE:
                current_chunk += seg
                current_size += seg_len
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                # 构建新块，保留重叠
                overlap_text = current_chunk[-CHUNK_OVERLAP:] if len(current_chunk) > CHUNK_OVERLAP else ""
                current_chunk = overlap_text + seg
                current_size = len(current_chunk)

        if current_chunk:
            chunks.append(current_chunk)

        return chunks


document_service = DocumentService()
