"""
中央配置读取层 — services/ 专用

架构约束：
- services/ 不得直接调用 os.environ
- 所有 env var 通过本模块的 getter 函数读取
- Redis / Broker URL 支持 fail-open 默认值
- 加密密钥在首次调用时惰性加载（非 module-level import time）

用法：
    from services.common.settings import get_encryption_key, get_redis_url

CI grep 白名单：本文件本身允许 os.environ，
其他 services/ 文件若发现 os.environ 调用需立即上报。
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional


# =============================================================================
# 加密密钥（惰性加载，解决 module-level 常量导致 key rotation 失效问题）
# =============================================================================

@lru_cache(maxsize=1)
def get_encryption_key() -> str:
    """
    获取 LLM/Tableau 加密密钥（惰性加载，缓存结果）。
    优先级：LLM_ENCRYPTION_KEY > DATASOURCE_ENCRYPTION_KEY
    """
    key = os.environ.get("LLM_ENCRYPTION_KEY") or os.environ.get("DATASOURCE_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "LLM_ENCRYPTION_KEY or DATASOURCE_ENCRYPTION_KEY must be set"
        )
    return key


def clear_encryption_key_cache() -> None:
    """运维用：清除加密密钥缓存（密钥轮换后必须调用）"""
    get_encryption_key.cache_clear()


# =============================================================================
# Redis 连接配置
# =============================================================================

@lru_cache(maxsize=1)
def get_redis_url() -> str:
    """
    获取 Redis 连接 URL（惰性加载，缓存结果）。
    用于：Celery Broker / NLQ 字段缓存 / DDL 规则缓存
    """
    return os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")


def clear_redis_url_cache() -> None:
    """运维用：清除 Redis URL 缓存"""
    get_redis_url.cache_clear()


# =============================================================================
# Celery Broker/Backend（供 tasks/__init__.py 使用）
# =============================================================================

@lru_cache(maxsize=1)
def get_celery_broker_url() -> str:
    return os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")


@lru_cache(maxsize=1)
def get_celery_result_backend() -> str:
    return os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")


# =============================================================================
# Tableau MCP Server 配置（惰性加载）
# =============================================================================

def get_tableau_mcp_server_url() -> str:
    """
    获取 Tableau MCP Server URL。
    优先级：DB(type=tableau, is_active=True) > 环境变量 > 默认值
    DB 查询失败时静默 fallback（迁移未完成等情况）。
    """
    try:
        from app.core.database import SessionLocal
        from services.mcp.models import McpServer
        db = SessionLocal()
        try:
            record = (
                db.query(McpServer)
                .filter(McpServer.type == "tableau", McpServer.is_active == True)
                .order_by(McpServer.created_at.asc())
                .first()
            )
            if record:
                return record.server_url
        finally:
            db.close()
    except Exception:
        pass
    return os.environ.get("TABLEAU_MCP_SERVER_URL", "http://localhost:3927/tableau-mcp")


@lru_cache(maxsize=1)
def get_tableau_mcp_timeout() -> int:
    return int(os.environ.get("TABLEAU_MCP_TIMEOUT", "30"))


@lru_cache(maxsize=1)
def get_tableau_mcp_protocol_version() -> str:
    return os.environ.get("TABLEAU_MCP_PROTOCOL_VERSION", "2025-06-18")


def clear_tableau_mcp_cache() -> None:
    """运维用：清除 Tableau MCP 配置缓存"""
    get_tableau_mcp_timeout.cache_clear()
    get_tableau_mcp_protocol_version.cache_clear()


# =============================================================================
# 认证 Bootstrap（供 services/auth/service.py 使用）
# =============================================================================

def get_admin_username() -> str:
    return os.environ.get("ADMIN_USERNAME", "admin")


def get_admin_password() -> Optional[str]:
    return os.environ.get("ADMIN_PASSWORD")
