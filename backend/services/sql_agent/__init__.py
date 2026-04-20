"""SQL Agent — 多方言 SQL 执行与安全校验服务"""

# 只导出子模块，不导入 service（service 依赖 DATABASE_URL）
from . import security
from . import executor
from . import models

from .models import SQLAgentQueryLog

__all__ = ["SQLAgentService", "SQLAgentQueryLog", "security", "executor", "models"]

def __getattr__(name):
    """惰性导入，避免未配置 DATABASE_URL 时无法使用 security/executor"""
    if name == "SQLAgentService":
        from .service import SQLAgentService
        return SQLAgentService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
