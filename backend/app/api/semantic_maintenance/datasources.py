"""
语义维护 - 数据源语义 API
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel

sys_path = str(Path(__file__).parent.parent.parent.parent.parent / "src")
import sys
sys.path.insert(0, sys_path)

from semantic_maintenance.service import SemanticMaintenanceService
from semantic_maintenance.models import SemanticStatus, SensitivityLevel, SemanticSource
from app.core.dependencies import get_current_user

router = APIRouter()


def _db_path():
    return str(Path(__file__).parent.parent.parent.parent.parent / "data" / "semantic_maintenance.db")


def _sm_service():
    return SemanticMaintenanceService(db_path=_db_path())


def _verify_connection_access(connection_id: int, user: dict) -> None:
    """验证用户有权访问指定连接"""
    import sqlite3
    from ..tableau import _db_path as tableau_db_path
    conn = sqlite3.connect(tableau_db_path())
    cursor = conn.cursor()
    cursor.execute("SELECT owner_id FROM tableau_connections WHERE id = ?", (connection_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="连接不存在")
    if user["role"] != "admin" and row[0] != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问该连接")


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
    tags_json: Optional[str] = None


class UpdateDatasourceSemanticsRequest(BaseModel):
    semantic_name: Optional[str] = None
    semantic_name_zh: Optional[str] = None
    semantic_description: Optional[str] = None
    business_definition: Optional[str] = None
    usage_scenarios: Optional[str] = None
    owner: Optional[str] = None
    steward: Optional[str] = None
    sensitivity_level: Optional[str] = None
    tags_json: Optional[str] = None


# --- Endpoints ---

@router.get("/datasources")
async def list_datasource_semantics(
    request: Request,
    connection_id: int = Query(..., description="Tableau 连接 ID"),
    status: Optional[str] = Query(None, description="语义状态过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    """获取数据源语义列表"""
    user = get_current_user(request)
    _verify_connection_access(connection_id, user)

    sm = _sm_service()
    items, total = sm.list_datasource_semantics(
        connection_id=connection_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/datasources/{ds_id}")
async def get_datasource_semantics(ds_id: int, request: Request):
    """获取数据源语义详情"""
    user = get_current_user(request)
    sm = _sm_service()
    from semantic_maintenance.database import SemanticMaintenanceDatabase
    db = SemanticMaintenanceDatabase(db_path=_db_path())
    ds = db.get_datasource_semantics_by_id(ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="记录不存在")
    _verify_connection_access(ds.connection_id, user)
    return ds.to_dict()


@router.post("/datasources")
async def create_datasource_semantics(req: CreateDatasourceSemanticsRequest, request: Request):
    """创建数据源语义"""
    user = get_current_user(request)
    _verify_connection_access(req.connection_id, user)

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
    return {"item": obj, "message": "创建成功"}


@router.put("/datasources/{ds_id}")
async def update_datasource_semantics(
    ds_id: int,
    req: UpdateDatasourceSemanticsRequest,
    request: Request,
):
    """更新数据源语义"""
    user = get_current_user(request)
    sm = _sm_service()
    db_obj = sm.db.get_datasource_semantics_by_id(ds_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="记录不存在")
    _verify_connection_access(db_obj.connection_id, user)

    if req.sensitivity_level and req.sensitivity_level not in SensitivityLevel.ALL:
        raise HTTPException(status_code=400, detail=f"sensitivity_level 必须是 {SensitivityLevel.ALL} 之一")

    fields = req.model_dump(exclude_unset=True)
    success, result = sm.update_datasource_semantics(ds_id, user_id=user["id"], **fields)
    if not success:
        raise HTTPException(status_code=400, detail=result)
    return {"item": result, "message": "更新成功"}


# --- AI Generation & Versions ---

class GenerateDatasourceAIRequest(BaseModel):
    ds_name: Optional[str] = None
    description: Optional[str] = None
    field_context: Optional[list] = None  # [{field_name, field_caption, role, data_type, formula}]


@router.post("/datasources/{ds_id}/generate-ai")
async def generate_datasource_ai(ds_id: int, req: GenerateDatasourceAIRequest, request: Request):
    """AI 生成数据源语义草稿"""
    user = get_current_user(request)
    sm = _sm_service()
    ds = sm.db.get_datasource_semantics_by_id(ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="记录不存在")
    _verify_connection_access(ds.connection_id, user)

    success, result = sm.generate_ai_draft_datasource(
        ds_id=ds_id,
        user_id=user["id"],
        ds_name=req.ds_name,
        description=req.description,
        field_context=req.field_context,
    )
    if not success:
        raise HTTPException(status_code=400, detail=result)
    return {"item": result, "message": "AI 语义草稿已生成"}


@router.get("/datasources/{ds_id}/versions")
async def get_datasource_versions(ds_id: int, request: Request):
    """获取数据源语义版本历史"""
    user = get_current_user(request)
    sm = _sm_service()
    ds = sm.db.get_datasource_semantics_by_id(ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="记录不存在")
    _verify_connection_access(ds.connection_id, user)

    versions = sm.get_datasource_semantic_history(ds_id)
    return {"versions": versions}


@router.post("/datasources/{ds_id}/rollback/{version_id}")
async def rollback_datasource(ds_id: int, version_id: int, request: Request):
    """回滚数据源语义到指定版本"""
    user = get_current_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要 admin 权限")
    sm = _sm_service()
    ds = sm.db.get_datasource_semantics_by_id(ds_id)
    if not ds:
        raise HTTPException(status_code=404, detail="记录不存在")
    _verify_connection_access(ds.connection_id, user)

    success, err = sm.rollback_datasource_semantic(ds_id, version_id, user_id=user["id"])
    if not success:
        raise HTTPException(status_code=400, detail=err)
    updated = sm.db.get_datasource_semantics_by_id(ds_id)
    return {"item": updated.to_dict(), "message": f"已回滚到版本 {version_id}"}
