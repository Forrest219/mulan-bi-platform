"""用户认证数据模型"""
from datetime import datetime
from typing import Optional, List, Dict, Any
import uuid

from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Table, Text, Index
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from app.core.database import Base, JSONB, sa_func, sa_text # 导入中央配置的 Base, JSONB, func, text

# 关联表：用户-组
user_group_members = Table(
    'auth_user_group_members', # 表名前缀规范化
    Base.metadata,
    Column('user_id', Integer, ForeignKey('auth_users.id'), primary_key=True),
    Column('group_id', Integer, ForeignKey('auth_user_groups.id'), primary_key=True),
    Column('created_at', DateTime, server_default=sa_func.now()) # DateTime 默认值
)

class User(Base):
    """用户表"""
    __tablename__ = "auth_users" # 表名前缀规范化

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128), nullable=False)
    password_hash = Column(String(256), nullable=False)
    email = Column(String(128), unique=True, nullable=False, index=True)  # 邮箱作为登录账号
    role = Column(String(32), default="user", server_default=sa_text("'user'"))  # admin, data_admin, analyst, user
    permissions = Column(JSONB, nullable=True)  # JSON array: 用户单独权限, 改为 JSONB
    is_active = Column(Boolean, default=True, server_default=sa_text('true')) # Boolean 默认值
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now()) # DateTime 默认值
    last_login = Column(DateTime, nullable=True)
    # MFA 字段
    mfa_enabled = Column(Boolean, default=False, server_default=sa_text('false'))
    mfa_secret_encrypted = Column(String(256), nullable=True)  # Fernet 加密存储
    mfa_backup_codes_encrypted = Column(String(1024), nullable=True)  # 加密 JSON 数组

    # 关联
    groups = relationship('UserGroup', secondary=user_group_members, back_populates='members')

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        result = {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "email": self.email,
            "role": self.role,
            "permissions": self.permissions if self.permissions else [], # JSONB 字段直接是 Python 对象
            "group_ids": [g.id for g in self.groups] if self.groups else [],
            "group_names": [g.name for g in self.groups] if self.groups else [],
            "is_active": self.is_active,
            "mfa_enabled": self.mfa_enabled,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "last_login": self.last_login.strftime("%Y-%m-%d %H:%M:%S") if self.last_login else None,
        }
        return result


class UserGroup(Base):
    """用户组表"""
    __tablename__ = "auth_user_groups" # 表名前缀规范化

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False, index=True)
    description = Column(String(256), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now()) # DateTime 默认值

    # 关联
    members = relationship('User', secondary=user_group_members, back_populates='groups')
    group_perms = relationship('GroupPermission', back_populates='group')

    def to_dict(self, include_members: bool = False) -> Dict[str, Any]:
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "member_count": len(self.members) if self.members else 0,
            "permissions": self.get_permissions(),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }
        if include_members:
            result["members"] = [m.to_dict() for m in self.members] if self.members else []
        return result

    def get_permissions(self) -> List[str]:
        """获取组的权限列表"""
        if not hasattr(self, '_permissions_cache'):
            self._permissions_cache = []
            # 从关联表中获取
            for assoc in self.group_perms:
                self._permissions_cache.append(assoc.permission_key)
        return self._permissions_cache


class GroupPermission(Base):
    """组-权限关联表"""
    __tablename__ = "auth_group_permissions" # 表名前缀规范化

    group_id = Column(Integer, ForeignKey('auth_user_groups.id'), primary_key=True)
    permission_key = Column(String(64), primary_key=True)
    created_at = Column(DateTime, server_default=sa_func.now()) # DateTime 默认值

    # 关系
    group = relationship('UserGroup', back_populates='group_perms')


class PasswordResetToken(Base):
    """密码重置 Token 存储表"""
    __tablename__ = "auth_password_reset_tokens"

    id = Column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa_text("gen_random_uuid()"),
    )
    user_id = Column(
        Integer,
        ForeignKey('auth_users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, server_default=sa_text('false'), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())


class RefreshToken(Base):
    """Refresh Token 存储表（JWT Refresh Token 持久化）"""
    __tablename__ = "auth_refresh_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('auth_users.id', ondelete='CASCADE'), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)  # SHA-256 hash of the raw token
    device_fingerprint = Column(String(256), nullable=True)  # 浏览器 UA/IP 指纹（可选）
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    revoked_at = Column(DateTime, nullable=True)  # 撤销时间，非空表示已撤销

    __table_args__ = (
        Index("ix_refresh_tokens_user_id", "user_id"),
        Index("ix_refresh_tokens_token_hash", "token_hash"),
    )


# 从中央配置导入 SessionLocal
from app.core.database import SessionLocal
from sqlalchemy.orm import Session

class UserDatabase:
    """用户数据库管理 - 不再是单例，直接使用中央 SessionLocal"""

    def __init__(self, db_path: str = None):
        """db_path 参数不再使用，保留签名以兼容旧代码"""
        pass

    @property
    def session(self) -> Session:
        """每次访问获取当前线程的 session，并刷新缓存避免脏读"""
        s = SessionLocal()
        s.expire_all() # 刷新缓存，确保获取最新数据
        return s

    def create_user(self, username: str, password_hash: str, role: str = "user", display_name: str = None, email: str = None, permissions: list = None) -> User:
        """创建用户"""
        user = User(
            username=username,
            password_hash=password_hash,
            role=role,
            display_name=display_name or username,
            email=email,
            permissions=permissions # JSONB 字段直接传入 Python 列表/字典
        )
        self.session.add(user)
        self.session.commit()
        return user

    def get_user(self, user_id: int) -> Optional[User]:
        """获取用户"""
        return self.session.query(User).filter(User.id == user_id).first()

    def get_user_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        return self.session.query(User).filter(User.username == username).first()

    def get_user_by_email(self, email: str) -> Optional[User]:
        """根据邮箱获取用户"""
        return self.session.query(User).filter(User.email == email).first()

    def get_users(self, limit: int = 100, role: str = None) -> List[User]:
        """获取用户列表"""
        query = self.session.query(User)
        if role:
            query = query.filter(User.role == role)
        return query.order_by(User.created_at.desc()).limit(limit).all()

    def update_user(self, user: User):
        """更新用户"""
        self.session.commit()

    def update_user_permissions(self, user_id: int, permissions: list) -> bool:
        """更新用户权限"""
        user = self.session.query(User).filter(User.id == user_id).first()
        if user:
            user.permissions = permissions # JSONB 字段直接传入 Python 列表/字典
            self.session.commit()
            return True
        return False

    def delete_user(self, user_id: int) -> bool:
        """删除用户"""
        user = self.session.query(User).filter(User.id == user_id).first()
        if user:
            self.session.delete(user)
            self.session.commit()
            return True
        return False

    # ========== 用户组管理 ==========

    def create_group(self, name: str, description: str = None) -> UserGroup:
        """创建用户组"""
        group = UserGroup(name=name, description=description)
        self.session.add(group)
        self.session.commit()
        return group

    def get_group(self, group_id: int) -> Optional[UserGroup]:
        """获取用户组"""
        return self.session.query(UserGroup).filter(UserGroup.id == group_id).first()

    def get_group_by_name(self, name: str) -> Optional[UserGroup]:
        """根据名称获取用户组"""
        return self.session.query(UserGroup).filter(UserGroup.name == name).first()

    def get_groups(self) -> List[UserGroup]:
        """获取所有用户组"""
        return self.session.query(UserGroup).order_by(UserGroup.created_at.desc()).all()

    def update_group(self, group_id: int, name: str = None, description: str = None) -> bool:
        """更新用户组"""
        group = self.session.query(UserGroup).filter(UserGroup.id == group_id).first()
        if not group:
            return False
        if name:
            group.name = name
        if description is not None:
            group.description = description
        self.session.commit()
        return True

    def delete_group(self, group_id: int) -> bool:
        """删除用户组"""
        group = self.session.query(UserGroup).filter(UserGroup.id == group_id).first()
        if group:
            self.session.delete(group)
            self.session.commit()
            return True
        return False

    def add_user_to_group(self, user_id: int, group_id: int) -> bool:
        """添加用户到组"""
        user = self.session.query(User).filter(User.id == user_id).first()
        group = self.session.query(UserGroup).filter(UserGroup.id == group_id).first()
        if not user or not group:
            return False
        if group not in user.groups:
            user.groups.append(group)
            self.session.commit()
        return True

    def remove_user_from_group(self, user_id: int, group_id: int) -> bool:
        """从组移除用户"""
        user = self.session.query(User).filter(User.id == user_id).first()
        group = self.session.query(UserGroup).filter(UserGroup.id == group_id).first()
        if not user or not group:
            return False
        if group in user.groups:
            user.groups.remove(group)
            self.session.commit()
        return True

    def get_group_members(self, group_id: int) -> List[User]:
        """获取组成员"""
        group = self.session.query(UserGroup).filter(UserGroup.id == group_id).first()
        if group:
            return group.members
        return []

    def get_user_groups(self, user_id: int) -> List[UserGroup]:
        """获取用户所属的组"""
        user = self.session.query(User).filter(User.id == user_id).first()
        if user:
            return user.groups
        return []

    # ========== 组权限管理 ==========

    def set_group_permissions(self, group_id: int, permissions: List[str]) -> bool:
        """设置组权限"""
        group = self.session.query(UserGroup).filter(UserGroup.id == group_id).first()
        if not group:
            return False

        # 删除旧权限
        self.session.query(GroupPermission).filter(GroupPermission.group_id == group_id).delete()

        # 添加新权限
        for perm_key in permissions:
            gp = GroupPermission(group_id=group_id, permission_key=perm_key)
            self.session.add(gp)

        self.session.commit()
        return True

    def get_group_permissions(self, group_id: int) -> List[str]:
        """获取组权限"""
        perms = self.session.query(GroupPermission).filter(GroupPermission.group_id == group_id).all()
        return [p.permission_key for p in perms]

    def get_user_permissions_from_groups(self, user_id: int) -> List[str]:
        """获取用户从组继承的权限"""
        groups = self.get_user_groups(user_id)
        perms = set()
        for group in groups:
            perms.update(self.get_group_permissions(group.id))
        return list(perms)

    def get_all_permissions(self) -> List[Dict[str, str]]:
        """获取所有可用权限定义"""
        return [
            {"key": "ddl_check", "label": "DDL 规范检查", "module": "DDL Validator"},
            {"key": "ddl_generator", "label": "DDL 生成器", "module": "DDL Generator"},
            {"key": "database_monitor", "label": "数据库监控", "module": "Database Monitor"},
            {"key": "rule_config", "label": "规则配置", "module": "Rule Config"},
            {"key": "scan_logs", "label": "扫描日志", "module": "Scan Logs"},
            {"key": "user_management", "label": "用户管理", "module": "Admin"},
        ]

    # ========== 密码重置 Token 管理 ==========

    def create_password_reset_token(
        self, user_id: int, token_hash: str, expires_at: datetime
    ) -> "PasswordResetToken":
        """创建密码重置 token 记录"""
        token = PasswordResetToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.session.add(token)
        self.session.commit()
        return token

    def get_valid_password_reset_token(self, token_hash: str) -> Optional["PasswordResetToken"]:
        """获取有效的密码重置 token（未过期、未使用）"""
        now = datetime.utcnow()
        return (
            self.session.query(PasswordResetToken)
            .filter(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.is_used.is_(False),
                PasswordResetToken.expires_at > now,
            )
            .first()
        )

    def invalidate_previous_reset_tokens(self, user_id: int) -> int:
        """将用户所有未使用的重置 token 标记为已使用，返回数量"""
        now = datetime.utcnow()
        count = (
            self.session.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.is_used.is_(False),
                PasswordResetToken.expires_at > now,
            )
            .update({"is_used": True})
        )
        self.session.commit()
        return count

    def mark_token_used(self, token_hash: str) -> bool:
        """标记 token 为已使用"""
        token = (
            self.session.query(PasswordResetToken)
            .filter(PasswordResetToken.token_hash == token_hash)
            .first()
        )
        if not token:
            return False
        token.is_used = True
        self.session.commit()
        return True

    # ========== Refresh Token 管理 ==========

    def create_refresh_token(
        self,
        user_id: int,
        token_hash: str,
        expires_at: datetime,
        device_fingerprint: str = None,
    ) -> "RefreshToken":
        """创建 refresh token 记录"""
        token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            device_fingerprint=device_fingerprint,
        )
        self.session.add(token)
        self.session.commit()
        return token

    def verify_refresh_token(self, token_hash: str) -> Optional["RefreshToken"]:
        """验证 refresh token hash，返回有效 token 记录"""
        now = datetime.utcnow()
        token = (
            self.session.query(RefreshToken)
            .filter(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .first()
        )
        return token

    def revoke_refresh_token(self, token_hash: str) -> bool:
        """撤销指定的 refresh token"""
        token = (
            self.session.query(RefreshToken)
            .filter(RefreshToken.token_hash == token_hash)
            .first()
        )
        if not token:
            return False
        token.revoked_at = datetime.utcnow()
        self.session.commit()
        return True

    def revoke_all_user_refresh_tokens(self, user_id: int) -> int:
        """撤销用户所有 refresh token，返回撤销数量"""
        now = datetime.utcnow()
        count = (
            self.session.query(RefreshToken)
            .filter(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .update({"revoked_at": now})
        )
        self.session.commit()
        return count

    # ========== MFA 管理 ==========

    def get_mfa_enabled(self, user_id: int) -> bool:
        """检查用户是否开启了 MFA"""
        user = self.get_user(user_id)
        return user.mfa_enabled if user else False

    def get_mfa_secret_encrypted(self, user_id: int) -> Optional[str]:
        """获取用户加密存储的 MFA secret"""
        user = self.get_user(user_id)
        return user.mfa_secret_encrypted if user else None

    def set_mfa_secret(self, user_id: int, encrypted_secret: str) -> bool:
        """设置用户 MFA secret（加密存储）"""
        user = self.get_user(user_id)
        if not user:
            return False
        user.mfa_secret_encrypted = encrypted_secret
        self.session.commit()
        return True

    def enable_mfa(self, user_id: int, encrypted_secret: str, backup_codes_encrypted: str) -> bool:
        """启用 MFA（设置 secret 和备用码）"""
        user = self.get_user(user_id)
        if not user:
            return False
        user.mfa_enabled = True
        user.mfa_secret_encrypted = encrypted_secret
        user.mfa_backup_codes_encrypted = backup_codes_encrypted
        self.session.commit()
        return True

    def disable_mfa(self, user_id: int) -> bool:
        """禁用 MFA（清除 secret）"""
        user = self.get_user(user_id)
        if not user:
            return False
        user.mfa_enabled = False
        user.mfa_secret_encrypted = None
        user.mfa_backup_codes_encrypted = None
        self.session.commit()
        return True

    def get_backup_codes_encrypted(self, user_id: int) -> Optional[str]:
        """获取用户加密存储的备用码"""
        user = self.get_user(user_id)
        return user.mfa_backup_codes_encrypted if user else None

    # close 方法不再需要，因为 session 由 SessionLocal 管理
    # def close(self):
    #     self.session.close()

