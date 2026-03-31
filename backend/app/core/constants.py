"""
共享常量定义
"""
import os

# JWT 配置
JWT_SECRET = os.environ.get("SESSION_SECRET")
if not JWT_SECRET:
    raise RuntimeError("SESSION_SECRET environment variable must be set")

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = 86400 * 7  # 7 天

# 用户角色
VALID_ROLES = ["admin", "data_admin", "analyst", "user"]

# 密码策略
MIN_PASSWORD_LENGTH = 6
