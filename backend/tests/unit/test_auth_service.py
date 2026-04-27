"""单元测试：AuthService — 业务逻辑方法（mock DB 层）

覆盖范围：
- authenticate: 邮箱/用户名登录、不存在用户、非活跃用户、密码错误
- register: 邮箱格式校验、重复邮箱、默认 display_name
- create_user: 重复用户名、默认角色/权限
- has_permission: admin 全权限、角色默认权限、缺失权限
- get_effective_permissions: 角色 + 个人权限合并去重
- update_user_permissions: 无效权限拒绝
- get_user_tag: 活跃/正常/冷门/潜水/僵尸 标签
- change_password: 旧密码错误、成功
- admin_reset_password: 用户不存在、密码过短、成功
"""
import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")

from services.auth.service import AuthService


def _make_service():
    """创建 AuthService 实例，绕过单例 __new__（避免 DB 初始化）。"""
    svc = object.__new__(AuthService)
    svc._db = MagicMock()
    return svc


def _hash_password(password: str) -> str:
    """独立生成密码哈希，不经过 AuthService 单例。"""
    import hashlib
    import secrets as _secrets
    salt = _secrets.token_hex(16)
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"{salt}${hash_obj.hex()}"


def _make_user_mock(
    user_id=1,
    username="testuser",
    email="test@example.com",
    role="user",
    is_active=True,
    password="secret123",
    permissions=None,
    last_login=None,
    mfa_enabled=False,
):
    """创建一个模拟 User 对象。"""
    pw_hash = _hash_password(password)

    user = MagicMock()
    user.id = user_id
    user.username = username
    user.email = email
    user.role = role
    user.is_active = is_active
    user.password_hash = pw_hash
    user.permissions = permissions or []
    user.last_login = last_login
    user.mfa_enabled = mfa_enabled
    user.to_dict.return_value = {
        "id": user_id,
        "username": username,
        "email": email,
        "role": role,
        "is_active": is_active,
        "permissions": permissions or [],
    }
    return user


# =====================================================================
# authenticate
# =====================================================================


class TestAuthenticate:
    """authenticate 方法测试"""

    def test_login_by_email(self):
        """通过邮箱登录成功"""
        svc = _make_service()
        user = _make_user_mock(password="correct")
        svc._db.get_user_by_email.return_value = user
        svc._db.get_user_by_username.return_value = None

        result = svc.authenticate("test@example.com", "correct")
        assert result is not None
        assert result["id"] == 1
        svc._db.update_user.assert_called_once()

    def test_login_by_username(self):
        """通过用户名登录成功"""
        svc = _make_service()
        user = _make_user_mock(password="correct")
        svc._db.get_user_by_email.return_value = None
        svc._db.get_user_by_username.return_value = user

        result = svc.authenticate("testuser", "correct")
        assert result is not None

    def test_login_user_not_found(self):
        """用户不存在返回 None"""
        svc = _make_service()
        svc._db.get_user_by_email.return_value = None
        svc._db.get_user_by_username.return_value = None

        assert svc.authenticate("nobody", "pass") is None

    def test_login_inactive_user(self):
        """非活跃用户返回 None"""
        svc = _make_service()
        user = _make_user_mock(is_active=False, password="correct")
        svc._db.get_user_by_email.return_value = user

        assert svc.authenticate("test@example.com", "correct") is None

    def test_login_wrong_password(self):
        """密码错误返回 None"""
        svc = _make_service()
        user = _make_user_mock(password="correct")
        svc._db.get_user_by_email.return_value = user

        assert svc.authenticate("test@example.com", "wrong") is None


# =====================================================================
# register
# =====================================================================


class TestRegister:
    """register 方法测试"""

    def test_register_invalid_email(self):
        """无效邮箱格式返回 None"""
        svc = _make_service()
        assert svc.register("not-an-email", "password") is None

    def test_register_duplicate_email(self):
        """邮箱已存在返回 None"""
        svc = _make_service()
        svc._db.get_user_by_email.return_value = MagicMock()
        assert svc.register("test@example.com", "password") is None

    def test_register_success_default_display_name(self):
        """成功注册使用邮箱前缀作为默认 display_name"""
        svc = _make_service()
        svc._db.get_user_by_email.return_value = None
        svc._db.get_user_by_username.return_value = None
        user = _make_user_mock()
        svc._db.create_user.return_value = user

        result = svc.register("alice@company.com", "password123")
        assert result is not None
        # 验证 create_user 被调用
        svc._db.create_user.assert_called_once()
        call_kwargs = svc._db.create_user.call_args
        assert call_kwargs.kwargs.get("display_name") == "alice" or \
               (call_kwargs.args and "alice" in str(call_kwargs))

    def test_register_username_collision_generates_suffix(self):
        """用户名冲突时自动加数字后缀"""
        svc = _make_service()
        svc._db.get_user_by_email.return_value = None
        # 第一次用户名存在，第二次不存在
        svc._db.get_user_by_username.side_effect = [MagicMock(), None]
        user = _make_user_mock()
        svc._db.create_user.return_value = user

        result = svc.register("bob@company.com", "password123")
        assert result is not None
        call_kwargs = svc._db.create_user.call_args
        assert call_kwargs.kwargs.get("username") == "bob1"


# =====================================================================
# create_user
# =====================================================================


class TestCreateUser:
    """create_user 方法测试"""

    def test_create_user_duplicate_username(self):
        """重复用户名返回 None"""
        svc = _make_service()
        svc._db.get_user_by_username.return_value = MagicMock()
        assert svc.create_user("existing", "pass") is None

    def test_create_user_default_role(self):
        """不指定角色默认为 user"""
        svc = _make_service()
        svc._db.get_user_by_username.return_value = None
        user = _make_user_mock()
        svc._db.create_user.return_value = user

        svc.create_user("newuser", "pass123")
        call_kwargs = svc._db.create_user.call_args.kwargs
        assert call_kwargs["role"] == "user"

    def test_create_user_with_role_uses_default_permissions(self):
        """指定角色不指定权限时使用角色默认权限"""
        svc = _make_service()
        svc._db.get_user_by_username.return_value = None
        user = _make_user_mock()
        svc._db.create_user.return_value = user

        svc.create_user("admin2", "pass123", role="data_admin")
        call_kwargs = svc._db.create_user.call_args.kwargs
        expected_perms = AuthService.ROLE_DEFAULT_PERMISSIONS["data_admin"]
        assert call_kwargs["permissions"] == expected_perms

    def test_create_user_with_group_ids(self):
        """指定 group_ids 时调用 add_user_to_group"""
        svc = _make_service()
        svc._db.get_user_by_username.return_value = None
        user = _make_user_mock()
        svc._db.create_user.return_value = user

        svc.create_user("newuser", "pass", group_ids=[1, 2])
        assert svc._db.add_user_to_group.call_count == 2


# =====================================================================
# has_permission / get_effective_permissions
# =====================================================================


class TestPermissions:
    """权限检查测试"""

    def test_has_permission_admin_always_true(self):
        """admin 角色拥有所有权限"""
        svc = _make_service()
        user = _make_user_mock(role="admin")
        svc._db.get_user.return_value = user

        assert svc.has_permission(1, "ddl_check") is True
        assert svc.has_permission(1, "nonexistent_perm") is True

    def test_has_permission_no_user_id(self):
        """user_id 为 None/0 返回 False"""
        svc = _make_service()
        assert svc.has_permission(None, "ddl_check") is False
        assert svc.has_permission(0, "ddl_check") is False

    def test_has_permission_user_not_found(self):
        """用户不存在返回 False"""
        svc = _make_service()
        svc._db.get_user.return_value = None
        assert svc.has_permission(999, "ddl_check") is False

    def test_has_permission_role_default(self):
        """角色默认权限生效"""
        svc = _make_service()
        user = _make_user_mock(role="analyst", permissions=[])
        svc._db.get_user.return_value = user

        assert svc.has_permission(1, "scan_logs") is True
        assert svc.has_permission(1, "tableau") is True
        assert svc.has_permission(1, "ddl_check") is False

    def test_get_effective_permissions_merges_role_and_personal(self):
        """合并角色默认权限和个人权限并去重"""
        svc = _make_service()
        user = _make_user_mock(role="analyst", permissions=["ddl_check", "scan_logs"])
        svc._db.get_user.return_value = user

        perms = svc.get_effective_permissions(1)
        # analyst 默认: scan_logs, tableau
        # 个人额外: ddl_check, scan_logs
        # 合并去重
        assert set(perms) == {"scan_logs", "tableau", "ddl_check"}

    def test_get_effective_permissions_user_not_found(self):
        """用户不存在返回空列表"""
        svc = _make_service()
        svc._db.get_user.return_value = None
        assert svc.get_effective_permissions(999) == []

    def test_update_user_permissions_invalid_perm(self):
        """无效权限名返回 False"""
        svc = _make_service()
        assert svc.update_user_permissions(1, ["invalid_perm"]) is False

    def test_update_user_permissions_valid(self):
        """有效权限更新成功并撤销 refresh token"""
        svc = _make_service()
        svc._db.update_user_permissions.return_value = True
        result = svc.update_user_permissions(1, ["ddl_check", "tableau"])
        assert result is True
        svc._db.revoke_all_user_refresh_tokens.assert_called_once_with(1)


# =====================================================================
# get_user_tag
# =====================================================================


class TestUserTag:
    """用户标签测试"""

    def test_tag_unknown_user(self):
        """用户不存在返回未知标签"""
        svc = _make_service()
        svc._db.get_user.return_value = None
        tag = svc.get_user_tag(999)
        assert tag["tag"] == "未知"

    def test_tag_zombie_no_login(self):
        """从未登录的用户标记为僵尸"""
        svc = _make_service()
        user = _make_user_mock(last_login=None)
        svc._db.get_user.return_value = user
        tag = svc.get_user_tag(1)
        assert tag["tag"] == "僵尸"

    def test_tag_active_within_7_days(self):
        """7天内登录标记为活跃"""
        svc = _make_service()
        user = _make_user_mock(last_login=datetime.now() - timedelta(days=3))
        svc._db.get_user.return_value = user
        tag = svc.get_user_tag(1)
        assert tag["tag"] == "活跃"
        assert tag["color"] == "emerald"

    def test_tag_normal_within_30_days(self):
        """8-30天登录标记为正常"""
        svc = _make_service()
        user = _make_user_mock(last_login=datetime.now() - timedelta(days=15))
        svc._db.get_user.return_value = user
        tag = svc.get_user_tag(1)
        assert tag["tag"] == "正常"
        assert tag["color"] == "blue"

    def test_tag_cold_within_90_days(self):
        """31-90天登录标记为冷门"""
        svc = _make_service()
        user = _make_user_mock(last_login=datetime.now() - timedelta(days=60))
        svc._db.get_user.return_value = user
        tag = svc.get_user_tag(1)
        assert tag["tag"] == "冷门"
        assert tag["color"] == "orange"

    def test_tag_lurker_over_90_days(self):
        """超过 90 天标记为潜水"""
        svc = _make_service()
        user = _make_user_mock(last_login=datetime.now() - timedelta(days=120))
        svc._db.get_user.return_value = user
        tag = svc.get_user_tag(1)
        assert tag["tag"] == "潜水"
        assert tag["color"] == "gray"


# =====================================================================
# change_password / admin_reset_password
# =====================================================================


class TestPasswordManagement:
    """密码管理测试"""

    def test_change_password_user_not_found(self):
        """用户不存在返回 False"""
        svc = _make_service()
        svc._db.get_user.return_value = None
        assert svc.change_password(999, "old", "new") is False

    def test_change_password_wrong_old_password(self):
        """旧密码错误返回 False"""
        svc = _make_service()
        user = _make_user_mock(password="correct")
        svc._db.get_user.return_value = user
        assert svc.change_password(1, "wrong", "newpass") is False

    def test_change_password_success(self):
        """正确旧密码更新成功"""
        svc = _make_service()
        user = _make_user_mock(password="oldpass")
        svc._db.get_user.return_value = user
        result = svc.change_password(1, "oldpass", "newpass123")
        assert result is True
        svc._db.update_user.assert_called_once()
        svc._db.revoke_all_user_refresh_tokens.assert_called_once_with(1)

    def test_admin_reset_password_user_not_found(self):
        """用户不存在返回失败"""
        svc = _make_service()
        svc._db.get_user.return_value = None
        ok, msg = svc.admin_reset_password(999, "newpass123")
        assert ok is False
        assert "不存在" in msg

    def test_admin_reset_password_too_short(self):
        """密码过短返回失败"""
        svc = _make_service()
        user = _make_user_mock()
        svc._db.get_user.return_value = user
        ok, msg = svc.admin_reset_password(1, "short")
        assert ok is False
        assert "8" in msg

    def test_admin_reset_password_success(self):
        """管理员重置密码成功"""
        svc = _make_service()
        user = _make_user_mock()
        svc._db.get_user.return_value = user
        ok, msg = svc.admin_reset_password(1, "newpassword123")
        assert ok is True
        assert "已重置" in msg
        svc._db.update_user.assert_called_once()
        svc._db.revoke_all_user_refresh_tokens.assert_called_once_with(1)


# =====================================================================
# update_user_role / toggle_user_active / update_user_info
# =====================================================================


class TestUserManagement:
    """用户管理方法测试"""

    def test_update_user_role_not_found(self):
        """用户不存在返回 False"""
        svc = _make_service()
        svc._db.get_user.return_value = None
        assert svc.update_user_role(999, "admin") is False

    def test_update_user_role_success(self):
        """角色更新成功并撤销 refresh token"""
        svc = _make_service()
        user = _make_user_mock(role="user")
        svc._db.get_user.return_value = user
        result = svc.update_user_role(1, "data_admin")
        assert result is True
        assert user.role == "data_admin"
        svc._db.revoke_all_user_refresh_tokens.assert_called_once_with(1)

    def test_toggle_user_active_not_found(self):
        """用户不存在返回 False"""
        svc = _make_service()
        svc._db.get_user.return_value = None
        assert svc.toggle_user_active(999) is False

    def test_toggle_user_active_success(self):
        """切换活跃状态"""
        svc = _make_service()
        user = _make_user_mock(is_active=True)
        svc._db.get_user.return_value = user
        result = svc.toggle_user_active(1)
        assert result is True
        assert user.is_active is False

    def test_update_user_info_not_found(self):
        """用户不存在返回 None"""
        svc = _make_service()
        svc._db.get_user.return_value = None
        assert svc.update_user_info(999, display_name="New Name") is None

    def test_update_user_info_success(self):
        """更新用户信息成功"""
        svc = _make_service()
        user = _make_user_mock()
        svc._db.get_user.return_value = user
        result = svc.update_user_info(1, display_name="Alice", email="alice@new.com")
        assert result is not None
        assert user.display_name == "Alice"
        assert user.email == "alice@new.com"


# =====================================================================
# Group management
# =====================================================================


class TestGroupManagement:
    """用户组管理方法测试"""

    def test_create_group_duplicate_name(self):
        """重复组名返回 None"""
        svc = _make_service()
        svc._db.get_group_by_name.return_value = MagicMock()
        assert svc.create_group("existing_group") is None

    def test_set_group_permissions_invalid(self):
        """无效权限拒绝设置"""
        svc = _make_service()
        result = svc.set_group_permissions(1, ["invalid_perm"])
        assert result is False

    def test_set_group_permissions_valid(self):
        """有效权限设置成功"""
        svc = _make_service()
        svc._db.set_group_permissions.return_value = True
        result = svc.set_group_permissions(1, ["ddl_check", "tableau"])
        assert result is True

    def test_get_user_permissions_with_groups_not_found(self):
        """用户不存在返回空结构"""
        svc = _make_service()
        svc._db.get_user.return_value = None
        result = svc.get_user_permissions_with_groups(999)
        assert result == {"personal": [], "from_groups": [], "all": []}

    def test_get_user_permissions_with_groups_merges(self):
        """合并个人权限和组权限"""
        svc = _make_service()
        user = _make_user_mock(permissions=["ddl_check"])
        svc._db.get_user.return_value = user
        svc._db.get_user_permissions_from_groups.return_value = ["tableau", "ddl_check"]

        result = svc.get_user_permissions_with_groups(1)
        assert "ddl_check" in result["all"]
        assert "tableau" in result["all"]
        assert result["personal"] == ["ddl_check"]
        assert "tableau" in result["from_groups"]
