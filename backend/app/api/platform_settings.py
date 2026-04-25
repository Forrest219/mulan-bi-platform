"""平台设置 API"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
import re

from app.core.dependencies import get_current_user
from app.core.database import get_db
from services.platform_settings import PlatformSettingsService

router = APIRouter(redirect_slashes=False)


class PlatformSettingsRequest(BaseModel):
    """更新平台设置请求"""
    platform_name: str
    platform_subtitle: Optional[str] = None
    logo_url: str
    favicon_url: Optional[str] = None

    @field_validator("logo_url")
    @classmethod
    def validate_logo_url(cls, v: str) -> str:
        pattern = r"^https?://[^\s/$.?#]+\.[^\s]*$"
        if not re.match(pattern, v):
            raise ValueError("logo_url 必须是有效的 HTTP(S) URL")
        if len(v) > 512:
            raise ValueError("logo_url 长度不能超过 512 字符")
        return v

    @field_validator("platform_name")
    @classmethod
    def validate_platform_name(cls, v: str) -> str:
        if not v or len(v.strip()) == 0:
            raise ValueError("platform_name 不能为空")
        if len(v) > 128:
            raise ValueError("platform_name 长度不能超过 128 字符")
        return v.strip()

    @field_validator("favicon_url")
    @classmethod
    def validate_favicon_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        pattern = r"^https?://[^\s/$.?#]+\.[^\s]*$"
        if not re.match(pattern, v):
            raise ValueError("favicon_url 必须是有效的 HTTP(S) URL")
        if len(v) > 512:
            raise ValueError("favicon_url 长度不能超过 512 字符")
        return v

    @field_validator("platform_subtitle")
    @classmethod
    def validate_platform_subtitle(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 256:
            raise ValueError("platform_subtitle 长度不能超过 256 字符")
        return v


def get_platform_settings_service(db=Depends(get_db)):
    return PlatformSettingsService(db)


@router.get("/")
async def get_platform_settings(
    svc: PlatformSettingsService = Depends(get_platform_settings_service),
    current_user=Depends(get_current_user),
):
    """获取平台设置（任意登录用户可读）"""
    settings = svc.get_or_initialize()
    return settings.to_dict()


@router.put("/")
async def update_platform_settings(
    request: PlatformSettingsRequest,
    svc: PlatformSettingsService = Depends(get_platform_settings_service),
    current_user=Depends(get_current_user),
):
    """更新平台设置（仅 admin 可写）"""
    # 权限校验：仅 admin 可修改
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可修改平台设置")

    settings = svc.put_settings(
        platform_name=request.platform_name,
        platform_subtitle=request.platform_subtitle,
        logo_url=request.logo_url,
        favicon_url=request.favicon_url,
    )
    return settings.to_dict()
