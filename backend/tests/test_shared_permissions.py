"""测试：共享资源权限 API（Spec 11 §4.2）"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch


class TestSharedPermissionsAPI:
    """GET /api/permissions/shared 端点测试"""

    def test_get_shared_permissions_empty(self, admin_client):
        """空列表时应返回空数组"""
        resp = admin_client.get("/api/permissions/shared")
        assert resp.status_code == 200
        data = resp.json()
        assert "permissions" in data
        assert data["permissions"] == []
        assert data["total"] == 0

    def test_get_shared_permissions_requires_admin(self, client):
        """非管理员访问应返回 403"""
        resp = client.get("/api/permissions/shared")
        assert resp.status_code in (401, 403)

    def test_shared_permissions_response_fields(self, admin_client, db_session):
        """验证返回字段符合 Spec 11 §4.2 要求"""
        from services.auth.models import SharedResourcePermission, User
        from app.core.database import SessionLocal

        # 创建测试数据
        admin = db_session.query(User).filter(User.username == "admin").first()
        assert admin is not None

        perm = SharedResourcePermission(
            grantee_type="user",
            grantee_id=admin.id,
            resource_type="semantic_table",
            resource_id="st_001",
            resource_name="销售事实表",
            permission_level="read",
            granted_by=admin.id,
            expires_at=datetime.utcnow() + timedelta(days=7),
        )
        db_session.add(perm)
        db_session.commit()

        resp = admin_client.get("/api/permissions/shared")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

        p = data["permissions"][0]
        # 验证必需字段（Spec 11 §4.2）
        assert "grantee" in p or ("grantee_type" in p and "grantee_id" in p and "grantee_name" in p)
        assert "resource_type" in p
        assert "resource_name" in p
        assert "permission_level" in p
        assert "granted_by" in p or "granted_by_name" in p
        assert "expires_at" in p
        assert p["resource_type"] == "semantic_table"
        assert p["resource_name"] == "销售事实表"
        assert p["permission_level"] == "read"

    def test_filter_by_user(self, admin_client, db_session):
        """filter_by_user 参数应正确过滤"""
        from services.auth.models import SharedResourcePermission, User

        admin = db_session.query(User).filter(User.username == "admin").first()
        other_user = db_session.query(User).filter(User.username != "admin").first()

        if other_user is None:
            pytest.skip("需要至少 2 个用户")

        # 创建两条权限，一条属于 admin，一条属于 other_user
        perm1 = SharedResourcePermission(
            grantee_type="user",
            grantee_id=admin.id,
            resource_type="datasource",
            resource_id="ds_001",
            resource_name="主数据源",
            permission_level="read",
            granted_by=admin.id,
        )
        perm2 = SharedResourcePermission(
            grantee_type="user",
            grantee_id=other_user.id,
            resource_type="datasource",
            resource_id="ds_002",
            resource_name="辅助数据源",
            permission_level="write",
            granted_by=admin.id,
        )
        db_session.add_all([perm1, perm2])
        db_session.commit()

        resp = admin_client.get(f"/api/permissions/shared?filter_by_user={admin.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["permissions"][0]["grantee_id"] == admin.id

    def test_filter_by_group(self, admin_client, db_session):
        """filter_by_group 参数应正确过滤"""
        from services.auth.models import SharedResourcePermission, User, UserGroup

        admin = db_session.query(User).filter(User.username == "admin").first()
        group = db_session.query(UserGroup).first()

        if group is None:
            pytest.skip("需要至少 1 个用户组")

        perm = SharedResourcePermission(
            grantee_type="group",
            grantee_id=group.id,
            resource_type="workbook",
            resource_id="wb_001",
            resource_name="销售报表",
            permission_level="admin",
            granted_by=admin.id,
        )
        db_session.add(perm)
        db_session.commit()

        resp = admin_client.get(f"/api/permissions/shared?filter_by_group={group.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["permissions"][0]["grantee_type"] == "group"
        assert data["permissions"][0]["grantee_id"] == group.id


class TestGrantSharedPermission:
    """POST /api/permissions/shared 端点测试"""

    def test_grant_permission_to_user(self, admin_client, db_session):
        """授予用户共享权限"""
        from services.auth.models import User

        admin = db_session.query(User).filter(User.username == "admin").first()
        other_user = db_session.query(User).filter(User.id != admin.id).first()
        if other_user is None:
            pytest.skip("需要至少 2 个用户")

        resp = admin_client.post("/api/permissions/shared", json={
            "grantee_type": "user",
            "grantee_id": other_user.id,
            "resource_type": "semantic_table",
            "resource_id": "st_test",
            "resource_name": "测试语义表",
            "permission_level": "read",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "permission" in data
        assert data["permission"]["grantee_id"] == other_user.id
        assert data["permission"]["resource_type"] == "semantic_table"
        assert data["permission"]["permission_level"] == "read"

    def test_grant_permission_with_expires_at(self, admin_client, db_session):
        """带过期时间的权限授予"""
        from services.auth.models import User

        admin = db_session.query(User).filter(User.username == "admin").first()
        other_user = db_session.query(User).filter(User.id != admin.id).first()
        if other_user is None:
            pytest.skip("需要至少 2 个用户")

        expires = (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"
        resp = admin_client.post("/api/permissions/shared", json={
            "grantee_type": "user",
            "grantee_id": other_user.id,
            "resource_type": "datasource",
            "resource_id": "ds_test",
            "resource_name": "测试数据源",
            "permission_level": "write",
            "expires_at": expires,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["permission"]["expires_at"] is not None

    def test_grant_invalid_grantee_type(self, admin_client):
        """无效的 grantee_type 应返回 400"""
        resp = admin_client.post("/api/permissions/shared", json={
            "grantee_type": "invalid",
            "grantee_id": 1,
            "resource_type": "semantic_table",
            "resource_id": "st_001",
            "resource_name": "测试表",
            "permission_level": "read",
        })
        assert resp.status_code == 400

    def test_grant_invalid_permission_level(self, admin_client, db_session):
        """无效的 permission_level 应返回 400"""
        from services.auth.models import User
        admin = db_session.query(User).filter(User.username == "admin").first()

        resp = admin_client.post("/api/permissions/shared", json={
            "grantee_type": "user",
            "grantee_id": admin.id,
            "resource_type": "semantic_table",
            "resource_id": "st_001",
            "resource_name": "测试表",
            "permission_level": "superadmin",  # 无效
        })
        assert resp.status_code == 400


class TestBatchRevokeSharedPermissions:
    """DELETE /api/permissions/shared/batch 端点测试"""

    def test_batch_revoke_empty(self, admin_client):
        """空列表应返回 400"""
        resp = admin_client.delete("/api/permissions/shared/batch", json={"permission_ids": []})
        assert resp.status_code == 400

    def test_batch_revoke_success(self, admin_client, db_session):
        """批量撤销成功"""
        from services.auth.models import SharedResourcePermission, User

        admin = db_session.query(User).filter(User.username == "admin").first()

        # 创建两条权限
        perms = [
            SharedResourcePermission(
                grantee_type="user",
                grantee_id=admin.id,
                resource_type="semantic_table",
                resource_id=f"st_{i}",
                resource_name=f"测试表{i}",
                permission_level="read",
                granted_by=admin.id,
            )
            for i in range(3)
        ]
        db_session.add_all(perms)
        db_session.commit()
        ids = [p.id for p in perms]

        resp = admin_client.delete("/api/permissions/shared/batch", json={"permission_ids": ids[:2]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] == 2

        # 验证只剩一条
        remaining = db_session.query(SharedResourcePermission).filter(
            SharedResourcePermission.id.in_(ids)
        ).count()
        assert remaining == 1


class TestExpiredPermissions:
    """过期权限相关测试"""

    def test_expired_permission_detection(self, admin_client, db_session):
        """is_expired 字段应正确标识过期权限"""
        from services.auth.models import SharedResourcePermission, User

        admin = db_session.query(User).filter(User.username == "admin").first()

        # 创建一条已过期的权限
        expired_perm = SharedResourcePermission(
            grantee_type="user",
            grantee_id=admin.id,
            resource_type="datasource",
            resource_id="ds_expired",
            resource_name="已过期数据源",
            permission_level="read",
            granted_by=admin.id,
            expires_at=datetime.utcnow() - timedelta(days=1),  # 已过期
        )
        # 创建一条未过期的权限
        valid_perm = SharedResourcePermission(
            grantee_type="user",
            grantee_id=admin.id,
            resource_type="datasource",
            resource_id="ds_valid",
            resource_name="有效数据源",
            permission_level="read",
            granted_by=admin.id,
            expires_at=datetime.utcnow() + timedelta(days=30),  # 未过期
        )
        db_session.add_all([expired_perm, valid_perm])
        db_session.commit()

        resp = admin_client.get("/api/permissions/shared")
        assert resp.status_code == 200
        data = resp.json()

        expired = [p for p in data["permissions"] if p.get("is_expired") is True]
        valid = [p for p in data["permissions"] if p.get("is_expired") is False]

        assert len(expired) >= 1
        assert len(valid) >= 1
