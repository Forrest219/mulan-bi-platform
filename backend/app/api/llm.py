"""LLM 管理 API"""

import time
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin, get_current_user
from services.llm.models import LLMConfigDatabase, LLMConfig
from services.llm.service import _decrypt, _encrypt, llm_service

router = APIRouter()


class LLMConfigRequest(BaseModel):
    """LLM 配置请求模型（单配置，兼容旧接口）"""

    provider: str = "openai"
    base_url: str = "https://api.openai.com/v1"
    api_key: str
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 1024
    is_active: bool = True


class LLMConfigCreateRequest(BaseModel):
    """多配置创建请求"""

    provider: str = "openai"
    base_url: str = Field(default="https://api.openai.com/v1", min_length=1)
    api_key: str = Field(..., min_length=1, description="API Key 不能为空")
    model: str = Field(default="gpt-4o-mini", min_length=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1, le=131072)
    is_active: bool = True
    purpose: str = "default"
    display_name: Optional[str] = Field(default=None, max_length=100)
    priority: int = 0


class LLMConfigUpdateRequest(BaseModel):
    """多配置更新请求（api_key 为空字符串时不更新）"""

    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=131072)
    is_active: Optional[bool] = None
    purpose: Optional[str] = None
    display_name: Optional[str] = Field(default=None, max_length=100)
    priority: Optional[int] = None


class LLMTestRequest(BaseModel):
    """LLM 测试请求模型

    支持两种模式：
    1. 临时测试（新建态）：传入 base_url / api_key / model，不依赖 DB 记录
    2. 已保存配置测试：不传这三个字段，从 DB 取 purpose=default 的配置
    """

    prompt: str = "Say OK in one word"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    config_id: Optional[int] = None


class ActiveToggleRequest(BaseModel):
    """启用/禁用配置请求体"""

    is_active: bool


@router.get("/config")
async def get_llm_config(request: Request):
    """获取 LLM 配置（不返回 api_key 明文）"""
    get_current_admin(request)
    db = LLMConfigDatabase()
    config = db.get_config()
    if not config:
        return {"config": None, "message": "未配置 LLM"}
    return {"config": config.to_dict()}


@router.post("/config")
async def save_llm_config(req: LLMConfigRequest, request: Request):
    """创建/更新 LLM 配置（仅 admin）"""
    user = get_current_admin(request)

    encrypted_key = _encrypt(req.api_key)
    db = LLMConfigDatabase()
    db.save_config(
        provider=req.provider,
        base_url=req.base_url,
        api_key_encrypted=encrypted_key,
        model=req.model,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        is_active=req.is_active,
        purpose="default",
    )

    try:
        from services.logs import logger
        logger.log_operation(
            operation_type="llm_config_update",
            target="llm_config",
            status="success",
            operator=user["username"],
            detail=f"更新 LLM 配置: provider={req.provider}, model={req.model}"
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("日志记录失败: %s", e)

    return {"message": "LLM 配置保存成功"}


@router.post("/config/test")
async def test_llm_connection(req: LLMTestRequest, request: Request):
    """测试 LLM 连接

    - 若请求体携带 base_url / api_key / model，则使用这些临时参数进行 ad-hoc 测试（不写 DB）。
    - 否则使用 DB 中 purpose=default 的活跃配置。
    """
    get_current_admin(request)

    if req.base_url and req.api_key and req.model:
        # 情况 1：ad-hoc 临时测试（新建态传了完整参数）
        result = await llm_service.test_connection_adhoc(
            base_url=req.base_url,
            api_key=req.api_key,
            model=req.model,
            test_prompt=req.prompt,
            provider=req.provider or "openai",
        )
    else:
        # 情况 2：按 config_id 测试特定保存的配置；情况 3：取 default 活跃配置
        db_helper = LLMConfigDatabase()
        session = db_helper.get_session()
        try:
            if req.config_id:
                cfg = session.query(LLMConfig).filter(LLMConfig.id == req.config_id).first()
            else:
                cfg = session.query(LLMConfig).filter(
                    LLMConfig.is_active == True
                ).order_by(LLMConfig.priority.desc()).first()

            if not cfg:
                return {"success": False, "message": "未找到配置"}

            api_key = _decrypt(cfg.api_key_encrypted)
            result = await llm_service.test_connection_adhoc(
                base_url=cfg.base_url,
                api_key=api_key,
                model=cfg.model,
                test_prompt=req.prompt,
                provider=cfg.provider,
            )
        finally:
            session.close()
    return result


@router.delete("/config")
async def delete_llm_config(request: Request):
    """删除 LLM 配置（已废弃，请使用 DELETE /api/llm/configs/{id}）"""
    raise HTTPException(status_code=410, detail="此接口已废弃，请使用 DELETE /api/llm/configs/{id}")



# ── 多配置 CRUD（B-P1-5）─────────────────────────────────────────────────────

@router.get("/configs")
async def list_llm_configs(request: Request):
    """列出所有 LLM 配置（admin-only，api_key 已掩码）"""
    get_current_admin(request)
    db_helper = LLMConfigDatabase()
    session = db_helper.get_session()
    try:
        configs = session.query(LLMConfig).order_by(LLMConfig.priority.desc(), LLMConfig.id).all()
        return {"configs": [c.to_dict() for c in configs]}
    finally:
        session.close()


@router.post("/configs", status_code=201)
async def create_llm_config(req: LLMConfigCreateRequest, request: Request):
    """创建新 LLM 配置（admin-only）"""
    get_current_admin(request)
    if not req.base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="base_url 必须以 http:// 或 https:// 开头")
    encrypted_key = _encrypt(req.api_key)
    db_helper = LLMConfigDatabase()
    session = db_helper.get_session()
    try:
        # Bug 3：display_name 唯一性校验
        if req.display_name:
            existing = session.query(LLMConfig).filter(
                LLMConfig.display_name == req.display_name
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail="显示名称已存在，请更换")
        config = LLMConfig(
            provider=req.provider,
            base_url=req.base_url,
            api_key_encrypted=encrypted_key,
            model=req.model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            is_active=req.is_active,
            purpose=req.purpose,
            display_name=req.display_name,
            priority=req.priority,
            api_key_updated_at=datetime.utcnow(),
        )
        session.add(config)
        session.commit()
        session.refresh(config)
        try:
            from services.logs import logger
            logger.log_operation(
                operation_type="llm_config_create",
                target=str(config.id),
                status="success",
                details=f"创建 LLM 配置: {config.display_name or config.provider}",
                operator=get_current_admin(request)["username"],
            )
        except Exception as _log_exc:
            import logging
            logging.getLogger(__name__).warning("日志记录失败: %s", _log_exc)
        return {"config": config.to_dict()}
    finally:
        session.close()


@router.put("/configs/{config_id}")
async def update_llm_config(config_id: int, req: LLMConfigUpdateRequest, request: Request):
    """更新 LLM 配置（admin-only，api_key 为空字符串时不更新）"""
    get_current_admin(request)
    if req.base_url is not None and req.base_url != "" and not req.base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="base_url 必须以 http:// 或 https:// 开头")
    db_helper = LLMConfigDatabase()
    session = db_helper.get_session()
    try:
        config = session.query(LLMConfig).filter(LLMConfig.id == config_id).first()
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        # Bug 3：display_name 唯一性校验（排除自身）
        if req.display_name is not None and req.display_name != "":
            existing = session.query(LLMConfig).filter(
                LLMConfig.display_name == req.display_name,
                LLMConfig.id != config_id,
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail="显示名称已被其他配置使用")
        if req.provider is not None:
            config.provider = req.provider
        if req.base_url is not None:
            config.base_url = req.base_url
        if req.api_key:  # 非空字符串才更新
            config.api_key_encrypted = _encrypt(req.api_key)
            config.api_key_updated_at = datetime.utcnow()
        if req.model is not None:
            config.model = req.model
        if req.temperature is not None:
            config.temperature = req.temperature
        if req.max_tokens is not None:
            config.max_tokens = req.max_tokens
        if req.is_active is not None:
            config.is_active = req.is_active
        if req.purpose is not None:
            config.purpose = req.purpose
        if req.display_name is not None:
            config.display_name = req.display_name
        if req.priority is not None:
            config.priority = req.priority
        session.commit()
        session.refresh(config)
        try:
            from services.logs import logger
            logger.log_operation(
                operation_type="llm_config_update",
                target=str(config_id),
                status="success",
                details=f"更新 LLM 配置: {config.display_name or str(config_id)}",
                operator=get_current_admin(request)["username"],
            )
        except Exception as _log_exc:
            import logging
            logging.getLogger(__name__).warning("日志记录失败: %s", _log_exc)
        return {"config": config.to_dict()}
    finally:
        session.close()


@router.delete("/configs/{config_id}", status_code=204)
async def delete_llm_config_by_id(config_id: int, request: Request):
    """删除 LLM 配置（admin-only，不允许删除最后一条 default 配置）"""
    get_current_admin(request)
    db_helper = LLMConfigDatabase()
    session = db_helper.get_session()
    try:
        config = session.query(LLMConfig).filter(LLMConfig.id == config_id).first()
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        # 保护：不允许删最后一条 default active 配置
        if config.purpose == "default" and config.is_active:
            remaining = session.query(LLMConfig).filter(
                LLMConfig.purpose == "default",
                LLMConfig.is_active == True,
                LLMConfig.id != config_id,
            ).count()
            if remaining == 0:
                raise HTTPException(status_code=400, detail="不能删除最后一条 default 活跃配置")
        try:
            from services.logs import logger
            logger.log_operation(
                operation_type="llm_config_delete",
                target=str(config_id),
                status="success",
                details=f"删除 LLM 配置: {config.display_name or str(config_id)}",
                operator=get_current_admin(request)["username"],
            )
        except Exception as _log_exc:
            import logging
            logging.getLogger(__name__).warning("日志记录失败: %s", _log_exc)
        session.delete(config)
        session.commit()
    finally:
        session.close()


@router.patch("/configs/{config_id}/active")
async def toggle_llm_config_active(
    config_id: int,
    body: ActiveToggleRequest,
    request: Request,
):
    """轻量启用/禁用 LLM 配置（admin-only）

    - is_active=False 时，若该配置是 purpose='default' 下的最后一条活跃配置，拒绝禁用（400）。
    - 成功后返回更新后的完整 config dict 并写审计日志。
    """
    user = get_current_admin(request)
    db_helper = LLMConfigDatabase()
    session = db_helper.get_session()
    try:
        config = session.query(LLMConfig).filter(LLMConfig.id == config_id).first()
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")

        # 禁用保护：不允许禁用 purpose='default' 下最后一条活跃配置
        if not body.is_active and config.is_active and config.purpose == "default":
            remaining = session.query(LLMConfig).filter(
                LLMConfig.purpose == "default",
                LLMConfig.is_active == True,
                LLMConfig.id != config_id,
            ).count()
            if remaining == 0:
                raise HTTPException(status_code=400, detail="不能禁用最后一条 default 活跃配置")

        config.is_active = body.is_active
        session.commit()
        session.refresh(config)

        action = "启用" if body.is_active else "禁用"
        try:
            from services.logs import logger as _audit_logger
            _audit_logger.log_operation(
                operation_type="llm_config_toggle_active",
                target=str(config_id),
                status="success",
                details=f"{action} LLM 配置: {config.display_name or str(config_id)}",
                operator=user["username"],
            )
        except Exception as _log_exc:
            import logging
            logging.getLogger(__name__).warning("日志记录失败: %s", _log_exc)

        return {"config": config.to_dict()}
    finally:
        session.close()


@router.get("/assets/{asset_id}/summary")
async def get_asset_summary(asset_id: int, request: Request, refresh: bool = False):
    """获取资产 AI 摘要"""
    user = get_current_user(request)

    import datetime

    from tableau.models import TableauDatabase

    db = TableauDatabase()
    asset = db.get_asset(asset_id)

    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="资产不存在")

    # IDOR 校验
    conn = db.get_connection(asset.connection_id)
    if user["role"] != "admin" and conn.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问该资产")

    # 检查缓存（1 小时）
    if not refresh and asset.ai_summary and asset.ai_summary_generated_at:
        elapsed = datetime.datetime.now() - asset.ai_summary_generated_at
        if elapsed.total_seconds() < 3600:
            return {"summary": asset.ai_summary, "cached": True}

    # 生成新摘要
    result = await llm_service.generate_asset_summary(asset)

    if "summary" in result:
        db.update_asset_summary(asset_id, result["summary"])
        return {"summary": result["summary"], "cached": False}
    else:
        error_msg = result.get("error", "生成失败")
        db.update_asset_error(asset_id, error_msg)
        return {"summary": None, "error": error_msg}


@router.get("/assets/{asset_id}/explain")
async def get_asset_explanation(asset_id: int, request: Request, refresh: bool = False):
    """获取资产 AI 详细解读（PRD §2.4）"""
    user = get_current_user(request)

    import datetime

    from tableau.models import TableauDatabase

    db = TableauDatabase()
    asset = db.get_asset(asset_id)

    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="资产不存在")

    # IDOR 校验
    conn = db.get_connection(asset.connection_id)
    if user["role"] != "admin" and conn.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问该资产")

    # 检查缓存（1小时）
    if not refresh and asset.ai_explain and asset.ai_explain_at:
        elapsed = datetime.datetime.now() - asset.ai_explain_at
        if elapsed.total_seconds() < 3600:
            return {"explanation": asset.ai_explain, "cached": True}

    # 生成新解读
    result = await llm_service.generate_asset_explanation(asset)

    if "explanation" in result:
        db.update_asset_explain(asset_id, result["explanation"])
        return {"explanation": result["explanation"], "cached": False}
    else:
        error_msg = result.get("error", "生成失败")
        return {"explanation": None, "error": error_msg}

