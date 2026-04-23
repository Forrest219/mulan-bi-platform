"""语义维护 - 字段语义 API
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# 导入中央数据库依赖和统一的权限验证函数
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.utils.auth import verify_connection_access
from services.semantic_maintenance.models import SemanticSource, SensitivityLevel

# 导入语义维护服务和模型
from services.semantic_maintenance.service import SemanticMaintenanceService

router = APIRouter()


# _db_path 不再需要
# def _db_path():
#     return str(Path(__file__).parent.parent.parent.parent.parent / "data" / "semantic_maintenance.db")


def _sm_service():
    # SemanticMaintenanceService 内部会实例化 SemanticMaintenanceDatabase，不再需要 db_path
    return SemanticMaintenanceService()


# _verify_connection_access 已经提取到 app.utils.auth.py
# def _verify_connection_access(connection_id: int, user: dict) -> None:
#     """验证用户有权访问指定连接"""
#     import sqlite3
#     from ..tableau import _db_path as tableau_db_path
#     conn = sqlite3.connect(tableau_db_path())
#     cursor = conn.cursor()
#     cursor.execute("SELECT owner_id FROM tableau_connections WHERE id = ?", (connection_id,))
#     row = cursor.fetchone()
#     conn.close()
#     if not row:
#         raise HTTPException(status_code=404, detail="连接不存在")
#     if user["role"] != "admin" and row[0] != user["id"]:
#         raise HTTPException(status_code=403, detail="无权访问该连接")


# --- Pydantic Schemas ---

class CreateFieldSemanticsRequest(BaseModel):
    """创建字段语义请求模型"""

    connection_id: int
    tableau_field_id: str
    field_registry_id: Optional[int] = None  # tableau_datasource_fields.id
    semantic_name: Optional[str] = None
    semantic_name_zh: Optional[str] = None
    semantic_definition: Optional[str] = None
    metric_definition: Optional[str] = None
    dimension_definition: Optional[str] = None
    unit: Optional[str] = None
    enum_desc_json: Optional[dict] = None # JSONB 字段直接是 dict
    tags_json: Optional[list] = None # JSONB 字段直接是 list
    synonyms_json: Optional[list] = None # JSONB 字段直接是 list
    sensitivity_level: Optional[str] = None
    is_core_field: Optional[bool] = None


class UpdateFieldSemanticsRequest(BaseModel):
    """更新字段语义请求模型"""

    semantic_name: Optional[str] = None
    semantic_name_zh: Optional[str] = None
    semantic_definition: Optional[str] = None
    metric_definition: Optional[str] = None
    dimension_definition: Optional[str] = None
    unit: Optional[str] = None
    enum_desc_json: Optional[dict] = None # JSONB 字段直接是 dict
    tags_json: Optional[list] = None # JSONB 字段直接是 list
    synonyms_json: Optional[list] = None # JSONB 字段直接是 list
    sensitivity_level: Optional[str] = None
    is_core_field: Optional[bool] = None


# --- Endpoints ---

@router.get("/fields")
async def list_field_semantics(
    request: Request,
    connection_id: int = Query(..., description="Tableau 连接 ID"),
    ds_id: Optional[int] = Query(None, description="字段注册 ID (tableau_datasource_fields.id)"),
    status: Optional[str] = Query(None, description="语义状态过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db) # 注入 db
):
    """获取字段语义列表"""
    user = get_current_user(request, db) # 传递 db
    verify_connection_access(connection_id, user, db) # 使用统一的权限验证函数

    sm = _sm_service()
    items, total = sm.list_field_semantics(
        connection_id=connection_id,
        ds_id=ds_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [item.to_dict() for item in items], # 确保返回 dict
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/fields/{field_id}")
async def get_field_semantics(field_id: int, request: Request, db: Session = Depends(get_db)):
    """获取字段语义详情"""
    user = get_current_user(request, db) # 传递 db
    sm = _sm_service()
    field = sm.db.get_field_semantics_by_id(field_id)
    if not field:
        raise HTTPException(status_code=404, detail="记录不存在")
    verify_connection_access(field.connection_id, user, db) # 使用统一的权限验证函数
    return field.to_dict()


@router.post("/fields")
async def create_field_semantics(req: CreateFieldSemanticsRequest, request: Request, db: Session = Depends(get_db)):
    """创建字段语义"""
    user = get_current_user(request, db) # 传递 db
    verify_connection_access(req.connection_id, user, db) # 使用统一的权限验证函数

    if req.sensitivity_level and req.sensitivity_level not in SensitivityLevel.ALL:
        raise HTTPException(status_code=400, detail=f"sensitivity_level 必须是 {SensitivityLevel.ALL} 之一")

    sm = _sm_service()
    data = req.model_dump(exclude_unset=True)
    pk_fields = {"connection_id", "tableau_field_id", "field_registry_id"}
    initial = {k: v for k, v in data.items() if k not in pk_fields}
    initial["source"] = SemanticSource.MANUAL
    obj = sm.get_or_create_field_semantics(
        connection_id=req.connection_id,
        tableau_field_id=req.tableau_field_id,
        field_registry_id=req.field_registry_id,
        user_id=user["id"],
        initial_data=initial,
    )
    return {"item": obj.to_dict(), "message": "创建成功"} # 确保返回 dict


@router.put("/fields/{field_id}")
async def update_field_semantics(
    field_id: int,
    req: UpdateFieldSemanticsRequest,
    request: Request,
    db: Session = Depends(get_db) # 注入 db
):
    """更新字段语义"""
    user = get_current_user(request, db) # 传递 db
    sm = _sm_service()
    field = sm.db.get_field_semantics_by_id(field_id)
    if not field:
        raise HTTPException(status_code=404, detail="记录不存在")
    verify_connection_access(field.connection_id, user, db) # 使用统一的权限验证函数

    if req.sensitivity_level and req.sensitivity_level not in SensitivityLevel.ALL:
        raise HTTPException(status_code=400, detail=f"sensitivity_level 必须是 {SensitivityLevel.ALL} 之一")

    fields = req.model_dump(exclude_unset=True)
    success, result = sm.update_field_semantics(field_id, user_id=user["id"], **fields)
    if not success:
        raise HTTPException(status_code=400, detail=result)
    return {"item": result.to_dict(), "message": "更新成功"} # 确保返回 dict


@router.post("/fields/{field_id}/submit-review")
async def submit_field_for_review(field_id: int, request: Request, db: Session = Depends(get_db)):
    """提交字段语义审核"""
    user = get_current_user(request, db) # 传递 db
    sm = _sm_service()
    field = sm.db.get_field_semantics_by_id(field_id)
    if not field:
        raise HTTPException(status_code=404, detail="记录不存在")
    verify_connection_access(field.connection_id, user, db) # 使用统一的权限验证函数

    success, err = sm.submit_field_for_review(field_id, user_id=user["id"])
    if not success:
        raise HTTPException(status_code=400, detail=err)
    updated = sm.db.get_field_semantics_by_id(field_id)
    return {"item": updated.to_dict(), "message": "已提交审核"}


@router.post("/fields/{field_id}/approve")
async def approve_field(field_id: int, request: Request, db: Session = Depends(get_db)):
    """审核通过字段语义"""
    user = get_current_user(request, db) # 传递 db
    if user["role"] not in ("admin", "reviewer"):
        raise HTTPException(status_code=403, detail="需要 reviewer 或 admin 权限")
    sm = _sm_service()
    field = sm.db.get_field_semantics_by_id(field_id)
    if not field:
        raise HTTPException(status_code=404, detail="记录不存在")
    verify_connection_access(field.connection_id, user, db) # 使用统一的权限验证函数

    success, err = sm.approve_field(field_id, user_id=user["id"])
    if not success:
        raise HTTPException(status_code=400, detail=err)
    updated = sm.db.get_field_semantics_by_id(field_id)
    return {"item": updated.to_dict(), "message": "审核通过"}


@router.post("/fields/{field_id}/reject")
async def reject_field(field_id: int, request: Request, db: Session = Depends(get_db)):
    """驳回字段语义"""
    user = get_current_user(request, db) # 传递 db
    if user["role"] not in ("admin", "reviewer"):
        raise HTTPException(status_code=403, detail="需要 reviewer 或 admin 权限")
    sm = _sm_service()
    field = sm.db.get_field_semantics_by_id(field_id)
    if not field:
        raise HTTPException(status_code=404, detail="记录不存在")
    verify_connection_access(field.connection_id, user, db) # 使用统一的权限验证函数

    success, err = sm.reject_field(field_id, user_id=user["id"])
    if not success:
        raise HTTPException(status_code=400, detail=err)
    updated = sm.db.get_field_semantics_by_id(field_id)
    return {"item": updated.to_dict(), "message": "已驳回"}


@router.get("/fields/{field_id}/versions")
async def get_field_versions(field_id: int, request: Request, db: Session = Depends(get_db)):
    """获取字段语义版本历史"""
    user = get_current_user(request, db) # 传递 db
    sm = _sm_service()
    field = sm.db.get_field_semantics_by_id(field_id)
    if not field:
        raise HTTPException(status_code=404, detail="记录不存在")
    verify_connection_access(field.connection_id, user, db) # 使用统一的权限验证函数

    versions = sm.get_field_semantic_history(field_id)
    return {"versions": [v.to_dict() for v in versions]} # 确保返回 dict


@router.post("/fields/{field_id}/rollback/{version_id}")
async def rollback_field(field_id: int, version_id: int, request: Request, db: Session = Depends(get_db)):
    """回滚字段语义到指定版本"""
    user = get_current_user(request, db) # 传递 db
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要 admin 权限")
    sm = _sm_service()
    field = sm.db.get_field_semantics_by_id(field_id)
    if not field:
        raise HTTPException(status_code=404, detail="记录不存在")
    verify_connection_access(field.connection_id, user, db) # 使用统一的权限验证函数

    success, err = sm.rollback_field_semantic(field_id, version_id, user_id=user["id"])
    if not success:
        raise HTTPException(status_code=400, detail=err)
    updated = sm.db.get_field_semantics_by_id(field_id)
    return {"item": updated.to_dict(), "message": f"已回滚到版本 {version_id}"}


# --- AI Generation ---

class GenerateFieldAIRequest(BaseModel):
    field_name: Optional[str] = None
    data_type: Optional[str] = None
    role: Optional[str] = None  # dimension / measure
    formula: Optional[str] = None
    enum_values: Optional[list[str]] = None


@router.post("/fields/{field_id}/generate-ai")
async def generate_field_ai(field_id: int, req: GenerateFieldAIRequest, request: Request, db: Session = Depends(get_db)):
    """AI 生成字段语义草稿"""
    user = get_current_user(request, db) # 传递 db
    sm = _sm_service()
    field = sm.db.get_field_semantics_by_id(field_id)
    if not field:
        raise HTTPException(status_code=404, detail="记录不存在")
    verify_connection_access(field.connection_id, user, db) # 使用统一的权限验证函数

    success, result = sm.generate_ai_draft_field(
        field_id=field_id,
        user_id=user["id"],
        field_name=req.field_name,
        data_type=req.data_type,
        role=req.role,
        formula=req.formula,
        enum_values=req.enum_values,
    )
    if not success:
        raise HTTPException(status_code=400, detail=result)
    return {"item": result.to_dict(), "message": "AI 语义草稿已生成"} # 确保返回 dict


# --- 向量字段解析（Spec 26 §P0） ---

class ResolveFieldRequest(BaseModel):
    """向量字段解析请求模型"""
    fuzzy_name: str
    datasource_luid: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)


@router.post("/fields/resolve")
async def resolve_field_semantics(
    req: ResolveFieldRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    向量语义字段解析（Spec 26 §P0 — /fields/resolve）。

    将自然语言模糊字段名映射为语义层候选字段列表。
    基于 embedding + HNSW 向量相似度搜索，返回带置信度的候选列表。

    - 连接权限由 connection_id 验证
    - 返回字段角色（dimension / measure）和数据类型（string / integer / datetime 等）
    - 若向量尚未生成（命中 0 条），返回空列表（前端应降级为 LIKE 查询）
    """
    user = get_current_user(request, db)

    # connection_id 放 query string（防 body 篡改）
    try:
        connection_id: int = int(request.query_params["connection_id"])
    except KeyError:
        raise HTTPException(status_code=422, detail="缺少 required query param: connection_id")
    except ValueError:
        raise HTTPException(status_code=422, detail="connection_id 必须是整数")

    verify_connection_access(connection_id, user, db)

    sm = _sm_service()
    candidates, err = sm.resolve_field_by_embedding(
        connection_id=connection_id,
        fuzzy_name=req.fuzzy_name,
        datasource_luid=req.datasource_luid,
        top_k=req.top_k,
    )

    return {"candidates": candidates}

