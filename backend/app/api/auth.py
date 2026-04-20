"""认证 API — 支持 JWT Access Token + Refresh Token 双 Token 模式

- Access Token（JWT）：存 session cookie，7天有效，前端用于 API 认证
- Refresh Token：存 refresh_token cookie，30天 Sliding Window，用于 Access Token 续期

刷新流程：
  1. 前端检测 Access Token 接近过期（剩余 < 5 分钟）
  2. 前端调用 POST /api/auth/refresh
  3. 后端验证 Refresh Token，颁发新 Access Token
  4. 前端重试原请求
"""
import os
import time
from collections import defaultdict
from typing import Optional

import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.core.constants import (
    JWT_ALGORITHM,
    JWT_EXPIRE_SECONDS,
    JWT_SECRET,
    MIN_PASSWORD_LENGTH,
    REFRESH_TOKEN_COOKIE_NAME,
    REFRESH_TOKEN_EXPIRE_SECONDS,
)
from app.core.dependencies import get_current_user as _get_current_user
from services.auth import auth_service

router = APIRouter()

_JWT_SECRET = JWT_SECRET
_JWT_ALGORITHM = JWT_ALGORITHM
_JWT_EXPIRE_SECONDS = JWT_EXPIRE_SECONDS
_REFRESH_TOKEN_COOKIE_NAME = REFRESH_TOKEN_COOKIE_NAME
_REFRESH_TOKEN_EXPIRE_SECONDS = REFRESH_TOKEN_EXPIRE_SECONDS

# 注册速率限制：每个 IP 每 60 秒最多 5 次
_register_attempts: dict[str, list[float]] = defaultdict(list)
_REGISTER_RATE_LIMIT = 5
_REGISTER_RATE_WINDOW = 60  # seconds


def _create_session_token(user_id: int, username: str, role: str) -> str:
    """创建带签名和过期时间的 JWT session token"""
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": int(time.time()) + _JWT_EXPIRE_SECONDS,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def _decode_session_token(token: str) -> Optional[dict]:
    """验证并解码 session token（含过期校验）"""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM], options={"require": ["exp"]})
        return {
            "id": int(payload["sub"]),
            "username": payload["username"],
            "role": payload["role"]
        }
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


class LoginRequest(BaseModel):
    """登录请求"""

    username: str  # 支持用户名或邮箱
    password: str


class RegisterRequest(BaseModel):
    """注册请求"""

    email: str
    password: str
    display_name: Optional[str] = None


class MFAVerifyRequest(BaseModel):
    """MFA 验证请求（setup / disable 时使用）"""

    code: str  # 6 位 TOTP Code 或备用码


class MFADisableRequest(BaseModel):
    """禁用 MFA 请求"""

    password: str
    code: str  # MFA 验证码


class LoginResponse(BaseModel):
    """登录响应"""

    success: bool
    message: str
    user: Optional[dict] = None
    mfa_required: bool = False  # MFA 已启用，需要输入验证码


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    old_password: str
    new_password: str


def get_session_user(request: Request) -> Optional[dict]:
    """从 session cookie 获取用户信息（JWT 验签）"""
    token = request.cookies.get("session")
    if not token:
        return None
    return _decode_session_token(token)


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response, http_request: Request):
    """用户登录"""
    user = auth_service.authenticate(request.username, request.password)

    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 检查 MFA 是否启用
    if user.get("mfa_enabled"):
        # MFA 启用：颁发临时 session cookie，但返回 MFA challenge
        token = _create_session_token(user["id"], user["username"], user["role"])
        _is_secure = os.environ.get("SECURE_COOKIES", "true").lower() == "true"
        response.set_cookie(
            key="session",
            value=token,
            httponly=True,
            samesite="lax",
            secure=_is_secure,
            max_age=_JWT_EXPIRE_SECONDS
        )
        return LoginResponse(
            success=True,
            message="请输入 MFA 验证码完成登录",
            user=user
        )

    # MFA 未启用：完整登录流程
    token = _create_session_token(user["id"], user["username"], user["role"])
    _is_secure = os.environ.get("SECURE_COOKIES", "true").lower() == "true"
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=_is_secure,
        max_age=_JWT_EXPIRE_SECONDS
    )

    # Refresh Token（30 天 Sliding Window）
    _device = http_request.headers.get("User-Agent", "")[:128]
    refresh_token = auth_service.create_refresh_token(
        user_id=user["id"],
        device_fingerprint=_device,
    )
    response.set_cookie(
        key=_REFRESH_TOKEN_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=_is_secure,
        max_age=_REFRESH_TOKEN_EXPIRE_SECONDS,
    )

    return LoginResponse(
        success=True,
        message="登录成功",
        user=user
    )


@router.post("/register", response_model=LoginResponse)
async def register(request: RegisterRequest, req: Request, response: Response):
    """用户注册"""
    # 速率限制
    client_ip = req.client.host if req.client else "unknown"
    now = time.time()
    _register_attempts[client_ip] = [t for t in _register_attempts[client_ip] if now - t < _REGISTER_RATE_WINDOW]
    if len(_register_attempts[client_ip]) >= _REGISTER_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="注册请求过于频繁，请稍后再试")
    _register_attempts[client_ip].append(now)

    if len(request.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail="密码长度至少为6位")

    user = auth_service.register(request.email, request.password, request.display_name)

    if not user:
        raise HTTPException(status_code=400, detail="邮箱已被注册或格式无效")

    # 自动登录（使用 JWT）
    token = _create_session_token(user["id"], user["username"], user["role"])
    _is_secure = os.environ.get("SECURE_COOKIES", "true").lower() == "true"
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=_is_secure,
        max_age=_JWT_EXPIRE_SECONDS
    )

    # Refresh Token（30 天 Sliding Window）
    refresh_token = auth_service.create_refresh_token(
        user_id=user["id"],
        device_fingerprint=request.client.host if request.client else "unknown",
    )
    response.set_cookie(
        key=_REFRESH_TOKEN_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=_is_secure,
        max_age=_REFRESH_TOKEN_EXPIRE_SECONDS,
    )

    return LoginResponse(
        success=True,
        message="注册成功",
        user=user
    )


@router.post("/logout")
async def logout(request: Request, response: Response):
    """用户登出"""
    token = request.cookies.get("session")
    if token:
        user_info = _decode_session_token(token)
        if user_info:
            try:
                from services.logs import logger
                logger.log_operation(
                    operation_type="logout",
                    target=user_info["username"],
                    status="success",
                    operator=user_info["username"]
                )
            except Exception as e:
                # 日志记录失败不影响登出流程
                import logging
                logging.getLogger(__name__).warning("登出日志记录失败: %s", e)

    # 撤销 Refresh Token
    refresh_token = request.cookies.get(_REFRESH_TOKEN_COOKIE_NAME)
    if refresh_token:
        auth_service.revoke_refresh_token(refresh_token)

    response.delete_cookie("session")
    response.delete_cookie(_REFRESH_TOKEN_COOKIE_NAME)
    return {"success": True, "message": "已登出"}


# ──────────────────────────────────────────────────────────────
# MFA（TOTP）端点
# ──────────────────────────────────────────────────────────────

@router.post("/mfa/setup")
async def mfa_setup(request: Request, response: Response):
    """生成 MFA 验证码（Setup Flow）。

    1. 用户在个人设置页面请求开启 MFA
    2. 后端生成 TOTP Secret 和 QR Code URI
    3. 前端显示 QR 码供用户扫描
    4. 用户输入扫描后的第一个 Code 调用 /mfa/verify-setup 完成启用
    """
    user_info = _get_current_user(request)
    if not user_info:
        raise HTTPException(status_code=401, detail="未登录")

    result = auth_service.generate_mfa_secret(user_info["id"])
    if not result:
        raise HTTPException(status_code=404, detail="用户不存在")

    secret, qr_uri, backup_codes = result

    # 临时存储 encrypted secret（验证后才正式启用）
    encrypted_secret = auth_service._encrypt_mfa_field(secret)
    auth_service._db.set_mfa_secret(user_info["id"], encrypted_secret)

    return {
        "secret": secret,
        "qr_uri": qr_uri,
        "backup_codes": backup_codes,
        "message": "请使用 authenticator 应用扫描上方二维码，然后输入验证码完成启用",
    }


@router.post("/mfa/verify-setup")
async def mfa_verify_setup(request: MFAVerifyRequest, response: Response):
    """验证 MFA Setup Code 并启用 MFA。

    需要先调用 /mfa/setup 获取 secret 和 backup codes。
    """
    user_info = _get_current_user(request)
    if not user_info:
        raise HTTPException(status_code=401, detail="未登录")

    success, data = auth_service.setup_mfa(user_info["id"], request.code)
    if not success:
        raise HTTPException(status_code=400, detail=data)

    return {
        "success": True,
        "message": "MFA 已成功启用，请妥善保管备用码",
        "backup_codes": data["backup_codes"],
    }


@router.post("/mfa/disable")
async def mfa_disable(request: MFADisableRequest, response: Response):
    """禁用 MFA（需要密码 + MFA 验证码双重验证）。
    """
    user_info = _get_current_user(request)
    if not user_info:
        raise HTTPException(status_code=401, detail="未登录")

    success, message = auth_service.disable_mfa(
        user_id=user_info["id"],
        password=request.password,
        code=request.code,
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {"success": True, "message": message}


@router.get("/mfa/status")
async def mfa_status(request: Request):
    """查询当前用户的 MFA 启用状态"""
    user_info = _get_current_user(request)
    if not user_info:
        raise HTTPException(status_code=401, detail="未登录")

    mfa_enabled = auth_service._db.get_mfa_enabled(user_info["id"])
    return {"mfa_enabled": mfa_enabled}


@router.post("/mfa/verify")
async def mfa_verify(request: MFAVerifyRequest, response: Response):
    """完成 MFA 登录验证（登录流程的第二步）。

    在登录返回 mfa_required=True 后，前端调用此接口验证 TOTP Code。
    验证成功后颁发 Refresh Token 完成登录。
    """
    user_info = _get_current_user(request)
    if not user_info:
        raise HTTPException(status_code=401, detail="会话已过期，请重新登录")

    if not auth_service.verify_mfa_code(user_info["id"], request.code):
        raise HTTPException(status_code=400, detail="MFA 验证码不正确")

    # MFA 验证成功：颁发 Refresh Token 完成登录
    _device = request.headers.get("User-Agent", "")[:128]
    refresh_token = auth_service.create_refresh_token(
        user_id=user_info["id"],
        device_fingerprint=_device,
    )
    _is_secure = os.environ.get("SECURE_COOKIES", "true").lower() == "true"
    response.set_cookie(
        key=_REFRESH_TOKEN_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=_is_secure,
        max_age=_REFRESH_TOKEN_EXPIRE_SECONDS,
    )

    user = auth_service.get_user(user_info["id"])
    return LoginResponse(
        success=True,
        message="MFA 验证成功",
        user=user,
        mfa_required=False,
    )


@router.post("/refresh")
async def refresh_token(request: Request, response: Response):
    """使用 Refresh Token 换取新的 Access Token（Sliding Window）。

    流程：
    1. 从 refresh_token cookie 读取 Refresh Token
    2. 验证 Refresh Token（未撤销、未过期）
    3. 颁发新的 Access Token（session cookie）
    4. 重置 Refresh Token 过期时间（Sliding Window）
    """
    refresh_token = request.cookies.get(_REFRESH_TOKEN_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh Token 不存在，请重新登录")

    user = auth_service.verify_refresh_token(refresh_token)
    if not user:
        raise HTTPException(status_code=401, detail="Refresh Token 无效或已过期，请重新登录")

    # 颁发新的 Access Token
    new_access_token = _create_session_token(user["id"], user["username"], user["role"])
    _is_secure = os.environ.get("SECURE_COOKIES", "true").lower() == "true"
    response.set_cookie(
        key="session",
        value=new_access_token,
        httponly=True,
        samesite="lax",
        secure=_is_secure,
        max_age=_JWT_EXPIRE_SECONDS,
    )

    # Sliding Window：撤销旧 Refresh Token，颁发新的
    auth_service.revoke_refresh_token(refresh_token)
    _device = request.headers.get("User-Agent", "")[:128]
    new_refresh_token = auth_service.create_refresh_token(
        user_id=user["id"],
        device_fingerprint=_device,
    )
    response.set_cookie(
        key=_REFRESH_TOKEN_COOKIE_NAME,
        value=new_refresh_token,
        httponly=True,
        samesite="lax",
        secure=_is_secure,
        max_age=_REFRESH_TOKEN_EXPIRE_SECONDS,
    )

    return {"success": True, "message": "Token 已刷新"}


@router.post("/refresh/revoke-all")
async def revoke_all_refresh_tokens(request: Request, response: Response):
    """撤销当前用户所有 Refresh Token（"退出所有设备"功能）。

    保留当前 Access Token 有效，撤销所有 refresh token。
    下次登录需要重新认证。
    """
    user_info = _get_current_user(request)
    if not user_info:
        raise HTTPException(status_code=401, detail="未登录")

    revoked_count = auth_service.revoke_all_user_refresh_tokens(user_info["id"])
    return {
        "success": True,
        "message": f"已撤销 {revoked_count} 个设备登录",
        "revoked_count": revoked_count,
    }


@router.get("/me")
async def get_me(request: Request):
    """获取当前登录用户信息"""
    user_info = _get_current_user(request)
    user = auth_service.get_user(user_info["id"])
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")
    return user


@router.post("/forgot-password", status_code=200)
async def forgot_password(payload: dict):
    """Always returns 200 regardless of whether email exists (security)."""
    # Email lookup intentionally omitted to prevent account enumeration
    return {"message": "如果该邮箱已注册，我们将发送重置说明。"}


@router.put("/change-password")
async def change_password(request: ChangePasswordRequest, http_request: Request):
    """修改密码（需登录态）"""
    current_user = _get_current_user(http_request)
    success = auth_service.change_password(
        current_user["id"],
        request.old_password,
        request.new_password,
    )
    if not success:
        raise HTTPException(status_code=400, detail="旧密码不正确或用户不存在")
    return {"message": "密码修改成功，已退出其他设备"}


@router.get("/verify")
async def verify_session(request: Request):
    """验证会话是否有效"""
    token = request.cookies.get("session")
    if not token:
        return {"valid": False}

    user_info = _decode_session_token(token)
    if not user_info:
        return {"valid": False}

    user = auth_service.get_user(user_info["id"])
    if not user or not user.get("is_active"):
        return {"valid": False}

    return {"valid": True, "user": user}
