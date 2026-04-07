"""认证服务"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import hashlib
import secrets

from .models import UserDatabase, User

# Refresh Token 配置
_REFRESH_TOKEN_EXPIRE_DAYS = 30  # 30 天有效期


class AuthService:
    """认证服务 - 单例模式"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._db = UserDatabase()
            cls._instance._ensure_admin()
        return cls._instance

    # 定义所有可用权限
    ALL_PERMISSIONS = [
        "ddl_check",
        "ddl_generator",
        "database_monitor",
        "rule_config",
        "scan_logs",
        "user_management",
        "tableau",
        "llm"
    ]

    # 权限标签映射
    PERMISSION_LABELS = {
        "ddl_check": "DDL 规范检查",
        "ddl_generator": "DDL 生成器",
        "database_monitor": "数据库监控",
        "rule_config": "规则配置",
        "scan_logs": "扫描日志",
        "user_management": "用户管理",
        "tableau": "Tableau 资产",
        "llm": "LLM 管理",
    }

    # 角色定义
    ROLE_ADMIN = "admin"
    ROLE_DATA_ADMIN = "data_admin"   # 数据管理员 - 数据域的 admin
    ROLE_ANALYST = "analyst"         # 业务分析师 - 只读
    ROLE_USER = "user"               # 普通用户

    # 角色标签映射
    ROLE_LABELS = {
        ROLE_ADMIN: "管理员",
        ROLE_DATA_ADMIN: "数据管理员",
        ROLE_ANALYST: "业务分析师",
        ROLE_USER: "普通用户",
    }

    # 角色默认权限
    ROLE_DEFAULT_PERMISSIONS = {
        ROLE_ADMIN: ALL_PERMISSIONS,
        ROLE_DATA_ADMIN: ["database_monitor", "ddl_check", "rule_config", "scan_logs", "tableau", "llm"],
        ROLE_ANALYST: ["scan_logs", "tableau"],
        ROLE_USER: [],
    }

    def _ensure_admin(self):
        """确保存在管理员账户（从环境变量读取账号密码）"""
        from services.common.settings import get_admin_username, get_admin_password
        admin_username = get_admin_username()
        admin_password = get_admin_password()

        if not admin_password:
            # 未配置管理员密码时跳过自动创建（生产模式）
            return

        existing = self._db.get_user_by_username(admin_username)
        if existing:
            return

        self._db.create_user(
            username=admin_username,
            password_hash=self.hash_password(admin_password),
            role="admin",
            display_name="管理员",
            email="admin@mulan.local",
            permissions=self.ALL_PERMISSIONS
        )

    def hash_password(self, password: str) -> str:
        """哈希密码 - 使用 PBKDF2"""
        salt = secrets.token_hex(16)
        hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
        return f"{salt}${hash_obj.hex()}"

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        try:
            salt, stored_hash = hashed_password.split('$')
            hash_obj = hashlib.pbkdf2_hmac('sha256', plain_password.encode('utf-8'), salt.encode('utf-8'), 100000)
            return hash_obj.hex() == stored_hash
        except Exception:
            return False

    def authenticate(self, username_or_email: str, password: str) -> Optional[Dict[str, Any]]:
        """验证用户登录（支持用户名或邮箱）"""
        # 优先通过邮箱查找
        user = self._db.get_user_by_email(username_or_email)
        # 如果没找到，尝试用户名
        if not user:
            user = self._db.get_user_by_username(username_or_email)
        if not user:
            return None
        if not user.is_active:
            return None
        if not self.verify_password(password, user.password_hash):
            return None

        # 更新最后登录时间
        user.last_login = datetime.now()
        self._db.update_user(user)

        return user.to_dict()

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """获取用户信息"""
        user = self._db.get_user(user_id)
        return user.to_dict() if user else None

    def get_users(self, role: str = None) -> list:
        """获取用户列表"""
        users = self._db.get_users(role=role)
        return [u.to_dict() for u in users]

    def create_user(self, username: str, password: str, role: str = None, display_name: str = None, email: str = None, permissions: list = None, group_ids: list = None) -> Optional[Dict[str, Any]]:
        """创建用户（管理员）"""
        existing = self._db.get_user_by_username(username)
        if existing:
            return None

        # 如果没有指定角色，默认普通用户
        if role is None:
            role = self.ROLE_USER

        # 如果没有指定权限，使用角色默认权限
        if permissions is None:
            permissions = self.ROLE_DEFAULT_PERMISSIONS.get(role, [])

        user = self._db.create_user(
            username=username,
            password_hash=self.hash_password(password),
            role=role,
            display_name=display_name or username,
            email=email,
            permissions=permissions
        )

        # 添加到组
        if group_ids:
            for group_id in group_ids:
                self._db.add_user_to_group(user.id, group_id)

        return user.to_dict()

    def register(self, email: str, password: str, display_name: str = None) -> Optional[Dict[str, Any]]:
        """用户注册"""
        import re
        # 验证邮箱格式
        if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
            return None

        # 检查邮箱是否已存在
        existing = self._db.get_user_by_email(email)
        if existing:
            return None

        # 从邮箱提取用户名部分作为默认显示名
        if not display_name:
            display_name = email.split('@')[0]

        # 生成唯一username (邮箱@前的部分 + 随机后缀)
        base_username = email.split('@')[0]
        username = base_username
        counter = 1
        while self._db.get_user_by_username(username):
            username = f"{base_username}{counter}"
            counter += 1

        user = self._db.create_user(
            username=username,
            password_hash=self.hash_password(password),
            role=self.ROLE_USER,
            display_name=display_name,
            email=email,
            permissions=self.ROLE_DEFAULT_PERMISSIONS.get(self.ROLE_USER, [])
        )

        return user.to_dict()

    def update_user_role(self, user_id: int, role: str) -> bool:
        """更新用户角色"""
        user = self._db.get_user(user_id)
        if not user:
            return False
        user.role = role
        self._db.update_user(user)
        return True

    def toggle_user_active(self, user_id: int) -> bool:
        """切换用户激活状态"""
        user = self._db.get_user(user_id)
        if not user:
            return False
        user.is_active = not user.is_active
        self._db.update_user(user)
        return True

    def update_user_permissions(self, user_id: int, permissions: list) -> bool:
        """更新用户权限"""
        # 验证权限列表中的每个权限都是有效的
        for perm in permissions:
            if perm not in self.ALL_PERMISSIONS:
                return False
        return self._db.update_user_permissions(user_id, permissions)

    def get_effective_permissions(self, user_id: int) -> List[str]:
        """获取用户实际生效的权限（角色默认 + 个人额外）"""
        user = self._db.get_user(user_id)
        if not user:
            return []
        # 角色默认权限
        role_perms = self.ROLE_DEFAULT_PERMISSIONS.get(user.role, [])
        # 个人额外权限
        personal_perms = user.permissions or []
        return list(set(role_perms + personal_perms))

    def has_permission(self, user_id: int, permission: str) -> bool:
        """检查用户是否拥有指定权限"""
        if not user_id:
            return False
        user = self._db.get_user(user_id)
        if not user:
            return False
        # admin 拥有所有权限
        if user.role == self.ROLE_ADMIN:
            return True
        # 合并角色默认权限和个人权限
        effective = self.get_effective_permissions(user_id)
        return permission in effective

    def delete_user(self, user_id: int) -> bool:
        """删除用户"""
        return self._db.delete_user(user_id)

    # ========== 用户组管理 ==========

    def create_group(self, name: str, description: str = None, permissions: list = None) -> Optional[Dict[str, Any]]:
        """创建用户组"""
        existing = self._db.get_group_by_name(name)
        if existing:
            return None

        group = self._db.create_group(name=name, description=description)

        # 设置组权限
        if permissions:
            self._db.set_group_permissions(group.id, permissions)

        return group.to_dict(include_members=True)

    def get_group(self, group_id: int) -> Optional[Dict[str, Any]]:
        """获取用户组"""
        group = self._db.get_group(group_id)
        if group:
            return group.to_dict(include_members=True)
        return None

    def get_groups(self) -> list:
        """获取所有用户组"""
        groups = self._db.get_groups()
        return [g.to_dict() for g in groups]

    def update_group(self, group_id: int, name: str = None, description: str = None) -> bool:
        """更新用户组"""
        return self._db.update_group(group_id, name=name, description=description)

    def delete_group(self, group_id: int) -> bool:
        """删除用户组"""
        return self._db.delete_group(group_id)

    def add_user_to_group(self, user_id: int, group_id: int) -> bool:
        """添加用户到组"""
        return self._db.add_user_to_group(user_id, group_id)

    def remove_user_from_group(self, user_id: int, group_id: int) -> bool:
        """从组移除用户"""
        return self._db.remove_user_from_group(user_id, group_id)

    def get_group_members(self, group_id: int) -> list:
        """获取组成员"""
        members = self._db.get_group_members(group_id)
        return [m.to_dict() for m in members]

    def get_user_groups(self, user_id: int) -> list:
        """获取用户所属的组"""
        groups = self._db.get_user_groups(user_id)
        return [g.to_dict() for g in groups]

    def set_group_permissions(self, group_id: int, permissions: List[str]) -> bool:
        """设置组权限"""
        # 验证权限
        for perm in permissions:
            if perm not in self.ALL_PERMISSIONS:
                return False
        return self._db.set_group_permissions(group_id, permissions)

    def get_group_permissions(self, group_id: int) -> List[str]:
        """获取组权限"""
        return self._db.get_group_permissions(group_id)

    def get_user_permissions_with_groups(self, user_id: int) -> Dict[str, Any]:
        """获取用户的所有权限（包含组继承）"""
        user = self._db.get_user(user_id)
        if not user:
            return {"personal": [], "from_groups": [], "all": []}

        personal = user.permissions or []
        from_groups = self._db.get_user_permissions_from_groups(user_id)
        all_perms = list(set(personal + from_groups))

        return {
            "personal": personal,
            "from_groups": from_groups,
            "all": all_perms
        }

    def get_all_available_permissions(self) -> List[Dict[str, str]]:
        """获取所有可用权限定义"""
        return self._db.get_all_permissions()

    # ========== 用户标签 ==========

    # ========== MFA（TOTP）管理 ==========

    def generate_mfa_secret(self, user_id: int) -> Optional[tuple]:
        """
        为用户生成 MFA TOTP Secret 和备用码。

        返回 (secret, qr_uri, backup_codes_plaintext) 元组。
        调用方负责加密存储 secret 和 backup codes。
        """
        user = self._db.get_user(user_id)
        if not user:
            return None

        import pyotp
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        issuer = "MulanBI"
        qr_uri = totp.provisioning_uri(name=user.email, issuer_name=issuer)

        # 生成 8 个备用码（一次性密码）
        import secrets
        backup_codes = [secrets.token_hex(4).upper() for _ in range(8)]

        return secret, qr_uri, backup_codes

    def _encrypt_mfa_field(self, plaintext: str) -> str:
        """使用 LLM CryptoHelper 加密 MFA 敏感字段"""
        from app.core.crypto import get_llm_crypto
        crypto = get_llm_crypto()
        return crypto.encrypt(plaintext.encode()).decode()

    def _decrypt_mfa_field(self, ciphertext: str) -> str:
        """解密 MFA 敏感字段"""
        from app.core.crypto import get_llm_crypto
        crypto = get_llm_crypto()
        return crypto.decrypt(ciphertext.encode()).decode()

    def verify_mfa_code(self, user_id: int, code: str) -> bool:
        """
        验证用户输入的 TOTP MFA Code。

        也检查是否为未使用的备用码，若是则标记为已使用。
        """
        encrypted_secret = self._db.get_mfa_secret_encrypted(user_id)
        if not encrypted_secret:
            return False

        try:
            secret = self._decrypt_mfa_field(encrypted_secret)
        except Exception:
            return False

        import pyotp

        # 验证 TOTP（允许 ±1 窗口，防止时钟漂移）
        totp = pyotp.TOTP(secret)
        if totp.verify(code, valid_window=1):
            return True

        # 检查备用码
        encrypted_backup = self._db.get_backup_codes_encrypted(user_id)
        if encrypted_backup:
            try:
                backup_list = self._decrypt_mfa_field(encrypted_backup)
                import json
                codes: list = json.loads(backup_list)
                if code.upper() in codes:
                    # 标记备用码为已使用（替换为 None）
                    codes = [c if c != code.upper() else None for c in codes]
                    new_encrypted = self._encrypt_mfa_field(json.dumps(codes))
                    self._db.enable_mfa(user_id, encrypted_secret, new_encrypted)
                    return True
            except Exception:
                pass

        return False

    def setup_mfa(self, user_id: int, code: str) -> tuple:
        """
        设置 MFA：验证初始 Code 后启用 MFA。

        返回 (success, secret_or_error_message)
        success=True 时返回 secret（明文，仅此时展示给用户）
        """
        # 生成 secret（如果还没有）
        result = self.generate_mfa_secret(user_id)
        if not result:
            return False, "用户不存在"
        secret, qr_uri, backup_codes_plaintext = result

        # 验证输入的 code 是否正确
        encrypted_secret = self._encrypt_mfa_field(secret)
        # 临时存储 secret 以便验证
        self._db.set_mfa_secret(user_id, encrypted_secret)

        if not self.verify_mfa_code(user_id, code):
            # 验证失败，清除临时 secret
            self._db.set_mfa_secret(user_id, "")
            return False, "验证码不正确，请确认 authenticator 应用已同步"

        # 验证通过，启用 MFA
        import json
        backup_codes_encrypted = self._encrypt_mfa_field(json.dumps(backup_codes_plaintext))
        self._db.enable_mfa(user_id, encrypted_secret, backup_codes_encrypted)

        return True, {"secret": secret, "qr_uri": qr_uri, "backup_codes": backup_codes_plaintext}

    def disable_mfa(self, user_id: int, password: str, code: str) -> tuple:
        """
        禁用 MFA：验证密码 + MFA Code 后禁用。

        返回 (success, message)
        """
        # 验证密码
        user = self._db.get_user(user_id)
        if not user:
            return False, "用户不存在"
        if not self.verify_password(password, user.password_hash):
            return False, "密码不正确"

        # 验证 MFA Code
        if not self.verify_mfa_code(user_id, code):
            return False, "MFA 验证码不正确"

        self._db.disable_mfa(user_id)
        return True, "MFA 已禁用"

    def create_refresh_token(
        self,
        user_id: int,
        device_fingerprint: str = None,
    ) -> str:
        """
        创建并存储 refresh token，返回原始 token（供调用方写入 HTTP-only cookie）。

        存储：token_hash（SHA-256）而非原始 token，防止数据库泄漏后被滥用。
        """
        raw_token = secrets.token_urlsafe(32)  # 256-bit random token
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = datetime.utcnow() + timedelta(days=_REFRESH_TOKEN_EXPIRE_DAYS)
        self._db.create_refresh_token(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            device_fingerprint=device_fingerprint,
        )
        return raw_token

    def verify_refresh_token(self, raw_token: str) -> Optional[Dict[str, Any]]:
        """
        验证 refresh token，返回有效用户信息。

        流程：raw_token → SHA-256 hash → 查询数据库 → 验证未撤销且未过期
        """
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        token_record = self._db.verify_refresh_token(token_hash)
        if not token_record:
            return None
        user = self._db.get_user(token_record.user_id)
        if not user or not user.is_active:
            return None
        return user.to_dict()

    def revoke_refresh_token(self, raw_token: str) -> bool:
        """撤销指定的 refresh token（logout 时调用）"""
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        return self._db.revoke_refresh_token(token_hash)

    def revoke_all_user_refresh_tokens(self, user_id: int) -> int:
        """撤销用户所有 refresh token（"退出所有设备"功能）"""
        return self._db.revoke_all_user_refresh_tokens(user_id)

    # ========== 用户标签 ==========

    def get_user_tag(self, user_id: int) -> Dict[str, Any]:
        """获取用户标签"""
        user = self._db.get_user(user_id)
        if not user:
            return {"tag": "未知", "emoji": "❓", "color": "gray", "days_since_login": -1}

        if not user.last_login:
            return {"tag": "僵尸", "emoji": "💀", "color": "red", "days_since_login": -1}

        diff = datetime.now() - user.last_login
        days = diff.days

        if days <= 7:
            return {"tag": "活跃", "emoji": "🌟", "color": "emerald", "days_since_login": days}
        elif days <= 30:
            return {"tag": "正常", "emoji": "😊", "color": "blue", "days_since_login": days}
        elif days <= 90:
            return {"tag": "冷门", "emoji": "😴", "color": "orange", "days_since_login": days}
        else:
            return {"tag": "潜水", "emoji": "👻", "color": "gray", "days_since_login": days}

    def get_users_with_tags(self) -> list:
        """获取所有用户并附带标签"""
        users = self.get_users()
        result = []
        for user in users:
            tag_info = self.get_user_tag(user["id"])
            user["tag"] = tag_info["tag"]
            user["tag_emoji"] = tag_info["emoji"]
            user["tag_color"] = tag_info["color"]
            user["days_since_login"] = tag_info["days_since_login"]
            result.append(user)
        return result


# 全局服务实例
auth_service = AuthService()
