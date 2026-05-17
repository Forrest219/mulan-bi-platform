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
from urllib.parse import urlsplit, urlunsplit


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

_LEGACY_DOCKER_HOST = "host.docker.internal"
_LOCAL_TABLEAU_MCP_HOST = "localhost"
_LOCAL_TABLEAU_MCP_PORT = 3927
_DOCKER_TABLEAU_MCP_HOST = "tableau-mcp-gateway"
_DOCKER_TABLEAU_MCP_PORT = 3928


def _is_running_in_container() -> bool:
    return bool(
        os.environ.get("KUBERNETES_SERVICE_HOST")
        or os.environ.get("DOCKER_CONTAINER")
        or os.path.exists("/.dockerenv")
    )


def normalize_tableau_mcp_endpoint(value: Optional[str]) -> Optional[str]:
    """Normalize persisted Tableau MCP endpoints for the current runtime.

    `host.docker.internal` is a container-to-host address and should not be
    persisted as the shared Tableau MCP binding URL. Host-side scripts need
    localhost, while docker-compose services should use the gateway service DNS.
    """
    raw = (value or "").strip()
    if not raw:
        return None

    parsed = urlsplit(raw)
    if parsed.hostname != _LEGACY_DOCKER_HOST:
        return raw.rstrip("/")

    if _is_running_in_container():
        host = _DOCKER_TABLEAU_MCP_HOST
        port = _DOCKER_TABLEAU_MCP_PORT if parsed.port in (None, _LOCAL_TABLEAU_MCP_PORT) else parsed.port
    else:
        host = _LOCAL_TABLEAU_MCP_HOST
        port = parsed.port or _LOCAL_TABLEAU_MCP_PORT

    netloc = f"{host}:{port}" if port else host
    return urlunsplit((parsed.scheme or "http", netloc, parsed.path, parsed.query, parsed.fragment)).rstrip("/")


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
            records = (
                db.query(McpServer)
                .filter(McpServer.type == "tableau", McpServer.is_active == True)
                .order_by(McpServer.created_at.asc())
                .all()
            )
            for record in records:
                credentials = record.credentials or {}
                tableau_server = (credentials.get("tableau_server") or "").rstrip("/")
                record_url = (normalize_tableau_mcp_endpoint(record.server_url) or "").rstrip("/")
                # mcp_servers.type='tableau' may store the Tableau site root
                # together with PAT credentials. That is not a streamable-http
                # MCP endpoint, so do not use it as TABLEAU_MCP_SERVER_URL.
                if record_url and "/mcp" in record_url.lower():
                    return record_url
                if record_url and record_url != tableau_server:
                    return record_url
        finally:
            db.close()
    except Exception:
        pass
    default_url = (
        "http://tableau-mcp-gateway:3928/tableau-mcp"
        if _is_running_in_container()
        else "http://localhost:3927/tableau-mcp"
    )
    return normalize_tableau_mcp_endpoint(os.environ.get("TABLEAU_MCP_SERVER_URL", default_url)) or default_url


def get_tableau_mcp_gateway_url() -> Optional[str]:
    """Shared Tableau MCP Gateway endpoint for auto-bound Tableau connections.

    MVP auto-bindings only read TABLEAU_MCP_GATEWAY_URL. The legacy
    TABLEAU_MCP_SERVER_URL fallback remains available to older runtime callers
    through get_tableau_mcp_server_url(), but it is not used for new bindings.
    """
    value = os.environ.get("TABLEAU_MCP_GATEWAY_URL")
    if value and value.strip():
        return normalize_tableau_mcp_endpoint(value)
    return None


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


# =============================================================================
# SMTP 配置（Spec 16 §5.2.2）
# =============================================================================

def get_smtp_config() -> dict:
    """
    获取 SMTP 配置字典（用于邮件出站）。

    读取顺序：
    1. DB: platform_settings.extra_settings["smtp"]（已加密存储）
    2. .env: SMTP_* 环境变量

    返回 dict 格式（统一 key 名）：
        host, port, user, password(解密后), from_addr, use_tls
    """
    # 1. 尝试从 DB 读取（platform_settings.extra_settings["smtp"]）
    db_cfg = _get_smtp_config_from_db()
    if db_cfg:
        # DB 中 password 已加密存储，需要解密
        password_plaintext = _decrypt_smtp_password(db_cfg.get("password_encrypted"))
        return {
            "host": db_cfg.get("host"),
            "port": int(db_cfg.get("port", 465)),
            "user": db_cfg.get("user"),
            "password": password_plaintext,
            "from_addr": db_cfg.get("from_addr"),
            "use_tls": bool(db_cfg.get("use_tls", True)),
        }

    # 2. Fallback 到 .env
    return {
        "host": os.environ.get("SMTP_HOST"),
        "port": int(os.environ.get("SMTP_PORT", "465")),
        "user": os.environ.get("SMTP_USER"),
        "password": os.environ.get("SMTP_PASSWORD"),
        "use_tls": os.environ.get("SMTP_USE_TLS", "true").lower() == "true",
        "from_addr": os.environ.get("SMTP_FROM_ADDR"),
    }


def _get_smtp_config_from_db() -> Optional[dict]:
    """
    从 platform_settings.extra_settings["smtp"] 读取 SMTP 配置。
    若 DB 中无配置或 Encryption Key 未设置，返回 None。
    """
    try:
        from app.core.database import SessionLocal
        from services.platform_settings.service import PlatformSettingsService
        db = SessionLocal()
        try:
            svc = PlatformSettingsService(db)
            return svc.get_smtp_config_from_db()
        finally:
            db.close()
    except Exception:
        # Encryption Key 未设置或 DB 连接失败，降级到 .env
        return None


def _decrypt_smtp_password(password_encrypted: Optional[str]) -> Optional[str]:
    """从 DB 读取加密密码后解密；无加密内容时返回原文（兼容旧 .env 降级）"""
    if not password_encrypted:
        return None
    # 判断是否为密文（非 base64url 标准 Fernet 格式则为明文旧数据）
    try:
        from app.core.crypto import get_smtp_crypto
        crypto = get_smtp_crypto()
        return crypto.decrypt(password_encrypted)
    except Exception:
        # 旧版明文或解密失败，返回原文
        return password_encrypted


def get_fernet_master_key() -> Optional[str]:
    """获取 Fernet 主密钥（用于 Webhook secret 加密，Spec 16 §5.3.8）"""
    return os.environ.get("FERNET_MASTER_KEY")
