"""知识库数据模型（PRD §2）"""
import json
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column, Integer, String, Text, DateTime,
    Boolean, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import Session

from app.core.database import Base, JSONB, sa_func, sa_text


# === kb_glossary ===

class KbGlossary(Base):
    """业务术语表 kb_glossary（PRD §2.2）"""
    __tablename__ = "kb_glossary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    term = Column(String(128), nullable=False, index=True)
    canonical_term = Column(String(128), nullable=False)
    synonyms_json = Column(JSONB, nullable=True, server_default=sa_text("'[]'::jsonb"))
    definition = Column(Text, nullable=False)
    formula = Column(Text, nullable=True)
    category = Column(String(64), nullable=False, server_default=sa_text("'concept'"))
    related_fields_json = Column(JSONB, nullable=True, server_default=sa_text("'[]'::jsonb"))
    source = Column(String(16), nullable=False, server_default=sa_text("'manual'"))
    status = Column(String(16), nullable=False, server_default=sa_text("'active'"))
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

    def build_embedding_text(self) -> str:
        """
        按 PRD §5.1 构造 Embedding 文本格式。
        glossary: "{canonical_term}: {definition}。同义词: {synonyms}。公式: {formula}"
        """
        parts = [f"{self.canonical_term}: {self.definition}"]
        synonyms = self.synonyms_json or []
        if synonyms:
            parts.append(f"同义词: {', '.join(synonyms)}")
        if self.formula:
            parts.append(f"公式: {self.formula}")
        return "。".join(parts)


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

    def build_embedding_text(self) -> str:
        """
        按 PRD §5.1 构造 schema 类型的 Embedding 文本。
        schema: "{datasource_id} 数据模型: {description}。{schema_yaml 摘要}"
        """
        # schema_yaml 可能很长，取前 500 字符作为摘要
        yaml_summary = self.schema_yaml[:500] if self.schema_yaml else ""
        parts = [f"{self.datasource_id} 数据模型"]
        if self.description:
            parts.append(f"{self.description}")
        if yaml_summary:
            parts.append(f"。{yaml_summary}")
        return "".join(parts)


# === kb_documents ===

class KbDocument(Base):
    """知识文档 kb_documents（PRD §2.4）"""
    __tablename__ = "kb_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    format = Column(String(16), nullable=False, server_default=sa_text("'markdown'"))
    category = Column(String(64), nullable=False, server_default=sa_text("'general'"))
    tags_json = Column(JSONB, nullable=True, server_default=sa_text("'[]'::jsonb"))
    status = Column(String(16), nullable=False, server_default=sa_text("'active'"))
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

    def build_embedding_text(self, chunk_text: str) -> str:
        """
        按 PRD §5.1 构造 document 类型的 Embedding 文本。
        document: 分块后的原始文本（chunk_text 即为已分块内容）
        """
        return chunk_text


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

    def delete(self, db: Session, doc_id: int, hard: bool = False) -> bool:
        """
        删除文档。
        - hard=False（软删除）：status → archived（data_admin 操作）
        - hard=True（硬删除）：同时清理 kb_embeddings（admin 专属）
        """
        d = self.get(db, doc_id)
        if not d:
            return False
        if hard:
            # 硬删除：级联清理向量
            db.query(KbEmbedding).filter(
                KbEmbedding.source_type == "document",
                KbEmbedding.source_id == doc_id,
            ).delete(synchronize_session=False)
            db.delete(d)
        else:
            # 软删除：标记为 archived
            d.status = "archived"
        db.commit()
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
        """批量写入 Embedding 记录（P0 幽灵向量修复：先清后插，同一事务）"""
        if not records:
            return 0
        # 提取单一实体标识（batch_upsert 按实体粒度调用，所有记录同源）
        first = records[0]
        type_ = first["source_type"]
        id_ = first["source_id"]
        # 先一次性清空该实体所有旧向量，防止内容缩减后残留幽灵向量
        db.query(KbEmbedding).filter(
            KbEmbedding.source_type == type_,
            KbEmbedding.source_id == id_,
        ).delete(synchronize_session=False)
        # 插入新记录，同一事务完成
        objs = [KbEmbedding(**r) for r in records]
        db.bulk_save_objects(objs)
        db.commit()
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


# === YAML Schema 验证器（Spec 17 §2.3 v1.0）===

class YAMLValidationError(Exception):
    """YAML 结构不符合 v1.0 规范（KB_010）"""
    pass


def validate_schema_yaml(yaml_content: str) -> dict:
    """
    校验 schema_yaml 内容是否符合 v1.0 规范（Spec 17 §2.3）。

    校验规则：
    - 顶级字段只允许：version, datasource_name, tables, relationships
    - tables[].name, tables[].description, tables[].columns 必须存在
    - columns[].name, columns[].type, columns[].description 必须存在
    - relationships[].type, from_table, from_column, to_table, to_column 必须存在

    Returns:
        解析后的 dict（供调用方使用）

    Raises:
        YAMLValidationError: 校验失败，返回 KB_010 错误码
    """
    import yaml

    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise YAMLValidationError(f"YAML 语法错误: {e}")

    if not isinstance(data, dict):
        raise YAMLValidationError("YAML 根对象必须是字典")

    # 顶级字段白名单
    ALLOWED_TOP_KEYS = {"version", "datasource_name", "tables", "relationships"}
    unknown_keys = set(data.keys()) - ALLOWED_TOP_KEYS
    if unknown_keys:
        raise YAMLValidationError(
            f"不允许的顶级字段: {sorted(unknown_keys)}。v1.0 只允许: {sorted(ALLOWED_TOP_KEYS)}"
        )

    # tables 必为列表
    tables = data.get("tables", [])
    if not isinstance(tables, list):
        raise YAMLValidationError("tables 必须是数组")

    for i, tbl in enumerate(tables):
        if not isinstance(tbl, dict):
            raise YAMLValidationError(f"tables[{i}] 必须是字典")
        if "name" not in tbl:
            raise YAMLValidationError(f"tables[{i}].name 必填")
        if "description" not in tbl:
            raise YAMLValidationError(f"tables[{i}].description 必填")
        if "columns" not in tbl:
            raise YAMLValidationError(f"tables[{i}].columns 必填")
        if not isinstance(tbl["columns"], list):
            raise YAMLValidationError(f"tables[{i}].columns 必须是数组")

        for j, col in enumerate(tbl["columns"]):
            if not isinstance(col, dict):
                raise YAMLValidationError(f"tables[{i}].columns[{j}] 必须是字典")
            for field in ("name", "type", "description"):
                if field not in col:
                    raise YAMLValidationError(
                        f"tables[{i}].columns[{j}].{field} 必填"
                    )

    # relationships 必为列表（可为空）
    rels = data.get("relationships", [])
    if not isinstance(rels, list):
        raise YAMLValidationError("relationships 必须是数组")

    for i, rel in enumerate(rels):
        if not isinstance(rel, dict):
            raise YAMLValidationError(f"relationships[{i}] 必须是字典")
        for field in ("type", "from_table", "from_column", "to_table", "to_column"):
            if field not in rel:
                raise YAMLValidationError(
                    f"relationships[{i}].{field} 必填"
                )

    return data


class KbSchemaDatabase:
    """kb_schemas CRUD + YAML v1.0 校验"""

    def create(
        self, db: Session, datasource_id: int, schema_yaml: str,
        description: str = None, version: int = 1,
        auto_generated: bool = False, created_by: int = None
    ) -> KbSchema:
        """
        创建 Schema（P1 YAML 强校验）：
        写入前必须通过 validate_schema_yaml() 校验，不通过则抛出 YAMLValidationError（KB_010）。
        """
        validate_schema_yaml(schema_yaml)  # 校验失败抛 YAMLValidationError
        s = KbSchema(
            datasource_id=datasource_id,
            schema_yaml=schema_yaml,
            description=description,
            version=version,
            auto_generated=auto_generated,
            created_by=created_by,
        )
        db.add(s); db.commit(); db.refresh(s)
        return s

    def get(self, db: Session, schema_id: int) -> Optional[KbSchema]:
        return db.query(KbSchema).filter(KbSchema.id == schema_id).first()

    def get_by_datasource(
        self, db: Session, datasource_id: int, version: int = None
    ) -> Optional[KbSchema]:
        q = db.query(KbSchema).filter(KbSchema.datasource_id == datasource_id)
        if version is not None:
            q = q.filter(KbSchema.version == version)
        return q.order_by(KbSchema.version.desc()).first()

    def update(
        self, db: Session, schema_id: int,
        schema_yaml: str = None, description: str = None,
        **kwargs
    ) -> Optional[KbSchema]:
        """
        更新 Schema（P1 YAML 强校验）：
        若传入 schema_yaml 必须通过校验，不通过则抛出 YAMLValidationError。
        """
        s = self.get(db, schema_id)
        if not s:
            return None
        if schema_yaml is not None:
            validate_schema_yaml(schema_yaml)
            s.schema_yaml = schema_yaml
        if description is not None:
            s.description = description
        db.commit(); db.refresh(s)
        return s

    def delete(self, db: Session, schema_id: int, hard: bool = False) -> bool:
        """
        删除 Schema：
        - hard=False（软删除）：admin 操作，本版本暂不实现 status 字段
        - hard=True（硬删除）：同时清理 kb_embeddings
        """
        s = self.get(db, schema_id)
        if not s:
            return False
        if hard:
            from .models import KbEmbedding
            db.query(KbEmbedding).filter(
                KbEmbedding.source_type == "schema",
                KbEmbedding.source_id == schema_id,
            ).delete(synchronize_session=False)
            db.delete(s)
        db.commit()
        return True

