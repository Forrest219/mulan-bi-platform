"""
认证 API
"""
from fastapi import APIRouter, HTTPException, Response, Request
from pydantic import BaseModel
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from auth import auth_service

router = APIRouter()


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
    """从 session cookie 获取用户信息"""
    session = request.cookies.get("session")
    if not session:
        return None

    parts = session.split(":")
    if len(parts) < 3:
        return None

    return {
        "id": int(parts[0]),
        "username": parts[1],
        "role": parts[2]
    }


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response):
    """用户登录"""
    user = auth_service.authenticate(request.username, request.password)

    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 设置 session cookie
    response.set_cookie(
        key="session",
        value=f"{user['id']}:{user['username']}:{user['role']}",
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

    # 自动登录
    response.set_cookie(
        key="session",
        value=f"{user['id']}:{user['username']}:{user['role']}",
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
    session = request.cookies.get("session")
    if session:
        parts = session.split(":")
        if len(parts) >= 2:
            username = parts[1]
            # Log logout operation (optional, skip if logger not available)
            try:
                from logs import logger
                logger.log_operation(
                    operation_type="logout",
                    target=username,
                    status="success",
                    operator=username
                )
            except Exception:
                pass

    response.delete_cookie("session")
    return {"success": True, "message": "已登出"}


@router.get("/me")
async def get_current_user(request: Request):
    """获取当前登录用户信息"""
    session = request.cookies.get("session")
    if not session:
        raise HTTPException(status_code=401, detail="未登录")

    parts = session.split(":")
    if len(parts) < 3:
        raise HTTPException(status_code=401, detail="无效的会话")

    user_id = int(parts[0])

    # 从数据库验证用户仍然有效
    user = auth_service.get_user(user_id)
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

    return user


@router.get("/verify")
async def verify_session(request: Request):
    """验证会话是否有效"""
    session = request.cookies.get("session")
    if not session:
        return {"valid": False}

    parts = session.split(":")
    if len(parts) < 3:
        return {"valid": False}

    user_id = int(parts[0])
    user = auth_service.get_user(user_id)

    if not user or not user.get("is_active"):
        return {"valid": False}

    return {"valid": True, "user": user}
