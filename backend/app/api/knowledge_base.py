"""知识库 API（PRD §7 + §8 + §9）"""
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from services.knowledge_base.document_service import document_service
from services.knowledge_base.embedding_service import embedding_service
from services.knowledge_base.errors import KBErrorCode, kb_error_response
from services.knowledge_base.glossary_service import glossary_service
from services.knowledge_base.models import KbDocument, KbGlossary, KbSchema
from services.knowledge_base.rag_service import rag_service


class RagEnrichRequest(BaseModel):
    """RAG enrich 请求体（PRD §7.11）"""

    question: str
    scenario: str = "default"

router = APIRouter()


def _require_role(user, min_role: str) -> None:
    """权限拦截：analyst < data_admin < admin"""
    role_rank = {"user": 0, "analyst": 1, "data_admin": 2, "admin": 3}
    user_rank = role_rank.get(user.get("role", "user"), 0)
    min_rank = role_rank.get(min_role, 0)
    if user_rank < min_rank:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "KB_011", "message": "权限不足"}
        )


def _error_response(code: KBErrorCode, status_code: int, **kwargs):
    return HTTPException(
        status_code=status_code,
        detail=kb_error_response(code, status_code, **kwargs)
    )


def _format_search_result(db: Session, raw: Dict) -> Dict:
    """将原始向量检索结果格式化为 PRD §7.10 规定格式：
    {source_type, source_id, title, content, similarity}
    - title: 从对应源表查询（glossary→canonical_term, document→title, schema→datasource_id, field_semantic→semantic_name_zh）
    - content: chunk_text
    - similarity: 原始相似度得分
    """
    from services.semantic_maintenance.models import TableauFieldSemantics

    source_type = raw["source_type"]
    source_id = raw["source_id"]
    similarity = raw.get("similarity", 0.0)

    title = f"{source_type}_{source_id}"  # 默认 title
    content = raw.get("chunk_text", "")

    if source_type == "glossary":
        record = db.query(KbGlossary).filter(KbGlossary.id == source_id).first()
        if record:
            title = record.canonical_term
            content = record.definition
    elif source_type == "document":
        record = db.query(KbDocument).filter(KbDocument.id == source_id).first()
        if record:
            title = record.title
            # content 保留 chunk_text（分块后的文本片段）
    elif source_type == "schema":
        record = db.query(KbSchema).filter(KbSchema.id == source_id).first()
        if record:
            title = f"schema_{record.datasource_id}"
            content = record.description or record.schema_yaml[:500] if record.schema_yaml else ""
    elif source_type == "field_semantic":
        record = db.query(TableauFieldSemantics).filter(TableauFieldSemantics.id == source_id).first()
        if record:
            title = record.semantic_name_zh or record.semantic_name or f"field_{source_id}"
            content = record.semantic_definition or ""

    return {
        "source_type": source_type,
        "source_id": source_id,
        "title": title,
        "content": content,
        "similarity": similarity,
    }


# === 术语端点 ===

@router.get("/glossary")
async def list_glossary(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """术语列表（PRD §7.1）GET /api/knowledge-base/glossary — analyst+"""
    _require_role(user, "analyst")

    result = glossary_service.search_terms(
        db, keyword=keyword, category=category, page=page, page_size=page_size
    )
    return result


@router.post("/glossary")
async def create_glossary(
    term: str,
    canonical_term: str,
    definition: str,
    category: str = "concept",
    synonyms: str = "",
    formula: Optional[str] = None,
    related_fields: str = "",
    source: str = "manual",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """创建术语（PRD §7.2）POST /api/knowledge-base/glossary — data_admin+"""
    _require_role(user, "data_admin")

    if not definition or not definition.strip():
        raise _error_response(KBErrorCode.TERM_MISSING_FIELD, 400)

    import json
    synonyms_list = json.loads(synonyms) if synonyms else []
    related_fields_list = json.loads(related_fields) if related_fields else []

    try:
        glossary = glossary_service.create_term(
            db,
            term=term,
            canonical_term=canonical_term,
            definition=definition,
            category=category,
            synonyms=synonyms_list,
            formula=formula,
            related_fields=related_fields_list,
            source=source,
            created_by=user.get("id"),
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise _error_response(KBErrorCode.TERM_DUPLICATE, 409)
        raise

    return {"id": glossary.id, "message": "术语创建成功"}


@router.get("/glossary/{glossary_id}")
async def get_glossary(glossary_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """术语详情（PRD §7.3）GET /api/knowledge-base/glossary/{id} — analyst+"""
    _require_role(user, "analyst")

    result = glossary_service.get_term(db, glossary_id)
    if not result:
        raise _error_response(KBErrorCode.TERM_NOT_FOUND, 404)
    return result


@router.put("/glossary/{glossary_id}")
async def update_glossary(
    glossary_id: int,
    term: Optional[str] = None,
    canonical_term: Optional[str] = None,
    definition: Optional[str] = None,
    category: Optional[str] = None,
    synonyms: Optional[str] = None,
    formula: Optional[str] = None,
    related_fields: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """更新术语（PRD §7.4）PUT /api/knowledge-base/glossary/{id} — data_admin+"""
    _require_role(user, "data_admin")

    import json
    kwargs = {}
    if term is not None:
        kwargs["term"] = term
    if canonical_term is not None:
        kwargs["canonical_term"] = canonical_term
    if definition is not None:
        if not definition.strip():
            raise _error_response(KBErrorCode.TERM_MISSING_FIELD, 400)
        kwargs["definition"] = definition
    if category is not None:
        kwargs["category"] = category
    if synonyms is not None:
        kwargs["synonyms_json"] = json.loads(synonyms) if synonyms else []
    if formula is not None:
        kwargs["formula"] = formula
    if related_fields is not None:
        kwargs["related_fields_json"] = json.loads(related_fields) if related_fields else []
    if status is not None:
        kwargs["status"] = status

    result = glossary_service.update_term(db, glossary_id, **kwargs)
    if not result:
        raise _error_response(KBErrorCode.TERM_NOT_FOUND, 404)
    return result


@router.delete("/glossary/{glossary_id}")
async def delete_glossary(
    glossary_id: int,
    hard: bool = Query(False, description="硬删除（仅 admin）"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """删除术语（PRD §7.5）DELETE /api/knowledge-base/glossary/{id}
    - hard=false（默认）：软删除（data_admin+），status → deprecated
    - hard=true：硬删除（admin 专属），同时清理 kb_embeddings
    """

    if hard:
        _require_role(user, "admin")
        success = glossary_service.hard_delete_term(db, glossary_id)
    else:
        _require_role(user, "data_admin")
        success = glossary_service.deprecate_term(db, glossary_id)

    if not success:
        raise _error_response(KBErrorCode.TERM_NOT_FOUND, 404)
    return {"message": "术语已删除" if hard else "术语已标记为 deprecated"}


# === 文档端点 ===

@router.get("/documents")
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """文档列表（PRD §7.6）GET /api/knowledge-base/documents — analyst+"""
    _require_role(user, "analyst")

    return document_service.list_documents(db, page=page, page_size=page_size, category=category)


@router.post("/documents")
async def create_document(
    title: str,
    content: str,
    format: str = "markdown",
    category: str = "general",
    tags: str = "",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """创建文档（PRD §7.7）POST /api/knowledge-base/documents — data_admin+
    副作用：Celery Worker 异步生成 Embedding（不等候完成，立即返回 201）。
    """
    _require_role(user, "data_admin")

    if not content or not content.strip():
        raise _error_response(KBErrorCode.DOC_EMPTY_CONTENT, 400)

    supported_formats = {"markdown", "text"}
    if format not in supported_formats:
        raise _error_response(KBErrorCode.DOC_UNSUPPORTED_FORMAT, 400, format=format)

    import json
    tags_list = json.loads(tags) if tags else []

    doc = document_service.create_document(
        db,
        title=title,
        content=content,
        format=format,
        category=category,
        tags=tags_list,
        created_by=user.get("id"),
    )
    return {"id": doc.id, "message": "文档创建成功"}


@router.get("/documents/{doc_id}")
async def get_document(doc_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """获取文档详情（PRD §7.x）GET /api/knowledge-base/documents/{id} — analyst+"""
    _require_role(user, "analyst")

    result = document_service.get_document(db, doc_id)
    if not result:
        raise _error_response(KBErrorCode.DOC_NOT_FOUND, 404)
    return result


@router.put("/documents/{doc_id}")
async def update_document(
    doc_id: int,
    title: Optional[str] = None,
    content: Optional[str] = None,
    format: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """更新文档（PRD §7.x）PUT /api/knowledge-base/documents/{id} — data_admin+"""
    _require_role(user, "data_admin")

    if content is not None and not content.strip():
        raise _error_response(KBErrorCode.DOC_EMPTY_CONTENT, 400)

    if format is not None:
        supported_formats = {"markdown", "text"}
        if format not in supported_formats:
            raise _error_response(KBErrorCode.DOC_UNSUPPORTED_FORMAT, 400, format=format)

    import json
    kwargs = {}
    if title is not None:
        kwargs["title"] = title
    if content is not None:
        kwargs["content"] = content
    if format is not None:
        kwargs["format"] = format
    if category is not None:
        kwargs["category"] = category
    if tags is not None:
        kwargs["tags_json"] = json.loads(tags) if tags else []
    if status is not None:
        kwargs["status"] = status

    result = document_service.update_document(db, doc_id, **kwargs)
    if not result:
        raise _error_response(KBErrorCode.DOC_NOT_FOUND, 404)
    return result


@router.post("/documents/{doc_id}/embed")
async def embed_document(
    doc_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """手动触发文档向量化（PRD §7.8）POST /api/knowledge-base/documents/{id}/embed — data_admin+
    仅当自动嵌入失败时使用，正常创建文档后由 Celery 自动处理。
    """
    _require_role(user, "data_admin")

    # 同步调用（Celery Worker 内部也用此路径）
    result = document_service.chunk_and_embed(db, doc_id)
    if "error" in result:
        raise _error_response(KBErrorCode.EMBEDDING_FAILED, 502)
    return result


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: int,
    hard: bool = Query(False, description="硬删除（仅 admin）"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """删除文档（PRD §7.9 + §9.1）DELETE /api/knowledge-base/documents/{id}
    - hard=false（默认）：软删除（admin 专属，PRD §9.1）
    - hard=true：硬删除（admin 专属），同时清理 kb_embeddings
    """
    _require_role(user, "admin")

    success = document_service.delete_document(db, doc_id, hard=hard)
    if not success:
        raise _error_response(KBErrorCode.DOC_NOT_FOUND, 404)
    return {"message": "文档已删除" if hard else "文档已归档"}


# === 搜索端点 ===

@router.post("/search")
async def search_knowledge(
    q: str,
    top_k: int = Query(10, ge=1, le=20),
    source_types: Optional[str] = None,
    threshold: float = Query(0.50, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """知识库语义搜索（PRD §7.10）POST /api/knowledge-base/search — analyst+
    请求体参数：query, top_k, source_types[], threshold
    """
    _require_role(user, "analyst")

    if not q or not q.strip():
        raise _error_response(KBErrorCode.SEARCH_QUERY_EMPTY, 400)

    import json
    source_type_list = json.loads(source_types) if source_types else None

    # 术语精确匹配
    matched_terms = glossary_service.match_terms(db, q, limit=top_k)

    # 向量相似度检索
    try:
        query_embedding = await embedding_service.embed_text(q)
        vector_results = embedding_service.search(
            db, query_embedding,
            top_k=top_k,
            threshold=threshold,
            source_type=source_type_list[0] if source_type_list and len(source_type_list) == 1 else None,
        )
        # 多 type 过滤在 service 层实现（按 source_type 分组）
        if source_type_list and len(source_type_list) > 1:
            vector_results = [r for r in vector_results if r["source_type"] in source_type_list]
    except RuntimeError:
        raise _error_response(KBErrorCode.VECTOR_SEARCH_UNAVAILABLE, 502)
    except Exception:
        raise _error_response(KBErrorCode.VECTOR_SEARCH_UNAVAILABLE, 502)

    return {
        "results": [_format_search_result(db, r) for r in vector_results],
        "terms": matched_terms,
        "query": q,
    }


@router.post("/rag/enrich")
async def rag_enrich(
    body: RagEnrichRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """RAG 上下文增强（PRD §7.11）POST /api/knowledge-base/rag/enrich — analyst+
    请求体：{ "question": str, "scenario": str }
    """
    _require_role(user, "analyst")

    result = await rag_service.enrich_context(db, body.question, body.scenario)
    return result
