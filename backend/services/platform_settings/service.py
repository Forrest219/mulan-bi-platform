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

    # -------------------------------------------------------------------------
    # SMTP 配置读写（存储在 extra_settings JSONB 中）
    # -------------------------------------------------------------------------

    def get_smtp_config_from_db(self) -> Optional[dict]:
        """
        从 DB 读取 SMTP 配置（extra_settings["smtp"]）。
        返回 dict 或 None。
        """
        from sqlalchemy import text
        import json

        row = self.db.execute(
            text("SELECT extra_settings FROM platform_settings WHERE id = 1")
        ).fetchone()
        if row is None:
            return None
        extra = row[0] or {}
        if isinstance(extra, str):
            extra = json.loads(extra)
        return extra.get("smtp") if isinstance(extra, dict) else None

    def put_smtp_config(self, smtp_config: dict) -> dict:
        """
        写入 SMTP 配置到 extra_settings["smtp"]。

        smtp_config 格式：
        {
            "host": str,
            "port": int,
            "user": str,
            "password": str,   # 明文，存储前用 Fernet 加密
            "from_addr": str,
            "use_tls": bool,
        }

        加密策略：
        - password 字段用 SMTP_ENCRYPTION_KEY（或 DATASOURCE_ENCRYPTION_KEY）加密后存储
        - 存储字段名为 password_encrypted
        - password 明文字段不存储（前端传入明文，服务层加密）
        """
        import json
        from sqlalchemy import text
        from app.core.crypto import get_smtp_crypto

        row = self.db.execute(
            text("SELECT extra_settings FROM platform_settings WHERE id = 1")
        ).fetchone()

        extra = {}
        if row and row[0]:
            extra = row[0] if isinstance(row[0], dict) else json.loads(row[0])

        # 加密密码
        # 支持两种 key 命名：API 层用 smtp_* 前缀，内部存储用无前缀
        password_plain = smtp_config.get("smtp_password") or smtp_config.get("password") or ""
        try:
            crypto = get_smtp_crypto()
            password_encrypted = crypto.encrypt(password_plain) if password_plain else ""
        except RuntimeError:
            # Encryption Key 未配置时，降级存明文（兼容旧 .env 模式）
            password_encrypted = password_plain

        db_record = {
            "host": smtp_config.get("smtp_host") or smtp_config.get("host"),
            "port": smtp_config.get("smtp_port") or smtp_config.get("port", 465),
            "user": smtp_config.get("smtp_user") or smtp_config.get("user"),
            "password_encrypted": password_encrypted,
            "from_addr": smtp_config.get("smtp_from_addr") or smtp_config.get("from_addr"),
            "use_tls": bool(smtp_config.get("smtp_use_tls") if "smtp_use_tls" in smtp_config else smtp_config.get("use_tls", True)),
        }

        extra["smtp"] = db_record

        self.db.execute(
            text("UPDATE platform_settings SET extra_settings = :extra WHERE id = 1"),
            {"extra": json.dumps(extra)},
        )
        self.db.commit()
        logger.info("SMTP 配置已保存（密码已加密）")
        return smtp_config

    def test_smtp_settings(self, smtp_config: dict) -> tuple[bool, str]:
        """
        测试 SMTP 配置是否可用。

        使用临时 SMTP 连接尝试发送一封测试邮件。
        返回 (success, detail)。
        """
        import json
        from sqlalchemy import text
        from app.core.crypto import get_smtp_crypto

        # 加密后的配置构造测试用
        password_plain = smtp_config.get("password") or ""
        try:
            crypto = get_smtp_crypto()
            password_encrypted = crypto.encrypt(password_plain) if password_plain else ""
        except RuntimeError:
            password_encrypted = password_plain

        test_cfg = {
            "host": smtp_config.get("host"),
            "port": smtp_config.get("port", 465),
            "user": smtp_config.get("user"),
            "password_encrypted": password_encrypted,
            "from_addr": smtp_config.get("from_addr"),
            "use_tls": bool(smtp_config.get("use_tls", True)),
        }

        from services.events.channels.email_channel import EmailChannel

        channel = EmailChannel()
        result = channel.deliver_password_reset_email(
            recipient=smtp_config.get("test_recipient", smtp_config.get("from_addr") or ""),
            display_name="管理员",
            reset_link=f"{smtp_config.get('host')} (连接测试)",
            smtp_config=test_cfg,
        )

        if result.status == "delivered":
            return True, "邮件发送成功"
        else:
            return False, result.detail

    # -------------------------------------------------------------------------
    # 邮件发送日志查询
    # -------------------------------------------------------------------------

    def get_email_send_logs(
        self,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """
        查询最近的邮件发送记录（最多 page_size 条，page 从 1 开始）。
        用于平台设置页"发送记录"表格。
        """
        from sqlalchemy import text
        from services.events.models import BiEmailSendLog

        try:
            total = self.db.query(BiEmailSendLog).count()
            items = (
                self.db.query(BiEmailSendLog)
                .order_by(BiEmailSendLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return {
                "items": [log.to_dict() for log in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        except Exception as e:
            # 表不存在或查询出错时返回空列表，避免 500
            logger.warning("[get_email_send_logs] 查询失败: %s", e)
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

    def create_email_send_log(
        self,
        email_type: str,
        recipient: str,
        from_addr: str,
        subject: str,
        outbox_id: int = None,
        scheduled_at=None,
    ) -> int:
        """
        创建一条邮件发送日志记录。

        返回新记录的 id。
        """
        from sqlalchemy import text
        from services.events.models import BiEmailSendLog
        import json

        log_entry = BiEmailSendLog(
            email_type=email_type,
            recipient=recipient,
            from_addr=from_addr,
            subject=(subject or "")[:128],
            status="enqueued",
            outbox_id=outbox_id,
            scheduled_at=scheduled_at,
            attempt_count=0,
        )
        self.db.add(log_entry)
        self.db.commit()
        self.db.refresh(log_entry)
        return log_entry.id

    def update_email_send_log(
        self,
        log_id: int,
        status: str,
        error_detail: str = None,
        attempt_count: int = None,
        sent_at=None,
    ) -> None:
        """更新邮件发送日志状态"""
        from sqlalchemy import text
        from services.events.models import BiEmailSendLog

        log = self.db.query(BiEmailSendLog).filter(BiEmailSendLog.id == log_id).first()
        if not log:
            return
        log.status = status
        if error_detail:
            log.error_detail = error_detail[:512]
        if attempt_count is not None:
            log.attempt_count = attempt_count
        if sent_at:
            log.sent_at = sent_at
        self.db.commit()
