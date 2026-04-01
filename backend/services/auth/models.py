"""用户认证数据模型"""
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

Base = declarative_base()

# 关联表：用户-组
user_group_members = Table(
    'user_group_members',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('group_id', Integer, ForeignKey('user_groups.id'), primary_key=True),
    Column('created_at', DateTime, default=datetime.now)
)

class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128), nullable=False)
    password_hash = Column(String(256), nullable=False)
    email = Column(String(128), unique=True, nullable=False, index=True)  # 邮箱作为登录账号
    role = Column(String(32), default="user")  # admin, user
    permissions = Column(Text, nullable=True)  # JSON array: 用户单独权限
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    last_login = Column(DateTime, nullable=True)

    # 关联
    groups = relationship('UserGroup', secondary=user_group_members, back_populates='members')

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        import json
        result = {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "email": self.email,
            "role": self.role,
            "permissions": json.loads(self.permissions) if self.permissions else [],
            "group_ids": [g.id for g in self.groups] if self.groups else [],
            "group_names": [g.name for g in self.groups] if self.groups else [],
            "is_active": self.is_active,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "last_login": self.last_login.strftime("%Y-%m-%d %H:%M:%S") if self.last_login else None,
        }
        return result


class UserGroup(Base):
    """用户组表"""
    __tablename__ = "user_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False, index=True)
    description = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

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
    __tablename__ = "group_permissions"

    group_id = Column(Integer, ForeignKey('user_groups.id'), primary_key=True)
    permission_key = Column(String(64), primary_key=True)
    created_at = Column(DateTime, default=datetime.now)

    # 关系
    group = relationship('UserGroup', back_populates='group_perms')


class UserDatabase:
    """用户数据库管理 - 单例模式"""

    _instance = None

    def __new__(cls, db_path: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            if db_path is None:
                import os
                db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "users.db")
            cls._instance._init_db(db_path)
        return cls._instance

    def _init_db(self, db_path: str):
        """初始化数据库"""
        import os
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

    def create_user(self, username: str, password_hash: str, role: str = "user", display_name: str = None, email: str = None, permissions: list = None) -> User:
        """创建用户"""
        import json
        user = User(
            username=username,
            password_hash=password_hash,
            role=role,
            display_name=display_name or username,
            email=email,
            permissions=json.dumps(permissions) if permissions else None
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
        import json
        user = self.session.query(User).filter(User.id == user_id).first()
        if user:
            user.permissions = json.dumps(permissions)
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

    def close(self):
        """关闭数据库连接"""
        self.session.close()
