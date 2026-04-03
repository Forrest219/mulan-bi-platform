"""单元测试：AuthService — 密码哈希 / JWT / RBAC"""
import os
import pytest

# 确保测试环境变量在导入前设置
os.environ.setdefault("ADMIN_USERNAME", "testadmin")
os.environ.setdefault("ADMIN_PASSWORD", "")  # 禁用自动创建管理员

from services.auth.service import AuthService
from services.auth.models import UserDatabase


@pytest.fixture(autouse=True)
def _restore_auth_db():
    """每个测试后恢复 auth_service._db，防止污染其他测试"""
    yield
    if AuthService._instance is not None:
        AuthService._instance._db = UserDatabase()


class _StubUserDatabase:
    """不执行任何 DB 操作的 mock — 用于不需要 DB 的纯逻辑测试"""
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class TestPasswordHashing:
    """密码哈希测试"""

    def test_hash_password_format(self):
        """哈希结果格式: salt$hexhash，长度正确"""
        svc = AuthService.__new__(AuthService)
        svc._db = _StubUserDatabase()  # 不依赖数据库
        h = svc.hash_password("testpass")
        parts = h.split("$")
        assert len(parts) == 2
        assert len(parts[0]) == 32  # 16 字节 hex = 32 字符
        assert len(parts[1]) == 64  # SHA256 hex = 64 字符

    def test_hash_password_deterministic_salt(self):
        """相同密码每次哈希 salt 不同，但均可验证"""
        svc = AuthService.__new__(AuthService)
        svc._db = None
        p = "mysecret"
        h1 = svc.hash_password(p)
        h2 = svc.hash_password(p)
        assert h1 != h2  # salt 不同
        assert svc.verify_password(p, h1) is True
        assert svc.verify_password(p, h2) is True

    def test_verify_password_correct(self):
        """正确密码验证通过"""
        svc = AuthService.__new__(AuthService)
        svc._db = None
        h = svc.hash_password("correct")
        assert svc.verify_password("correct", h) is True

    def test_verify_password_wrong(self):
        """错误密码验证失败"""
        svc = AuthService.__new__(AuthService)
        svc._db = None
        h = svc.hash_password("correct")
        assert svc.verify_password("wrong", h) is False

    def test_verify_password_malformed_hash(self):
        """损坏的哈希串返回 False"""
        svc = AuthService.__new__(AuthService)
        svc._db = None
        assert svc.verify_password("x", "no-dollar-sign") is False
        assert svc.verify_password("x", "") is False


class TestRolePermissions:
    """RBAC 角色权限测试"""

    def test_admin_has_all_permissions(self):
        """admin 角色拥有所有权限"""
        svc = AuthService.__new__(AuthService)
        svc._db = None
        assert svc.ROLE_ADMIN == "admin"
        assert set(svc.ROLE_DEFAULT_PERMISSIONS["admin"]) == set(svc.ALL_PERMISSIONS)

    def test_data_admin_permissions(self):
        """data_admin 角色有正确子集"""
        svc = AuthService.__new__(AuthService)
        svc._db = None
        expected = {"database_monitor", "ddl_check", "rule_config", "scan_logs", "tableau", "llm"}
        assert set(svc.ROLE_DEFAULT_PERMISSIONS["data_admin"]) == expected

    def test_analyst_permissions(self):
        """analyst 角色只有只读权限"""
        svc = AuthService.__new__(AuthService)
        svc._db = None
        assert set(svc.ROLE_DEFAULT_PERMISSIONS["analyst"]) == {"scan_logs", "tableau"}

    def test_user_permissions(self):
        """user 角色无默认权限"""
        svc = AuthService.__new__(AuthService)
        svc._db = None
        assert svc.ROLE_DEFAULT_PERMISSIONS["user"] == []

    def test_permission_labels_complete(self):
        """所有权限都有中文标签"""
        svc = AuthService.__new__(AuthService)
        svc._db = None
        for perm in svc.ALL_PERMISSIONS:
            assert perm in svc.PERMISSION_LABELS
            assert svc.PERMISSION_LABELS[perm]


class TestRoleLabels:
    """角色标签测试"""

    def test_all_roles_have_labels(self):
        """所有角色都有中文标签"""
        svc = AuthService.__new__(AuthService)
        svc._db = None
        for role in [svc.ROLE_ADMIN, svc.ROLE_DATA_ADMIN, svc.ROLE_ANALYST, svc.ROLE_USER]:
            assert role in svc.ROLE_LABELS
            assert svc.ROLE_LABELS[role]
