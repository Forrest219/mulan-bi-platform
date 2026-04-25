"""平台设置服务"""
import re
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from .models import PlatformSettings


class PlatformSettingsService:
    """平台设置服务"""

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
