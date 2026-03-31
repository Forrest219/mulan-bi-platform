"""
认证 API
"""
import os
import sys
from pathlib import Path
from typing import Optional

import jwt
from fastapi import APIRouter, HTTPException, Response, Request
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from auth import auth_service

router = APIRouter()

# Session 签名密钥（从环境变量获取）
_JWT_SECRET = os.environ.get("SESSION_SECRET")
if not _JWT_SECRET:
    raise RuntimeError("SESSION_SECRET environment variable must be set")
_JWT_ALGORITHM = "HS256"


def _create_session_token(user_id: int, username: str, role: str) -> str:
    """创建带签名的 JWT session token"""
    payload = {"sub": str(user_id), "username": username, "role": role}
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def _decode_session_token(token: str) -> Optional[dict]:
    """验证并解码 session token"""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        return {
            "id": int(payload["sub"]),
            "username": payload["username"],
            "role": payload["role"]
        }
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
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 7  # 7 days
    )

    return LoginResponse(
        success=True,
        message="登录成功",
        user=user
    )


@router.post("/register", response_model=LoginResponse)
async def register(request: RegisterRequest, response: Response):
    """用户注册"""
    if len(request.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少为6位")

    user = auth_service.register(request.email, request.password, request.display_name)

    if not user:
        raise HTTPException(status_code=400, detail="邮箱已被注册或格式无效")

    # 自动登录（使用 JWT）
    token = _create_session_token(user["id"], user["username"], user["role"])
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 7  # 7 days
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
