"""
语义维护 - 数据源语义 API
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

# 导入中央数据库依赖和统一的权限验证函数
from app.core.database import get_db
from app.utils.auth import verify_connection_access
from app.core.dependencies import get_current_user, require_roles

# 导入语义维护服务和模型
from services.semantic_maintenance.service import SemanticMaintenanceService
from services.semantic_maintenance.models import SemanticStatus, SensitivityLevel, SemanticSource
from services.semantic_maintenance.database import SemanticMaintenanceDatabase # 导入 SemanticMaintenanceDatabase

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

class CreateDatasourceSemanticsRequest(BaseModel):
    connection_id: int
    tableau_datasource_id: str
    semantic_name: Optional[str] = None
    semantic_name_zh: Optional[str] = None
    semantic_description: Optional[str] = None
    business_definition: Optional[str] = None
    usage_scenarios: Optional[str] = None
    owner: Optional[str] = None
    steward: Optional[str] = None
    sensitivity_level: Optional[str] = None
    tags_json: Optional[list] = None # JSONB 字段直接是 list


class UpdateDatasourceSemanticsRequest(BaseModel):
    semantic_name: Optional[str] = None
    semantic_name_zh: Optional[str] = None
    semantic_description: Optional[str] = None
    business_definition: Optional[str] = None
    usage_scenarios: Optional[str] = None
    owner: Optional[str] = None
    steward: Optional[str] = None
    sensitivity_level: Optional[str] = None
    tags_json: Optional[list] = None # JSONB 字段直接是 list


# --- Endpoints ---

@router.get("/datasources")
async def list_datasource_semantics(
    request: Request,
    connection_id: int = Query(..., description="Tableau 连接 ID"),
    status: Optional[str] = Query(None, description="语义状态过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db) # 注入 db
):
    """获取数据源语义列表"""
    user = get_current_user(request, db) # 传递 db
    verify_connection_access(connection_id, user, db) # 使用统一的权限验证函数

    sm = _sm_service()
    items, total = sm.list_datasource_semantics(
        connection_id=connection_id,
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


@router.get("/datasources/{ds_id}")
async def get_datasource_semantics(ds_id: int, request: Request, db: Session = Depends(get_db)):
    """获取数据源语义详情"""
    user = get_current_user(request, db) # 传递 db
    sm = _sm_service()
    # db = SemanticMaintenanceDatabase(db_path=_db_path()) # 不再需要 db_path
    ds = sm.db.get_datasource_semantics_by_id(ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="记录不存在")
    verify_connection_access(ds.connection_id, user, db) # 使用统一的权限验证函数
    return ds.to_dict()


@router.post("/datasources")
async def create_datasource_semantics(req: CreateDatasourceSemanticsRequest, request: Request, db: Session = Depends(get_db)):
    """创建数据源语义"""
    user = get_current_user(request, db) # 传递 db
    verify_connection_access(req.connection_id, user, db) # 使用统一的权限验证函数

    if req.sensitivity_level and req.sensitivity_level not in SensitivityLevel.ALL:
        raise HTTPException(status_code=400, detail=f"sensitivity_level 必须是 {SensitivityLevel.ALL} 之一")

    sm = _sm_service()
    initial = req.model_dump(exclude_unset=True)
    # 移除 connection_id 和 tableau_datasource_id，它们作为主键
    data = {k: v for k, v in initial.items() if k not in ("connection_id", "tableau_datasource_id")}
    data["source"] = SemanticSource.MANUAL
    obj = sm.get_or_create_datasource_semantics(
        connection_id=req.connection_id,
        tableau_datasource_id=req.tableau_datasource_id,
        user_id=user["id"],
        initial_data=data,
    )
    return {"item": obj.to_dict(), "message": "创建成功"} # 确保返回 dict


@router.put("/datasources/{ds_id}")
async def update_datasource_semantics(
    ds_id: int,
    req: UpdateDatasourceSemanticsRequest,
    request: Request,
    db: Session = Depends(get_db) # 注入 db
):
    """更新数据源语义"""
    user = get_current_user(request, db) # 传递 db
    sm = _sm_service()
    db_obj = sm.db.get_datasource_semantics_by_id(ds_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="记录不存在")
    verify_connection_access(db_obj.connection_id, user, db) # 使用统一的权限验证函数

    if req.sensitivity_level and req.sensitivity_level not in SensitivityLevel.ALL:
        raise HTTPException(status_code=400, detail=f"sensitivity_level 必须是 {SensitivityLevel.ALL} 之一")

    fields = req.model_dump(exclude_unset=True)
    success, result = sm.update_datasource_semantics(ds_id, user_id=user["id"], **fields)
    if not success:
        raise HTTPException(status_code=400, detail=result)
    return {"item": result.to_dict(), "message": "更新成功"} # 确保返回 dict


# --- AI Generation & Versions ---

class GenerateDatasourceAIRequest(BaseModel):
    ds_name: Optional[str] = None
    description: Optional[str] = None
    field_context: Optional[list] = None  # [{field_name, field_caption, role, data_type, formula}]


@router.post("/datasources/{ds_id}/generate-ai")
async def generate_datasource_ai(ds_id: int, req: GenerateDatasourceAIRequest, request: Request, db: Session = Depends(get_db)):
    """AI 生成数据源语义草稿"""
    user = get_current_user(request, db) # 传递 db
    sm = _sm_service()
    ds = sm.db.get_datasource_semantics_by_id(ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="记录不存在")
    verify_connection_access(ds.connection_id, user, db) # 使用统一的权限验证函数

    success, result = sm.generate_ai_draft_datasource(
        ds_id=ds_id,
        user_id=user["id"],
        ds_name=req.ds_name,
        description=req.description,
        field_context=req.field_context,
    )
    if not success:
        raise HTTPException(status_code=400, detail=result)
    return {"item": result.to_dict(), "message": "AI 语义草稿已生成"} # 确保返回 dict


@router.get("/datasources/{ds_id}/versions")
async def get_datasource_versions(ds_id: int, request: Request, db: Session = Depends(get_db)):
    """获取数据源语义版本历史"""
    user = get_current_user(request, db) # 传递 db
    sm = _sm_service()
    ds = sm.db.get_datasource_semantics_by_id(ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="记录不存在")
    verify_connection_access(ds.connection_id, user, db) # 使用统一的权限验证函数

    versions = sm.get_datasource_semantic_history(ds_id)
    return {"versions": [v.to_dict() for v in versions]} # 确保返回 dict


@router.post("/datasources/{ds_id}/rollback/{version_id}")
async def rollback_datasource(ds_id: int, version_id: int, request: Request, db: Session = Depends(get_db)):
    """回滚数据源语义到指定版本"""
    user = get_current_user(request, db) # 传递 db
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要 admin 权限")
    sm = _sm_service()
    ds = sm.db.get_datasource_semantics_by_id(ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="记录不存在")
    verify_connection_access(ds.connection_id, user, db) # 使用统一的权限验证函数

    success, err = sm.rollback_datasource_semantic(ds_id, version_id, user_id=user["id"])
    if not success:
        raise HTTPException(status_code=400, detail=err)
    updated = sm.db.get_datasource_semantics_by_id(ds_id)
    return {"item": updated.to_dict(), "message": f"已回滚到版本 {version_id}"}

