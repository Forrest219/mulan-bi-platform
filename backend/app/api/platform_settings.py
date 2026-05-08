"""平台设置 API"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
import re

from app.core.dependencies import get_current_user
from app.core.database import get_db
from services.platform_settings import PlatformSettingsService
from services.common.settings import get_smtp_config
from services.audit.audit_service import log_action

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
    log_action(current_user.get("id"), current_user.get("username", ""), "update", "platform_settings", "global",
               after_state={"platform_name": request.platform_name, "logo_url": request.logo_url})
    return settings.to_dict()


# ──────────────────────────────────────────────────────────────
# SMTP 邮件配置（存储在 platform_settings.extra_settings["smtp"]）
# ──────────────────────────────────────────────────────────────

class SmtpConfigRequest(BaseModel):
    """SMTP 配置请求"""
    smtp_host: str
    smtp_port: int = 465
    smtp_user: str
    smtp_password: str
    smtp_from_addr: str
    smtp_use_tls: bool = True

    @field_validator("smtp_host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        if not v or len(v.strip()) == 0:
            raise ValueError("SMTP 主机不能为空")
        return v.strip()

    @field_validator("smtp_port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if v <= 0 or v > 65535:
            raise ValueError("SMTP 端口必须在 1-65535 之间")
        return v

    @field_validator("smtp_user")
    @classmethod
    def validate_user(cls, v: str) -> str:
        if not v or len(v.strip()) == 0:
            raise ValueError("SMTP 用户名不能为空")
        return v.strip()

    @field_validator("smtp_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) == 0:
            raise ValueError("SMTP 密码不能为空")
        return v

    @field_validator("smtp_from_addr")
    @classmethod
    def validate_from_addr(cls, v: str) -> str:
        pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        if not re.match(pattern, v):
            raise ValueError("发件人地址必须是有效邮箱格式")
        return v.strip()


class SmtpConfigResponse(BaseModel):
    """SMTP 配置响应（密码隐藏）"""
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str  # 返回时隐藏为 ***，前端通过 has_password 判断是否已配置
    smtp_from_addr: str
    smtp_use_tls: bool
    is_configured: bool  # DB 是否有记录（用于前端区分"未配置"和"已配置"）


class SmtpTestRequest(BaseModel):
    """测试邮件请求"""
    recipient_email: str

    @field_validator("recipient_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        if not re.match(pattern, v):
            raise ValueError("收件人邮箱格式无效")
        return v.strip()


def _load_smtp_config_with_fallback(svc: PlatformSettingsService) -> dict:
    """
    合并配置：优先读 DB，若无则 fallback 到 .env。
    返回的 dict 包含 is_configured 标记。
    """
    db_config = svc.get_smtp_config_from_db()
    if db_config:
        return {**db_config, "is_configured": True}

    # Fallback 到 .env
    env_config = get_smtp_config()
    return {
        "smtp_host": env_config.get("host") or "",
        "smtp_port": env_config.get("port") or 465,
        "smtp_user": env_config.get("user") or "",
        "smtp_password": env_config.get("password") or "",
        "smtp_from_addr": env_config.get("from_addr") or "",
        "smtp_use_tls": env_config.get("use_tls", True),
        "is_configured": False,
    }


@router.get("/smtp")
async def read_smtp_config(
    svc: PlatformSettingsService = Depends(get_platform_settings_service),
    current_user=Depends(get_current_user),
):
    """
    获取当前 SMTP 配置（密码字段隐藏）。仅 admin 可读。
    优先返回 DB 配置，不存在则返回 .env 配置（只读标记）。
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看邮件设置")

    cfg = _load_smtp_config_with_fallback(svc)
    # 隐藏密码
    cfg["smtp_password"] = "***" if cfg.get("smtp_password") else ""
    return cfg


@router.put("/smtp")
async def update_smtp_config(
    request: SmtpConfigRequest,
    svc: PlatformSettingsService = Depends(get_platform_settings_service),
    current_user=Depends(get_current_user),
):
    """保存 SMTP 配置（仅 admin）"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可修改邮件设置")

    smtp_config = {
        "smtp_host": request.smtp_host,
        "smtp_port": request.smtp_port,
        "smtp_user": request.smtp_user,
        "smtp_password": request.smtp_password,
        "smtp_from_addr": request.smtp_from_addr,
        "smtp_use_tls": request.smtp_use_tls,
    }
    svc.put_smtp_config(smtp_config)
    log_action(current_user.get("id"), current_user.get("username", ""), "update", "smtp_config", "global",
               after_state={"smtp_host": request.smtp_host, "smtp_user": request.smtp_user})
    # 返回（密码隐藏）
    return {
        **smtp_config,
        "smtp_password": "***",
        "is_configured": True,
    }


@router.post("/smtp/test")
async def test_smtp_config(
    request: SmtpTestRequest,
    svc: PlatformSettingsService = Depends(get_platform_settings_service),
    current_user=Depends(get_current_user),
):
    """发送测试邮件（仅 admin）"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可发送测试邮件")

    import smtplib
    import uuid

    cfg = _load_smtp_config_with_fallback(svc)

    host = cfg.get("smtp_host") or cfg.get("host")
    port = cfg.get("smtp_port") or 465
    user = cfg.get("smtp_user") or cfg.get("user")
    password = cfg.get("smtp_password") or cfg.get("password")
    from_addr = cfg.get("smtp_from_addr") or cfg.get("from_addr")
    use_tls = cfg.get("smtp_use_tls", True)

    if not host or not user or not password or not from_addr:
        raise HTTPException(status_code=400, detail="SMTP 配置不完整，请先保存邮件设置")

    trace_id = str(uuid.uuid4())[:8]

    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            if use_tls:
                server.starttls()
        server.login(user, password)

        from email.mime.text import MIMEText
        msg = MIMEText("这是一封来自木兰 BI 平台的测试邮件，证明邮件发送功能正常工作。\n\n如果您收到此邮件，说明 SMTP 配置正确。", "plain", "utf-8")
        msg["Subject"] = "【木兰 BI 平台】测试邮件"
        msg["From"] = from_addr
        msg["To"] = request.recipient_email

        server.sendmail(from_addr, [request.recipient_email], msg.as_bytes())
        server.quit()
        return {"success": True, "message": f"测试邮件已发送到 {request.recipient_email}"}
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=400, detail="SMTP 认证失败，请检查用户名和密码")
    except smtplib.SMTPRecipientsRefused:
        raise HTTPException(status_code=400, detail=f"收件人地址 {request.recipient_email} 被服务器拒绝")
    except smtplib.SMTPServerDisconnected:
        raise HTTPException(status_code=400, detail="SMTP 服务器连接断开，请检查主机和端口")
    except smtplib.SMTPException as e:
        raise HTTPException(status_code=400, detail=f"SMTP 错误: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"邮件发送失败: {e}")


# ──────────────────────────────────────────────────────────────
# 邮件发送记录（仅 admin）
# ──────────────────────────────────────────────────────────────

@router.get("/email-logs")
async def get_email_send_logs(
    page: int = 1,
    page_size: int = 50,
    svc: PlatformSettingsService = Depends(get_platform_settings_service),
    current_user=Depends(get_current_user),
):
    """获取邮件发送记录（最近 page_size 条，仅 admin）"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看发送记录")
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 50
    return svc.get_email_send_logs(page=page, page_size=page_size)
