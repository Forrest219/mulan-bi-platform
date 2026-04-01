"""
认证 API
"""
import os
import sys
import time
from pathlib import Path
from typing import Optional

import jwt
from fastapi import APIRouter, HTTPException, Response, Request
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "backend" / "services"))

from auth import auth_service
from app.core.constants import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_SECONDS, MIN_PASSWORD_LENGTH

router = APIRouter()

_JWT_SECRET = JWT_SECRET
_JWT_ALGORITHM = JWT_ALGORITHM
_JWT_EXPIRE_SECONDS = JWT_EXPIRE_SECONDS


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


class LoginResponse(BaseModel):
    """登录响应"""
    success: bool
    message: str
    user: Optional[dict] = None


def get_session_user(request: Request) -> Optional[dict]:
    """从 session cookie 获取用户信息（JWT 验签）"""
    token = request.cookies.get("session")
    if not token:
        return None
    return _decode_session_token(token)


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response):
    """用户登录"""
    user = auth_service.authenticate(request.username, request.password)

    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = _create_session_token(user["id"], user["username"], user["role"])
    _is_secure = os.environ.get("SECURE_COOKIES", "false").lower() == "true"
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
        message="登录成功",
        user=user
    )


@router.post("/register", response_model=LoginResponse)
async def register(request: RegisterRequest, response: Response):
    """用户注册"""
    if len(request.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail="密码长度至少为6位")

    user = auth_service.register(request.email, request.password, request.display_name)

    if not user:
        raise HTTPException(status_code=400, detail="邮箱已被注册或格式无效")

    # 自动登录（使用 JWT）
    token = _create_session_token(user["id"], user["username"], user["role"])
    _is_secure = os.environ.get("SECURE_COOKIES", "false").lower() == "true"
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
                from logs import logger
                logger.log_operation(
                    operation_type="logout",
                    target=user_info["username"],
                    status="success",
                    operator=user_info["username"]
                )
            except Exception as e:
                # 日志记录失败不影响登出流程
                import logging
                logging.getLogger(__name__).warning(f"登出日志记录失败: {e}")

    response.delete_cookie("session")
    return {"success": True, "message": "已登出"}


@router.get("/me")
async def get_current_user(request: Request):
    """获取当前登录用户信息"""
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")

    user_info = _decode_session_token(token)
    if not user_info:
        raise HTTPException(status_code=401, detail="无效的会话")

    user = auth_service.get_user(user_info["id"])
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

    return user


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
