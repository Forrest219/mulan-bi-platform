"""知识库 API（管理员专用，PRD §8）"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.database import get_db
from services.knowledge_base.glossary_service import glossary_service
from services.knowledge_base.document_service import document_service
from services.knowledge_base.embedding_service import embedding_service
from services.knowledge_base.rag_service import rag_service

router = APIRouter()


@router.get("/glossary")
async def list_glossary(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """术语列表（PRD §8.1）GET /api/kb/glossary"""
    user = get_current_user(request=None, db=db)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问知识库")

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
):
    """创建术语（PRD §8.2）POST /api/kb/glossary"""
    user = get_current_user(request=None, db=db)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问知识库")

    import json
    synonyms_list = json.loads(synonyms) if synonyms else []
    related_fields_list = json.loads(related_fields) if related_fields else []

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
    return glossary.to_dict()


@router.get("/glossary/{glossary_id}")
async def get_glossary(glossary_id: int, db: Session = Depends(get_db)):
    """术语详情（PRD §8.3）GET /api/kb/glossary/{id}"""
    user = get_current_user(request=None, db=db)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问知识库")

    result = glossary_service.get_term(db, glossary_id)
    if not result:
        raise HTTPException(status_code=404, detail="术语不存在")
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
):
    """更新术语（PRD §8.4）PUT /api/kb/glossary/{id}"""
    user = get_current_user(request=None, db=db)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问知识库")

    import json
    kwargs = {}
    if term is not None:
        kwargs["term"] = term
    if canonical_term is not None:
        kwargs["canonical_term"] = canonical_term
    if definition is not None:
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
        raise HTTPException(status_code=404, detail="术语不存在")
    return result


@router.delete("/glossary/{glossary_id}")
async def delete_glossary(glossary_id: int, db: Session = Depends(get_db)):
    """删除术语（PRD §8.5）DELETE /api/kb/glossary/{id}"""
    user = get_current_user(request=None, db=db)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问知识库")

    success = glossary_service.deprecate_term(db, glossary_id)
    if not success:
        raise HTTPException(status_code=404, detail="术语不存在")
    return {"message": "术语已标记为 deprecated"}


@router.get("/documents")
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """文档列表（PRD §8.6）GET /api/kb/documents"""
    user = get_current_user(request=None, db=db)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问知识库")

    return document_service.list_documents(db, page=page, page_size=page_size, category=category)


@router.post("/documents")
async def create_document(
    title: str,
    content: str,
    format: str = "markdown",
    category: str = "general",
    tags: str = "",
    db: Session = Depends(get_db),
):
    """创建文档（PRD §8.7）POST /api/kb/documents"""
    user = get_current_user(request=None, db=db)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问知识库")

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
    return doc.to_dict()


@router.post("/documents/{doc_id}/embed")
async def embed_document(doc_id: int, db: Session = Depends(get_db)):
    """文档向量化（PRD §8.8）POST /api/kb/documents/{id}/embed"""
    user = get_current_user(request=None, db=db)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问知识库")

    result = document_service.chunk_and_embed(db, doc_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: int, db: Session = Depends(get_db)):
    """删除文档（PRD §8.9）DELETE /api/kb/documents/{id}"""
    user = get_current_user(request=None, db=db)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问知识库")

    success = document_service.delete_document(db, doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"message": "文档已删除"}


@router.get("/search")
async def search_knowledge(
    q: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=20),
    source_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """知识检索（PRD §8.10）GET /api/kb/search?q=...&top_k=5"""
    user = get_current_user(request=None, db=db)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问知识库")

    # 1. 术语精确匹配
    matched_terms = glossary_service.match_terms(db, q, limit=top_k)

    # 2. 向量相似度检索
    try:
        query_embedding = await embedding_service.embed_text(q)
        vector_results = embedding_service.search(
            db, query_embedding, top_k=top_k, source_type=source_type
        )
    except Exception as e:
        vector_results = []

    return {
        "terms": matched_terms,
        "vectors": vector_results,
        "query": q,
    }


@router.post("/rag/enrich")
async def rag_enrich(
    question: str,
    scenario: str = "default",
    db: Session = Depends(get_db),
):
    """RAG 上下文增强（PRD §8.11）POST /api/kb/rag/enrich"""
    user = get_current_user(request=None, db=db)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问知识库")

    result = await rag_service.enrich_context(db, question, scenario)
    return result
