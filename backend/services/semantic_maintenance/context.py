"""
语义维护模块 - ContextVar 共享上下文（协程/线程安全）

用于在 FieldSyncService 和 PublishService 之间共享 Tableau REST API 认证令牌。
避免将 auth_token / site_id 存储在实例属性中导致跨协程串签。
"""
import contextvars
from typing import Optional

# Tableau REST API 认证上下文
_auth_token_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "semantic_auth_token", default=None
)
_site_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "semantic_site_id", default=None
)


def set_semantic_auth(token: str, site_id: str) -> None:
    """在当前上下文设置 Tableau REST API 认证令牌"""
    _auth_token_var.set(token)
    _site_id_var.set(site_id)


def get_semantic_auth() -> tuple[Optional[str], Optional[str]]:
    """获取当前上下文的 (auth_token, site_id)"""
    return _auth_token_var.get(), _site_id_var.get()


def clear_semantic_auth() -> None:
    """清除当前上下文的认证令牌"""
    _auth_token_var.set(None)
    _site_id_var.set(None)
