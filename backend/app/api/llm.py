"""LLM 管理 API"""
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
from llm.models import LLMConfigDatabase
from llm.service import llm_service, _encrypt
from app.core.dependencies import get_current_user, get_current_admin

router = APIRouter()


class LLMConfigRequest(BaseModel):
    provider: str = "openai"
    base_url: str = "https://api.openai.com/v1"
    api_key: str
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 1024
    is_active: bool = True


class LLMTestRequest(BaseModel):
    prompt: str = "Hello, respond with 'OK'"


def _db_path():
    return str(Path(__file__).parent.parent.parent.parent / "data" / "llm.db")


@router.get("/config")
async def get_llm_config(request: Request):
    """获取 LLM 配置（不返回 api_key 明文）"""
    get_current_admin(request)
    db = LLMConfigDatabase(db_path=_db_path())
    config = db.get_config()
    if not config:
        return {"config": None, "message": "未配置 LLM"}
    return {"config": config.to_dict()}


@router.post("/config")
async def save_llm_config(req: LLMConfigRequest, request: Request):
    """创建/更新 LLM 配置（仅 admin）"""
    user = get_current_admin(request)

    encrypted_key = _encrypt(req.api_key)
    db = LLMConfigDatabase(db_path=_db_path())
    db.save_config(
        provider=req.provider,
        base_url=req.base_url,
        api_key_encrypted=encrypted_key,
        model=req.model,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        is_active=req.is_active,
    )

    try:
        from logs import logger
        logger.log_operation(
            operation_type="llm_config_update",
            target="llm_config",
            status="success",
            operator=user["username"],
            detail=f"更新 LLM 配置: provider={req.provider}, model={req.model}"
        )
    except Exception:
        pass

    return {"message": "LLM 配置保存成功"}


@router.post("/config/test")
async def test_llm_connection(req: LLMTestRequest, request: Request):
    """测试 LLM 连接"""
    get_current_admin(request)
    result = llm_service.test_connection(test_prompt=req.prompt)
    return result


@router.delete("/config")
async def delete_llm_config(request: Request):
    """删除 LLM 配置"""
    get_current_admin(request)
    db = LLMConfigDatabase(db_path=_db_path())
    db.delete_config()
    return {"message": "LLM 配置已删除"}


@router.get("/assets/{asset_id}/summary")
async def get_asset_summary(asset_id: int, request: Request, refresh: bool = False):
    """获取资产 AI 摘要"""
    user = get_current_user(request)

    import datetime
    from tableau.models import TableauDatabase

    db_path = str(Path(__file__).parent.parent.parent.parent / "data" / "tableau.db")
    db = TableauDatabase(db_path=db_path)
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
    result = llm_service.generate_asset_summary(asset)

    if "summary" in result:
        db.update_asset_summary(asset_id, result["summary"])
        return {"summary": result["summary"], "cached": False}
    else:
        error_msg = result.get("error", "生成失败")
        db.update_asset_error(asset_id, error_msg)
        return {"summary": None, "error": error_msg}

