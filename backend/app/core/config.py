"""
应用配置层 - 提供 get_settings() 函数

架构约束：
- app/ 层使用本模块集中管理配置
- services/ 层应使用 services.common.settings
"""
import os
from functools import lru_cache
from typing import Optional


class Settings:
    """应用配置类"""

    # Database
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi")
    DB_POOL_SIZE: int = int(os.environ.get("DB_POOL_SIZE", "10"))
    DB_MAX_OVERFLOW: int = int(os.environ.get("DB_MAX_OVERFLOW", "20"))

    # Security
    SESSION_SECRET: str = os.environ.get("SESSION_SECRET", "change-this-to-a-random-secret-in-production")
    DATASOURCE_ENCRYPTION_KEY: str = os.environ.get("DATASOURCE_ENCRYPTION_KEY", "change-this-to-a-random-key-32b!")
    TABLEAU_ENCRYPTION_KEY: str = os.environ.get("TABLEAU_ENCRYPTION_KEY", "change-this-to-another-key-32b!")
    LLM_ENCRYPTION_KEY: str = os.environ.get("LLM_ENCRYPTION_KEY", "change-this-to-llm-key-32bytes!")

    # CORS
    ALLOWED_ORIGINS: str = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3002,http://localhost:3003")

    # Cookies
    SECURE_COOKIES: bool = os.environ.get("SECURE_COOKIES", "false").lower() == "true"

    # Admin
    ADMIN_USERNAME: Optional[str] = os.environ.get("ADMIN_USERNAME")
    ADMIN_PASSWORD: Optional[str] = os.environ.get("ADMIN_PASSWORD")

    # Celery
    CELERY_BROKER_URL: str = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND: str = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
