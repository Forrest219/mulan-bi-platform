"""
共享常量定义
"""
import os

# JWT 配置
JWT_SECRET = os.environ.get("SESSION_SECRET")
if not JWT_SECRET:
    raise RuntimeError("SESSION_SECRET environment variable must be set")

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = 86400 * 7  # 7 天（Access Token 有效期）

# Refresh Token 配置
REFRESH_TOKEN_COOKIE_NAME = "refresh_token"
REFRESH_TOKEN_EXPIRE_SECONDS = 86400 * 30  # 30 天（Sliding Window）

# 用户角色
VALID_ROLES = ["admin", "data_admin", "analyst", "user"]

# 密码策略
MIN_PASSWORD_LENGTH = 6
