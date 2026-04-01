"""
Tableau 管理 API
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
from tableau.models import TableauDatabase
from tableau.sync_service import TableauSyncService
from app.core.dependencies import get_current_user
from app.core.crypto import get_tableau_crypto

router = APIRouter()

_crypto = get_tableau_crypto()
_encrypt = _crypto.encrypt
_decrypt = _crypto.decrypt


def _db_path():
    return str(Path(__file__).parent.parent.parent.parent / "data" / "tableau.db")


def require_admin_or_data_admin(request: Request) -> dict:
    """仅管理员或数据管理员可访问"""
    user = get_current_user(request)
    if user["role"] not in ("admin", "data_admin"):
        raise HTTPException(status_code=403, detail="需要管理员或数据管理员权限")
    return user


def _verify_connection_access(connection_id: int, user: dict, _db: TableauDatabase) -> None:
    """验证用户有权访问指定连接（IDOR 修复）"""
    conn = _db.get_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")
    # admin 可访问所有连接，非 admin 只能访问自己的
    if user["role"] != "admin" and conn.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问该连接")


# --- Pydantic Models ---

class CreateConnectionRequest(BaseModel):
    name: str
    server_url: str
    site: str
    api_version: str = "3.21"
    connection_type: str = "mcp"  # 'mcp' or 'tsc'
    token_name: str
    token_value: str


class UpdateConnectionRequest(BaseModel):
    name: Optional[str] = None
    server_url: Optional[str] = None
    site: Optional[str] = None
    api_version: Optional[str] = None
    connection_type: Optional[str] = None
    token_name: Optional[str] = None
    token_value: Optional[str] = None
    is_active: Optional[bool] = None
    auto_sync_enabled: Optional[bool] = None
    sync_interval_hours: Optional[int] = None


# --- REST API 直连测试（MCP 模式） ---

def _test_connection_rest(server_url: str, site: str, token_name: str,
                          token_value: str, api_version: str = "3.21") -> dict:
    """通过 REST API 直接测试 Tableau 连接（不依赖 TSC 库）"""
    import requests
    url = f"{server_url.rstrip('/')}/api/{api_version}/auth/signin"
    payload = {
        "credentials": {
            "personalAccessTokenName": token_name,
            "personalAccessTokenSecret": token_value,
            "site": {"contentUrl": site}
        }
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("credentials", {}).get("token", "")
            site_id = data.get("credentials", {}).get("site", {}).get("id", "")
            # Sign out 清理 session
            if token:
                try:
                    requests.post(
                        f"{server_url.rstrip('/')}/api/{api_version}/auth/signout",
                        headers={"X-Tableau-Auth": token},
                        timeout=5
                    )
                except Exception:
                    pass
            return {"success": True, "message": f"REST API 连接成功 (site: {site_id})"}
        else:
            detail = resp.text[:200]
            return {"success": False, "message": f"REST API 认证失败 (HTTP {resp.status_code}): {detail}"}
    except Exception as e:
        if "Timeout" in type(e).__name__:
            return {"success": False, "message": "连接超时，请检查 Server URL 是否可达"}
        if "ConnectionError" in type(e).__name__:
            return {"success": False, "message": "无法连接到服务器，请检查 URL"}
        return {"success": False, "message": f"REST API 测试失败: {str(e)}"}


# --- Endpoints ---

@router.get("/connections")
async def list_connections(request: Request, include_inactive: bool = False):
    """获取 Tableau 连接列表"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    if user["role"] == "admin":
        connections = _db.get_all_connections(include_inactive=include_inactive)
    else:
        connections = _db.get_all_connections(owner_id=user["id"], include_inactive=include_inactive)

    return {"connections": [c.to_dict() for c in connections], "total": len(connections)}


@router.post("/connections")
async def create_connection(req: CreateConnectionRequest, request: Request):
    """创建 Tableau 连接"""
    user = require_admin_or_data_admin(request)
    _db = TableauDatabase(db_path=_db_path())

    if req.connection_type not in ("mcp", "tsc"):
        raise HTTPException(status_code=400, detail="connection_type 必须为 'mcp' 或 'tsc'")

    encrypted_token = _encrypt(req.token_value)

    conn = _db.create_connection(
        name=req.name,
        server_url=req.server_url,
        site=req.site,
        token_name=req.token_name,
        token_encrypted=encrypted_token,
        owner_id=user["id"],
        api_version=req.api_version,
        connection_type=req.connection_type
    )

    return {"connection": conn.to_dict(), "message": "连接创建成功"}


@router.put("/connections/{conn_id}")
async def update_connection(conn_id: int, req: UpdateConnectionRequest, request: Request):
    """更新 Tableau 连接"""
    user = require_admin_or_data_admin(request)
    _db = TableauDatabase(db_path=_db_path())

    conn = _db.get_connection(conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    if user["role"] != "admin" and conn.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权修改该连接")

    update_data = req.model_dump(exclude_unset=True)
    if "token_value" in update_data and update_data["token_value"]:
        # 用户提供了新 token_value，同时更新 token_name 和加密后的 token
        update_data["token_encrypted"] = _encrypt(update_data.pop("token_value"))
        if req.token_name:
            update_data["token_name"] = req.token_name
    elif "token_value" in update_data and not update_data["token_value"]:
        # token_value 为空字符串，不更新 token 相关字段
        update_data.pop("token_value", None)
        update_data.pop("token_name", None)

    _db.update_connection(conn_id, **update_data)
    return {"message": "连接更新成功"}


@router.delete("/connections/{conn_id}")
async def delete_connection(conn_id: int, request: Request):
    """删除 Tableau 连接"""
    user = require_admin_or_data_admin(request)
    _db = TableauDatabase(db_path=_db_path())

    conn = _db.get_connection(conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    if user["role"] != "admin" and conn.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权删除该连接")

    _db.delete_connection(conn_id)
    return {"message": "连接已删除"}


@router.post("/connections/{conn_id}/test")
async def test_connection(conn_id: int, request: Request):
    """测试 Tableau 连接"""
    user = require_admin_or_data_admin(request)
    _db = TableauDatabase(db_path=_db_path())

    conn = _db.get_connection(conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    if user["role"] != "admin" and conn.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权操作该连接")

    try:
        decrypted_token = _decrypt(conn.token_encrypted)
    except Exception as decrypt_err:
        err_str = str(decrypt_err)
        if "InvalidToken" in err_str or "decrypt" in err_str.lower():
            msg = "Token 解密失败：加密密钥可能已变更，请重新保存 PAT Token"
            _db.update_connection_health(conn_id, False, msg)
            return {"success": False, "message": msg}
        raise

    # MCP 模式：通过 REST API 直连测试
    if getattr(conn, "connection_type", "mcp") == "mcp":
        result = _test_connection_rest(
            server_url=conn.server_url,
            site=conn.site,
            token_name=conn.token_name,
            token_value=decrypted_token,
            api_version=conn.api_version
        )
        _db.update_connection_health(conn_id, result["success"], result["message"])
        return result

    # TSC 模式：通过 tableauserverclient 库测试
    try:
        service = TableauSyncService(
            server_url=conn.server_url,
            site=conn.site,
            token_name=conn.token_name,
            token_value=decrypted_token,
            api_version=conn.api_version
        )
        try:
            result = service.test_connection()
            # 保存测试结果到数据库
            _db.update_connection_health(conn_id, result.get("success", False), result.get("message", ""))
            return result
        finally:
            service.disconnect()
    except Exception as e:
        error_msg = str(e)
        # 保存测试失败结果到数据库
        _db.update_connection_health(conn_id, False, f"测试失败: {error_msg}")
        return {"success": False, "message": f"测试失败: {error_msg}"}


@router.post("/connections/{conn_id}/sync")
async def sync_connection(conn_id: int, request: Request):
    """触发 Tableau 资产同步"""
    user = require_admin_or_data_admin(request)
    _db = TableauDatabase(db_path=_db_path())

    conn = _db.get_connection(conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    if user["role"] != "admin" and conn.owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="无权操作该连接")

    try:
        decrypted_token = _decrypt(conn.token_encrypted)
    except Exception as decrypt_err:
        err_str = str(decrypt_err)
        if "InvalidToken" in err_str or "decrypt" in err_str.lower():
            msg = "Token 解密失败：加密密钥可能已变更，请重新保存 PAT Token"
            _db.update_connection_health(conn_id, False, msg)
            return {"success": False, "message": msg}
        raise
    try:
        service = TableauSyncService(
            server_url=conn.server_url,
            site=conn.site,
            token_name=conn.token_name,
            token_value=decrypted_token,
            api_version=conn.api_version
        )

        try:
            if not service.connect():
                return {"success": False, "message": "无法连接到 Tableau Server"}

            result = service.sync_all_assets(_db, conn_id)

            wb_count = len(result['synced'].get("workbook", []))
            db_count = len(result['synced'].get("dashboard", []))
            view_count = len(result['synced'].get("view", []))
            ds_count = len(result['synced'].get("datasource", []))
            details = f"工作簿:{wb_count} 仪表板:{db_count} 视图:{view_count} 数据源:{ds_count}"

            return {
                "success": result["status"] != "failed",
                "message": f"同步{result['status']}，共 {result['total']} 个资产，标记 {result['deleted']} 个已删除，{details}",
                "sync_log_id": result.get("sync_log_id"),
                "duration_sec": result.get("duration_sec"),
                "errors": result.get("errors", []),
            }
        finally:
            service.disconnect()

    except Exception as e:
        error_msg = str(e)
        _db.update_connection_health(conn_id, False, f"同步失败: {error_msg}")
        return {"success": False, "message": f"同步失败: {error_msg}"}


@router.get("/assets")
async def list_assets(
    request: Request,
    connection_id: int = Query(..., description="连接 ID"),
    asset_type: Optional[str] = Query(None, description="资产类型: workbook, view, datasource"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100)
):
    """获取资产列表（分页）"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    # 验证用户有权访问该连接
    _verify_connection_access(connection_id, user, _db)

    assets, total = _db.get_assets(
        connection_id=connection_id,
        asset_type=asset_type,
        page=page,
        page_size=page_size
    )

    return {
        "assets": [a.to_dict() for a in assets],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size
    }


@router.get("/assets/search")
async def search_assets(
    request: Request,
    q: str = Query(..., min_length=1, description="搜索关键词"),
    connection_id: Optional[int] = Query(None),
    asset_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100)
):
    """搜索资产"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    # 如果指定了 connection_id，验证用户有权访问
    if connection_id is not None:
        _verify_connection_access(connection_id, user, _db)

    assets, total = _db.search_assets(
        connection_id=connection_id,
        query=q,
        asset_type=asset_type,
        page=page,
        page_size=page_size
    )

    return {
        "assets": [a.to_dict() for a in assets],
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: int, request: Request):
    """获取资产详情"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    asset = _db.get_asset(asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="资产不存在")

    # 验证用户有权访问该资产所属的连接
    _verify_connection_access(asset.connection_id, user, _db)

    result = asset.to_dict()

    # 获取关联的数据源
    datasources = _db.get_asset_datasources(asset_id)
    result["datasources"] = [ds.to_dict() for ds in datasources]

    # 获取连接信息（含 server_url 用于跳转链接）
    conn = _db.get_connection(asset.connection_id)
    if conn:
        result["server_url"] = conn.server_url

    return result


@router.get("/projects")
async def get_projects(
    request: Request,
    connection_id: int = Query(..., description="连接 ID")
):
    """获取项目树"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    # 验证用户有权访问该连接
    _verify_connection_access(connection_id, user, _db)

    projects = _db.get_project_tree(connection_id)
    return {"projects": projects}


# --- Sync Logs (Phase 2a) ---

@router.get("/connections/{conn_id}/sync-logs")
async def list_sync_logs(
    conn_id: int,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    """获取同步日志列表"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())
    _verify_connection_access(conn_id, user, _db)

    logs, total = _db.get_sync_logs(conn_id, page=page, page_size=page_size)
    return {
        "logs": [log.to_dict() for log in logs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/connections/{conn_id}/sync-logs/{log_id}")
async def get_sync_log(conn_id: int, log_id: int, request: Request):
    """获取同步日志详情"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())
    _verify_connection_access(conn_id, user, _db)

    log = _db.get_sync_log(log_id)
    if not log or log.connection_id != conn_id:
        raise HTTPException(status_code=404, detail="同步日志不存在")
    return log.to_dict()


@router.get("/connections/{conn_id}/sync-status")
async def get_sync_status(conn_id: int, request: Request):
    """获取连接同步状态"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())
    _verify_connection_access(conn_id, user, _db)

    conn = _db.get_connection(conn_id)
    return {
        "status": conn.sync_status or "idle",
        "last_sync_at": conn.last_sync_at.strftime("%Y-%m-%d %H:%M:%S") if conn.last_sync_at else None,
        "last_sync_duration_sec": conn.last_sync_duration_sec,
        "auto_sync_enabled": conn.auto_sync_enabled,
        "sync_interval_hours": conn.sync_interval_hours,
    }


# --- Asset Hierarchy (Phase 2a) ---

@router.get("/assets/{asset_id}/children")
async def get_asset_children(asset_id: int, request: Request):
    """获取 workbook 下属的 view/dashboard"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    asset = _db.get_asset(asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="资产不存在")
    _verify_connection_access(asset.connection_id, user, _db)

    if asset.asset_type != "workbook":
        return {"children": []}

    children = _db.get_children_assets(asset.tableau_id, asset.connection_id)
    return {"children": [c.to_dict() for c in children]}


@router.get("/assets/{asset_id}/parent")
async def get_asset_parent(asset_id: int, request: Request):
    """获取 view/dashboard 的父 workbook"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    asset = _db.get_asset(asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="资产不存在")
    _verify_connection_access(asset.connection_id, user, _db)

    parent = _db.get_parent_asset(asset_id)
    return {"parent": parent.to_dict() if parent else None}


# --- Deep AI Explain (Phase 2a) ---

class ExplainRequest(BaseModel):
    refresh: bool = False


@router.post("/assets/{asset_id}/explain")
async def explain_asset(asset_id: int, req: ExplainRequest, request: Request):
    """生成/获取深度 AI 解读"""
    user = get_current_user(request)
    _db = TableauDatabase(db_path=_db_path())

    asset = _db.get_asset(asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="资产不存在")
    _verify_connection_access(asset.connection_id, user, _db)

    # 缓存：1 小时内不重新生成（除非强制刷新）
    if not req.refresh and asset.ai_explain and asset.ai_explain_at:
        if datetime.now() - asset.ai_explain_at < timedelta(hours=1):
            return {
                "explain": asset.ai_explain,
                "cached": True,
                "generated_at": asset.ai_explain_at.strftime("%Y-%m-%d %H:%M:%S"),
            }

    # 获取关联数据源信息
    datasources = _db.get_asset_datasources(asset_id)
    ds_text = "\n".join([f"- {ds.datasource_name} ({ds.datasource_type or '未知类型'})" for ds in datasources]) or "无"

    # 获取数据源字段元数据（如果有缓存）
    field_text = "暂无字段元数据"
    fields = _db.get_datasource_fields(asset_id)
    if fields:
        field_lines = []
        for f in fields:
            caption = f.ai_caption or f.field_caption or ""
            desc = f.ai_description or f.description or ""
            role_str = f.role or ""
            line = f"- {f.field_name}"
            if caption:
                line += f" ({caption})"
            line += f" [{f.data_type or ''}] [{role_str}]"
            if f.formula:
                line += f" 公式: {f.formula}"
            if desc:
                line += f" — {desc}"
            field_lines.append(line)
        field_text = "\n".join(field_lines)

    # 获取父工作簿信息
    parent_info = "无"
    if asset.parent_workbook_name:
        parent_info = asset.parent_workbook_name

    # 调用 LLM 生成深度解读
    try:
        from llm.service import LLMService
        llm = LLMService()

        prompt = f"""你是一个 BI 报表解读专家。请根据以下报表信息，用通俗易懂的语言向业务用户解释这个报表。

## 报表基本信息
名称：{asset.name}
类型：{asset.asset_type}
项目：{asset.project_name or '未分类'}
描述：{asset.description or '无'}
所有者：{asset.owner_name or '未知'}

## 所属工作簿
{parent_info}

## 关联数据源
{ds_text}

## 数据源字段元数据
{field_text}

请提供以下内容:
1. **报表概述**: 用 2~3 句话说明这个报表的核心用途
2. **关键指标**: 列出报表涉及的主要指标，并用业务语言解释其含义
3. **维度说明**: 说明报表的主要分析维度
4. **数据关注点**: 指出使用此报表时需要注意的要点
5. **适用场景**: 建议在什么场景下使用此报表

要求:
- 面向非技术业务人员
- 使用中文
- 如果字段元数据中有计算字段公式，要解释其业务含义而非技术实现"""

        result = llm.complete(prompt, system="你是一个专业的 BI 报表解读专家。", timeout=30)
        if isinstance(result, dict) and "error" in result:
            return {"explain": None, "error": result["error"], "cached": False}

        explain_text = result if isinstance(result, str) else result.get("content", str(result))
        _db.update_asset_explain(asset_id, explain_text)

        return {
            "explain": explain_text,
            "cached": False,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if True else None,
        }

    except ImportError:
        return {"explain": None, "error": "LLM 服务未配置", "cached": False}
    except Exception as e:
        return {"explain": None, "error": f"生成失败: {str(e)}", "cached": False}
