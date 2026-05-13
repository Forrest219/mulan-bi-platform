"""
Skills API — 技能中心 FastAPI 路由

Spec: docs/specs/agents_skills.md §4
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_roles

import services.skills.service as skill_svc

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic Request / Response Models
# ---------------------------------------------------------------------------


class InitialVersionBody(BaseModel):
    description: str
    input_schema: Dict[str, Any]
    endpoint_type: str = "static"
    code_ref: Optional[str] = None
    change_notes: Optional[str] = None


class CreateSkillBody(BaseModel):
    skill_key: str
    name: str
    description: Optional[str] = None
    category: str = "general"
    initial_version: InitialVersionBody


class PatchSkillBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    is_enabled: Optional[bool] = None


class PublishVersionBody(BaseModel):
    description: str
    input_schema: Dict[str, Any]
    endpoint_type: str = "static"
    code_ref: Optional[str] = None
    change_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# 辅助函数：统一错误码 → HTTP 异常映射
# ---------------------------------------------------------------------------

_ERROR_CODE_TO_HTTP = {
    "SKILLS_001": 409,
    "SKILLS_002": 404,
    "SKILLS_003": 400,
    "SKILLS_004": 404,
    "SKILLS_005": 400,
    "SKILLS_006": 400,
}


def _raise_from_service_error(exc: Exception) -> None:
    """将 service 层抛出的 ValueError / LookupError 转换为 HTTPException。

    Service 层错误格式："{CODE}:{message}"
    """
    msg = str(exc)
    for code, status in _ERROR_CODE_TO_HTTP.items():
        if msg.startswith(code + ":"):
            human_msg = msg[len(code) + 1:]
            raise HTTPException(
                status_code=status,
                detail={"code": code, "message": human_msg},
            )
    # 未知错误，500
    logger.exception("Skills service unexpected error: %s", exc)
    raise HTTPException(status_code=500, detail={"code": "SYS_001", "message": "服务器内部错误"})


# ---------------------------------------------------------------------------
# 4.1  POST /api/skills — 创建新技能（admin only）
# ---------------------------------------------------------------------------


@router.post("/api/skills", status_code=201)
def create_skill(
    body: CreateSkillBody,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles(["admin"])),
):
    """创建新技能（含初始 v1 版本）。

    Spec §4.1
    """
    try:
        result = skill_svc.create_skill(
            db,
            skill_key=body.skill_key,
            name=body.name,
            description=body.description,
            category=body.category,
            initial_version=body.initial_version.dict(),
            created_by_id=current_user.get("id"),
        )
        db.commit()
        return result
    except (ValueError, LookupError) as e:
        db.rollback()
        _raise_from_service_error(e)
    except Exception as e:
        db.rollback()
        logger.exception("create_skill unexpected error: %s", e)
        raise HTTPException(status_code=500, detail={"code": "SYS_001", "message": "服务器内部错误"})


# ---------------------------------------------------------------------------
# 4.0  GET /api/skills/registered-tools — 静态注册工具元数据（admin / data_admin）
# 注意：此路由必须在 /{id} 之前注册，防止 FastAPI 路由歧义
# ---------------------------------------------------------------------------


@router.get("/api/skills/registered-tools")
def list_registered_tools(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """返回真实 ToolRegistry 静态注册工具元数据。

    Spec §4.0
    """
    return skill_svc.list_registered_tools(db)


# ---------------------------------------------------------------------------
# 4.5  GET /api/skills — 技能列表（admin / data_admin）
# ---------------------------------------------------------------------------


@router.get("/api/skills")
def list_skills(
    category: Optional[str] = Query(None),
    is_enabled: Optional[bool] = Query(None),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """技能列表（分页 + 筛选）。

    Spec §4.5 GET /api/skills
    """
    return skill_svc.list_skills(
        db,
        category=category,
        is_enabled=is_enabled,
        q=q,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# 4.4  GET /api/skills/dispatch — LLM 调用批量查询
# 注意：此路由必须在 /{id} 之前注册，防止 FastAPI 路由歧义
# ---------------------------------------------------------------------------


@router.get("/api/skills/dispatch")
def get_dispatch(
    category: Optional[str] = Query(None),
    skill_keys: Optional[str] = Query(None, description="逗号分隔的 skill_key 列表"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """供 LLM 调用时批量查询当前生效的技能定义。

    Spec §4.4
    """
    return skill_svc.get_dispatch(db, category=category, skill_keys=skill_keys)


# ---------------------------------------------------------------------------
# 4.5  GET /api/skills/{id} — 技能详情（admin / data_admin）
# ---------------------------------------------------------------------------


@router.get("/api/skills/{skill_id}")
def get_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """技能详情（含所有版本历史）。

    Spec §4.5 GET /api/skills/{id}
    """
    try:
        return skill_svc.get_skill(db, skill_id=skill_id)
    except LookupError as e:
        _raise_from_service_error(e)


# ---------------------------------------------------------------------------
# 4.5  PATCH /api/skills/{id} — 更新技能基本信息（admin only）
# ---------------------------------------------------------------------------


@router.patch("/api/skills/{skill_id}")
def patch_skill(
    skill_id: str,
    body: PatchSkillBody,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles(["admin"])),
):
    """更新技能基本信息（name/description/category/is_enabled）。

    Spec §4.5 PATCH /api/skills/{id}
    """
    try:
        result = skill_svc.patch_skill(
            db,
            skill_id=skill_id,
            name=body.name,
            description=body.description,
            category=body.category,
            is_enabled=body.is_enabled,
            updated_by_id=current_user.get("id"),
        )
        db.commit()
        return result
    except LookupError as e:
        db.rollback()
        _raise_from_service_error(e)
    except Exception as e:
        db.rollback()
        logger.exception("patch_skill unexpected error: %s", e)
        raise HTTPException(status_code=500, detail={"code": "SYS_001", "message": "服务器内部错误"})


# ---------------------------------------------------------------------------
# 4.2  POST /api/skills/{id}/versions — 发布新版本（admin only）
# ---------------------------------------------------------------------------


@router.post("/api/skills/{skill_id}/versions", status_code=201)
def publish_version(
    skill_id: str,
    body: PublishVersionBody,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles(["admin"])),
):
    """发布新版本（自动将旧版本设为非活跃）。

    Spec §4.2
    """
    try:
        result = skill_svc.publish_version(
            db,
            skill_id=skill_id,
            description=body.description,
            input_schema=body.input_schema,
            endpoint_type=body.endpoint_type,
            code_ref=body.code_ref,
            change_notes=body.change_notes,
            created_by_id=current_user.get("id"),
        )
        db.commit()
        return result
    except (ValueError, LookupError) as e:
        db.rollback()
        _raise_from_service_error(e)
    except Exception as e:
        db.rollback()
        logger.exception("publish_version unexpected error: %s", e)
        raise HTTPException(status_code=500, detail={"code": "SYS_001", "message": "服务器内部错误"})


# ---------------------------------------------------------------------------
# 4.3  POST /api/skills/{id}/rollback/{version_id} — 回滚到指定版本（admin only）
# ---------------------------------------------------------------------------


@router.post("/api/skills/{skill_id}/rollback/{version_id}")
def rollback_version(
    skill_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles(["admin"])),
):
    """回滚到指定版本（重新激活历史版本，不创建新版本行）。

    Spec §4.3
    """
    try:
        result = skill_svc.rollback_version(
            db,
            skill_id=skill_id,
            version_id=version_id,
            user_id=current_user.get("id"),
        )
        db.commit()
        return result
    except LookupError as e:
        db.rollback()
        _raise_from_service_error(e)
    except Exception as e:
        db.rollback()
        logger.exception("rollback_version unexpected error: %s", e)
        raise HTTPException(status_code=500, detail={"code": "SYS_001", "message": "服务器内部错误"})


# ---------------------------------------------------------------------------
# 4.5  GET /api/skills/{id}/versions/{v_id}/diff/{v_id2} — Schema Diff
# ---------------------------------------------------------------------------


@router.get("/api/skills/{skill_id}/versions/{v_id}/diff/{v_id2}")
def get_diff(
    skill_id: str,
    v_id: str,
    v_id2: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_roles(["admin", "data_admin"])),
):
    """对比两个版本的 input_schema 差异（RFC 6902 JSON Patch）。

    Spec §4.5 GET /api/skills/{id}/versions/{v_id}/diff/{v_id2}
    """
    try:
        return skill_svc.get_diff(db, skill_id=skill_id, v_id1=v_id, v_id2=v_id2)
    except LookupError as e:
        _raise_from_service_error(e)
