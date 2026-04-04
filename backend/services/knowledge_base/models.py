"""知识库数据模型（PRD §2）"""
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column, Integer, String, Text, DateTime,
    Boolean, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import Session

from app.core.database import Base, JSONB, sa_func


# === kb_glossary ===

class KbGlossary(Base):
    """业务术语表 kb_glossary（PRD §2.2）"""
    __tablename__ = "kb_glossary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    term = Column(String(128), nullable=False, index=True)
    canonical_term = Column(String(128), nullable=False)
    synonyms_json = Column(JSONB, nullable=True, server_default="'[]'")
    definition = Column(Text, nullable=False)
    formula = Column(Text, nullable=True)
    category = Column(String(64), nullable=False, server_default="'concept'")
    related_fields_json = Column(JSONB, nullable=True, server_default="'[]'")
    source = Column(String(16), nullable=False, server_default="'manual'")
    status = Column(String(16), nullable=False, server_default="'active'")
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=False, server_default=sa_func.now(), onupdate=sa_func.now())

    __table_args__ = (
        UniqueConstraint("canonical_term", name="uq_glossary_canonical"),
        Index("ix_glossary_category", "category"),
        Index("ix_glossary_status", "status"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "term": self.term,
            "canonical_term": self.canonical_term,
            "synonyms": self.synonyms_json or [],
            "definition": self.definition,
            "formula": self.formula,
            "category": self.category,
            "related_fields": self.related_fields_json or [],
            "source": self.source,
            "status": self.status,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.updated_at else None,
        }


# === kb_schemas ===

class KbSchema(Base):
    """数据模型语义描述 kb_schemas（PRD §2.3）"""
    __tablename__ = "kb_schemas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    datasource_id = Column(Integer, nullable=False, index=True)
    schema_yaml = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, server_default="1")
    auto_generated = Column(Boolean, nullable=False, server_default="false")
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=False, server_default=sa_func.now(), onupdate=sa_func.now())

    __table_args__ = (
        UniqueConstraint("datasource_id", "version", name="uq_schema_ds_version"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "datasource_id": self.datasource_id,
            "schema_yaml": self.schema_yaml,
            "description": self.description,
            "version": self.version,
            "auto_generated": self.auto_generated,
            "created_by": self.created_by,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.updated_at else None,
        }


# === kb_documents ===

class KbDocument(Base):
    """知识文档 kb_documents（PRD §2.4）"""
    __tablename__ = "kb_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    format = Column(String(16), nullable=False, server_default="'markdown'")
    category = Column(String(64), nullable=False, server_default="'general'")
    tags_json = Column(JSONB, nullable=True, server_default="'[]'")
    status = Column(String(16), nullable=False, server_default="'active'")
    chunk_count = Column(Integer, nullable=False, server_default="0")
    last_embedded_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=False, server_default=sa_func.now(), onupdate=sa_func.now())

    __table_args__ = (
        Index("ix_doc_category", "category"),
        Index("ix_doc_status", "status"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "format": self.format,
            "category": self.category,
            "tags": self.tags_json or [],
            "status": self.status,
            "chunk_count": self.chunk_count,
            "last_embedded_at": self.last_embedded_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.last_embedded_at else None,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.updated_at else None,
        }


# === kb_embeddings ===

class KbEmbedding(Base):
    """向量索引 kb_embeddings（PRD §2.5，HNSW 索引）"""
    __tablename__ = "kb_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_type = Column(String(32), nullable=False)
    source_id = Column(Integer, nullable=False)
    chunk_index = Column(Integer, nullable=False, server_default="0")
    chunk_text = Column(Text, nullable=False)
    embedding = Column(JSONB, nullable=False)
    model_name = Column(String(128), nullable=False)
    token_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())

    __table_args__ = (
        Index("ix_emb_source", "source_type", "source_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "chunk_index": self.chunk_index,
            "chunk_text": self.chunk_text,
            "embedding": self.embedding,
            "model_name": self.model_name,
            "token_count": self.token_count,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.created_at else None,
        }


# === 数据库操作类 ===

class KbGlossaryDatabase:
    """kb_glossary CRUD + 术语精确匹配"""

    def create(self, db: Session, term: str, canonical_term: str, definition: str,
               category: str = "concept", synonyms: list = None, formula: str = None,
               related_fields: list = None, source: str = "manual",
               created_by: int = None) -> KbGlossary:
        g = KbGlossary(
            term=term, canonical_term=canonical_term, definition=definition,
            category=category, synonyms_json=synonyms or [],
            formula=formula, related_fields_json=related_fields or [],
            source=source, created_by=created_by,
        )
        db.add(g); db.commit(); db.refresh(g)
        return g

    def get(self, db: Session, glossary_id: int) -> Optional[KbGlossary]:
        return db.query(KbGlossary).filter(KbGlossary.id == glossary_id).first()

    def list(self, db: Session, page: int = 1, page_size: int = 20,
             category: str = None, status: str = "active",
             keyword: str = None) -> Dict[str, Any]:
        q = db.query(KbGlossary)
        if category:
            q = q.filter(KbGlossary.category == category)
        if status:
            q = q.filter(KbGlossary.status == status)
        if keyword:
            q = q.filter(
                (KbGlossary.term.ilike(f"%{keyword}%")) |
                (KbGlossary.canonical_term.ilike(f"%{keyword}%")) |
                (KbGlossary.synonyms_json.cast(String).ilike(f"%{keyword}%"))
            )
        total = q.count()
        items = q.order_by(KbGlossary.id.desc()).offset((page-1)*page_size).limit(page_size).all()
        return {"items": [g.to_dict() for g in items], "total": total, "page": page, "page_size": page_size}

    def update(self, db: Session, glossary_id: int, **kwargs) -> Optional[KbGlossary]:
        g = self.get(db, glossary_id)
        if not g:
            return None
        for k, v in kwargs.items():
            if hasattr(g, k) and k not in ("id", "created_at"):
                setattr(g, k, v)
        db.commit(); db.refresh(g)
        return g

    def soft_delete(self, db: Session, glossary_id: int) -> bool:
        g = self.get(db, glossary_id)
        if not g:
            return False
        g.status = "deprecated"
        db.commit()
        return True

    def hard_delete(self, db: Session, glossary_id: int) -> bool:
        g = self.get(db, glossary_id)
        if not g:
            return False
        db.query(KbEmbedding).filter(
            KbEmbedding.source_type == "glossary",
            KbEmbedding.source_id == glossary_id,
        ).delete(synchronize_session=False)
        db.delete(g); db.commit()
        return True

    def match_by_term(self, db: Session, query: str) -> List[Dict]:
        """术语精确匹配：term / canonical_term / synonyms"""
        results = db.query(KbGlossary).filter(
            KbGlossary.status == "active",
            (KbGlossary.term == query) |
            (KbGlossary.canonical_term == query) |
            (KbGlossary.synonyms_json.cast(String).contains(query))
        ).all()
        return [g.to_dict() for g in results]

    def get_by_ids(self, db: Session, ids: List[int]) -> List[KbGlossary]:
        return db.query(KbGlossary).filter(KbGlossary.id.in_(ids)).all()


class KbDocumentDatabase:
    """kb_documents CRUD"""

    def create(self, db: Session, title: str, content: str,
               format: str = "markdown", category: str = "general",
               tags: list = None, created_by: int = None) -> KbDocument:
        d = KbDocument(
            title=title, content=content, format=format, category=category,
            tags_json=tags or [], created_by=created_by,
        )
        db.add(d); db.commit(); db.refresh(d)
        return d

    def get(self, db: Session, doc_id: int) -> Optional[KbDocument]:
        return db.query(KbDocument).filter(KbDocument.id == doc_id).first()

    def list(self, db: Session, page: int = 1, page_size: int = 20,
             category: str = None, status: str = "active") -> Dict[str, Any]:
        q = db.query(KbDocument)
        if category:
            q = q.filter(KbDocument.category == category)
        if status:
            q = q.filter(KbDocument.status == status)
        total = q.count()
        items = q.order_by(KbDocument.id.desc()).offset((page-1)*page_size).limit(page_size).all()
        return {"items": [d.to_dict() for d in items], "total": total, "page": page, "page_size": page_size}

    def update(self, db: Session, doc_id: int, **kwargs) -> Optional[KbDocument]:
        d = self.get(db, doc_id)
        if not d:
            return None
        for k, v in kwargs.items():
            if hasattr(d, k) and k not in ("id", "created_at"):
                setattr(d, k, v)
        db.commit(); db.refresh(d)
        return d

    def delete(self, db: Session, doc_id: int) -> bool:
        d = self.get(db, doc_id)
        if not d:
            return False
        db.query(KbEmbedding).filter(
            KbEmbedding.source_type == "document",
            KbEmbedding.source_id == doc_id,
        ).delete(synchronize_session=False)
        db.delete(d); db.commit()
        return True

    def update_embedding_meta(self, db: Session, doc_id: int, chunk_count: int):
        d = self.get(db, doc_id)
        if d:
            d.chunk_count = chunk_count
            d.last_embedded_at = sa_func.now()
            db.commit()


class KbEmbeddingDatabase:
    """kb_embeddings 向量操作（HNSW 索引）"""

    def upsert(self, db: Session, source_type: str, source_id: int,
               chunk_index: int, chunk_text: str, embedding: list,
               model_name: str, token_count: int = None) -> KbEmbedding:
        # 删除旧记录（重新生成时）
        db.query(KbEmbedding).filter(
            KbEmbedding.source_type == source_type,
            KbEmbedding.source_id == source_id,
            KbEmbedding.chunk_index == chunk_index,
        ).delete(synchronize_session=False)
        e = KbEmbedding(
            source_type=source_type, source_id=source_id,
            chunk_index=chunk_index, chunk_text=chunk_text,
            embedding=embedding, model_name=model_name, token_count=token_count,
        )
        db.add(e); db.commit(); db.refresh(e)
        return e

    def batch_upsert(self, db: Session, records: List[Dict]) -> int:
        """批量写入 Embedding 记录"""
        if not records:
            return 0
        for r in records:
            db.query(KbEmbedding).filter(
                KbEmbedding.source_type == r["source_type"],
                KbEmbedding.source_id == r["source_id"],
                KbEmbedding.chunk_index == r["chunk_index"],
            ).delete(synchronize_session=False)
        objs = [KbEmbedding(**r) for r in records]
        db.bulk_save_objects(objs); db.commit()
        return len(records)

    def search_by_vector(self, db: Session, query_embedding: list,
                        top_k: int = 5, threshold: float = 0.7,
                        source_type: str = None) -> List[Dict]:
        """
        余弦相似度向量检索。
        使用 HNSW 索引（m=16, ef_construction=200，CREATE INDEX 时指定）。
        手动计算 1 - cosine_distance 作为 similarity。
        """
        from sqlalchemy import text
        # 计算余弦相似度：1 - (a <=> b)，pgvector 的 <=> 是余弦距离
        query = text("""
            SELECT id, source_type, source_id, chunk_index, chunk_text,
                   model_name, token_count, created_at,
                   1 - (embedding <=> :query_embedding::vector) AS similarity
            FROM kb_embeddings
            WHERE 1 - (embedding <=> :query_embedding::vector) > :threshold
            ORDER BY embedding <=> :query_embedding::vector
            LIMIT :top_k
        """)
        params = {
            "query_embedding": str(query_embedding),
            "threshold": threshold,
            "top_k": top_k,
        }
        if source_type:
            query = text("""
                SELECT id, source_type, source_id, chunk_index, chunk_text,
                       model_name, token_count, created_at,
                       1 - (embedding <=> :query_embedding::vector) AS similarity
                FROM kb_embeddings
                WHERE source_type = :source_type
                  AND 1 - (embedding <=> :query_embedding::vector) > :threshold
                ORDER BY embedding <=> :query_embedding::vector
                LIMIT :top_k
            """)
            params["source_type"] = source_type

        result = db.execute(query, params)
        rows = result.fetchall()
        return [
            {
                "id": row.id,
                "source_type": row.source_type,
                "source_id": row.source_id,
                "chunk_index": row.chunk_index,
                "chunk_text": row.chunk_text,
                "model_name": row.model_name,
                "token_count": row.token_count,
                "similarity": float(row.similarity),
                "created_at": row.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if row.created_at else None,
            }
            for row in rows
        ]

    def delete_by_source(self, db: Session, source_type: str, source_id: int):
        db.query(KbEmbedding).filter(
            KbEmbedding.source_type == source_type,
            KbEmbedding.source_id == source_id,
        ).delete(synchronize_session=False)
        db.commit()
