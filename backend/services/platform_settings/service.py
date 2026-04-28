"""平台设置服务"""
import logging
import re
import threading
import time
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from .models import PlatformSettings

logger = logging.getLogger(__name__)

# 缓存 TTL = 30 秒（Spec 36 §15 热更要求）
_SETTINGS_CACHE_TTL = 30


class _SettingsCache:
    """
    线程安全的设置缓存（TTL=30s，支持热更）。
    存储结构：{key: (value, expiry_timestamp)}
    """

    def __init__(self, ttl: int = _SETTINGS_CACHE_TTL):
        self._cache: Dict[str, Any] = {}
        self._expiry: Dict[str, float] = {}
        self._ttl = ttl
        self._lock = threading.RLock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                return None
            if time.time() > self._expiry.get(key, 0):
                # 过期，删除
                self._cache.pop(key, None)
                self._expiry.pop(key, None)
                return None
            return self._cache[key]

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._cache[key] = value
            self._expiry[key] = time.time() + self._ttl

    def invalidate(self, key: Optional[str] = None) -> None:
        """清空缓存，key=None 时清空所有"""
        with self._lock:
            if key is None:
                self._cache.clear()
                self._expiry.clear()
            else:
                self._cache.pop(key, None)
                self._expiry.pop(key, None)


# 全局缓存实例
_settings_cache = _SettingsCache()


class PlatformSettingsService:
    """平台设置服务

    支持两种访问模式：
    1. 结构化字段：get_settings() / put_settings()
    2. Key-Value 模式：get(key) / set(key, value)  —— 用于 homepage_agent_mode 等特性开关
    """

    # 默认 Logo URL（复用 config.ts 原值）
    DEFAULT_LOGO_URL = "https://public.readdy.ai/ai/img_res/d9bf8fa2-dfff-4c50-98cf-7b635309e7d6.png"
    DEFAULT_PLATFORM_NAME = "木兰 BI 平台"
    DEFAULT_PLATFORM_SUBTITLE = "数据建模与治理平台"

    def __init__(self, db: Session):
        self.db = db

    def get_settings(self) -> Optional[PlatformSettings]:
        """获取平台设置（仅 id=1）"""
        return self.db.query(PlatformSettings).filter(PlatformSettings.id == 1).first()

    def get_or_initialize(self) -> PlatformSettings:
        """获取设置，若不存在则创建默认记录"""
        from sqlalchemy.exc import IntegrityError

        settings = self.get_settings()
        if settings is None:
            try:
                settings = PlatformSettings(
                    id=1,
                    platform_name=self.DEFAULT_PLATFORM_NAME,
                    platform_subtitle=self.DEFAULT_PLATFORM_SUBTITLE,
                    logo_url=self.DEFAULT_LOGO_URL,
                    favicon_url=None,
                )
                self.db.add(settings)
                self.db.commit()
                self.db.refresh(settings)
            except IntegrityError:
                # 并发请求已创建，回滚并重新查询
                self.db.rollback()
                settings = self.get_settings()
        return settings

    # -------------------------------------------------------------------------
    # Key-Value 访问模式（Spec 36 §15 唯一读取入口）
    # -------------------------------------------------------------------------

    def get(self, key: str) -> Optional[str]:
        """
        获取指定 key 的值（TTL=30s 缓存）。

        Spec 36 §15 红线约束：
        HOMEPAGE_AGENT_MODE 唯一读取入口是此方法，禁止业务代码直接读 env。

        :param key: 配置键名（如 'homepage_agent_mode', 'homepage_agent_mode_user_override'）
        :return: 配置值字符串或 None
        """
        # 先查缓存
        cached = _settings_cache.get(key)
        if cached is not None:
            return cached

        # 查数据库（从 settings 表的扩展字段，或新建一个 key-value 表）
        # 当前 platform_settings 是单行结构，扩展字段用 JSONB 存储
        # 由于原表只有 id=1 的单行，我们用额外字段扩展，或新建表
        # 这里先用一个简化方案：通过查询 settings JSON 字段读取
        settings = self.get_settings()
        if settings is None:
            return None

        # settings 对象目前没有 extra_settings 字段
        # 方案：在 PlatformSettings 模型上临时加一个 JSONB 字段不现实
        # 改用直接查询的方式（后续可迁移到独立的 key-value 表）
        from sqlalchemy import text

        # 直接从数据库查询 platform_settings 表的 extra_settings JSON 字段
        # 需要在模型中先添加该字段，或直接用原始 SQL
        row = self.db.execute(
            text("SELECT extra_settings FROM platform_settings WHERE id = 1")
        ).fetchone()

        if row is None:
            return None

        import json
        extra = row[0] or {}
        value = extra.get(key) if isinstance(extra, dict) else None

        # 写入缓存
        if value is not None:
            _settings_cache.set(key, value)

        return value

    def set(self, key: str, value: str) -> None:
        """
        设置指定 key 的值（同时更新数据库和缓存）。

        用于：
        - homepage_agent_mode 全局切换
        - homepage_agent_mode_user_override 单用户覆盖

        :param key: 配置键名
        :param value: 配置值（字符串）
        """
        import json

        # 获取当前 extra_settings
        settings = self.get_settings()
        row = self.db.execute(
            text("SELECT extra_settings FROM platform_settings WHERE id = 1")
        ).fetchone()

        extra = {}
        if row and row[0]:
            extra = row[0] if isinstance(row[0], dict) else json.loads(row[0])

        extra[key] = value

        # 更新数据库
        self.db.execute(
            text("UPDATE platform_settings SET extra_settings = :extra WHERE id = 1"),
            {"extra": json.dumps(extra)},
        )
        self.db.commit()

        # 更新缓存
        _settings_cache.set(key, value)

        logger.info("PlatformSetting updated: %s = %s", key, value)

    @staticmethod
    def validate_logo_url(url: str) -> bool:
        """校验 logo_url 是否为合法 HTTP(S) URL"""
        pattern = r"^https?://[^\s/$.?#]+\.[^\s]*$"
        return bool(re.match(pattern, url)) and len(url) <= 512

    def put_settings(
        self,
        platform_name: str,
        platform_subtitle: Optional[str],
        logo_url: str,
        favicon_url: Optional[str],
    ) -> PlatformSettings:
        """
        全量更新平台设置（仅 id=1）。
        返回更新后的记录。
        """
        settings = self.get_or_initialize()

        settings.platform_name = platform_name
        settings.platform_subtitle = platform_subtitle
        settings.logo_url = logo_url
        settings.favicon_url = favicon_url

        self.db.commit()
        self.db.refresh(settings)
        return settings
