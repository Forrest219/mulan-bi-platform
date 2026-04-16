"""LLM 管理 API"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.dependencies import get_current_admin, get_current_user
from services.llm.models import LLMConfigDatabase, LLMConfig
from services.llm.service import _encrypt, llm_service

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
    base_url: str = "https://api.openai.com/v1"
    api_key: str
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 1024
    is_active: bool = True
    purpose: str = "default"
    display_name: Optional[str] = None
    priority: int = 0


class LLMConfigUpdateRequest(BaseModel):
    """多配置更新请求（api_key 为空字符串时不更新）"""

    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    is_active: Optional[bool] = None
    purpose: Optional[str] = None
    display_name: Optional[str] = None
    priority: Optional[int] = None


class LLMTestRequest(BaseModel):
    """LLM 测试请求模型"""

    prompt: str = "Hello, respond with 'OK'"


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
    """测试 LLM 连接"""
    get_current_admin(request)
    result = await llm_service.test_connection(test_prompt=req.prompt)
    return result


@router.delete("/config")
async def delete_llm_config(request: Request):
    """删除 LLM 配置"""
    get_current_admin(request)
    db = LLMConfigDatabase()
    db.delete_config()
    return {"message": "LLM 配置已删除"}



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
    encrypted_key = _encrypt(req.api_key)
    db_helper = LLMConfigDatabase()
    session = db_helper.get_session()
    try:
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
        )
        session.add(config)
        session.commit()
        session.refresh(config)
        return {"config": config.to_dict()}
    finally:
        session.close()


@router.put("/configs/{config_id}")
async def update_llm_config(config_id: int, req: LLMConfigUpdateRequest, request: Request):
    """更新 LLM 配置（admin-only，api_key 为空字符串时不更新）"""
    get_current_admin(request)
    db_helper = LLMConfigDatabase()
    session = db_helper.get_session()
    try:
        config = session.query(LLMConfig).filter(LLMConfig.id == config_id).first()
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        if req.provider is not None:
            config.provider = req.provider
        if req.base_url is not None:
            config.base_url = req.base_url
        if req.api_key:  # 非空字符串才更新
            config.api_key_encrypted = _encrypt(req.api_key)
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
        session.delete(config)
        session.commit()
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

