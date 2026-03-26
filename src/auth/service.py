"""认证服务"""
from datetime import datetime
from typing import Optional, Dict, Any, List
import hashlib
import secrets

from .models import UserDatabase, User


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
        "user_management"
    ]

    # 权限标签映射
    PERMISSION_LABELS = {
        "ddl_check": "DDL 规范检查",
        "ddl_generator": "DDL 生成器",
        "database_monitor": "数据库监控",
        "rule_config": "规则配置",
        "scan_logs": "扫描日志",
        "user_management": "用户管理",
    }

    def _ensure_admin(self):
        """确保存在管理员账户"""
        admin = self._db.get_user_by_username("admin")
        if not admin:
            self._db.create_user(
                username="admin",
                password_hash=self.hash_password("admin123"),
                role="admin",
                display_name="管理员",
                email="admin@mulan.local",  # 管理员邮箱
                permissions=self.ALL_PERMISSIONS  # admin 拥有所有权限
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

    def create_user(self, username: str, password: str, role: str = "user", display_name: str = None, email: str = None, permissions: list = None, group_ids: list = None) -> Optional[Dict[str, Any]]:
        """创建用户（管理员）"""
        existing = self._db.get_user_by_username(username)
        if existing:
            return None

        # 如果没有指定权限，默认给空权限列表
        if permissions is None:
            permissions = []

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
            role="user",
            display_name=display_name,
            email=email,
            permissions=[]
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
