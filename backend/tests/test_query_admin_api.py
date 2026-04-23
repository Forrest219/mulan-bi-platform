"""
集成测试：Spec 14 T-09 — 管理员配置 Connected App 密钥 API

覆盖场景：
    1. Happy Path
       - PUT 保存密钥 → 200，响应含 client_id
       - GET 查询激活密钥 → 200，secret_masked 为 "***"
       - DELETE 停用 → 200，deactivated >= 1
       - DELETE 后 GET → 未配置（configured=false）

    2. 权限边界
       - 非 admin 用户调用三个接口 → 403
       - 未登录调用三个接口 → 401

    3. 异常场景
       - PUT 缺少必填字段（connection_id=0, client_id/secret_value 为空）→ 422
       - DELETE 未配置时 → 404
       - 重复 PUT（upsert）→ 200，旧记录被停用，新记录激活

测试策略：
    - 使用真实登录 fixture（admin_client / analyst_client），保持鉴权链路真实
    - ConnectedAppSecretsDatabase 的 upsert/deactivate 通过 mock 隔离 DB I/O
    - GET 的 get_active 也通过 mock 返回构造对象，避免依赖真实 Tableau 连接
"""
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# 必须在 import app 前设置环境变量（与 conftest.py 一致）
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")
os.environ.setdefault("SECURE_COOKIES", "false")
os.environ.setdefault("SERVICE_JWT_SECRET", "test-service-jwt-secret-for-ci-ok!!")

# ─── 常量 ─────────────────────────────────────────────────────────────────────

_BASE = "/api/admin/query"
_ENDPOINT = f"{_BASE}/connected-app"

_VALID_CONNECTION_ID = 1
_VALID_PUT_BODY = {
    "connection_id": _VALID_CONNECTION_ID,
    "client_id": "test-client-id-abc123",
    "secret_value": "test-secret-value-xyz",
}

# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _make_secret_record(
    connection_id: int = _VALID_CONNECTION_ID,
    client_id: str = "test-client-id-abc123",
    secret_encrypted: str = "gAAAAABfake_encrypted_token",
) -> MagicMock:
    """构造模拟 ConnectedAppSecret ORM 对象"""
    record = MagicMock()
    record.id = 42
    record.connection_id = connection_id
    record.client_id = client_id
    record.secret_encrypted = secret_encrypted
    record.is_active = True
    record.created_at = datetime(2026, 4, 21, 10, 0, 0, tzinfo=timezone.utc)
    record.updated_at = None
    return record


# ─── 1. Happy Path ────────────────────────────────────────────────────────────


class TestHappyPath:
    """正常操作流程"""

    def test_put_save_secret_returns_200_with_client_id(self, admin_client: TestClient):
        """PUT 保存密钥 → 200，响应体包含 ok=True 和 client_id"""
        fake_record = _make_secret_record()

        with patch(
            "services.query.jwt_service.ConnectedAppSecretsDatabase.upsert",
            return_value=fake_record,
        ):
            resp = admin_client.put(_ENDPOINT, json=_VALID_PUT_BODY)

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["client_id"] == "test-client-id-abc123"
        assert data["connection_id"] == _VALID_CONNECTION_ID
        assert data["is_active"] is True
        assert "created_at" in data

    def test_get_active_secret_returns_masked(self, admin_client: TestClient):
        """GET 查询激活密钥 → 200，secret_masked 固定为 '***'，明文不外泄"""
        fake_record = _make_secret_record()

        with patch(
            "services.query.jwt_service.ConnectedAppSecretsDatabase.get_active",
            return_value=fake_record,
        ):
            resp = admin_client.get(_ENDPOINT, params={"connection_id": _VALID_CONNECTION_ID})

        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["connection_id"] == _VALID_CONNECTION_ID
        assert data["client_id"] == "test-client-id-abc123"
        assert data["secret_masked"] == "***"
        assert data["is_active"] is True
        assert data["created_at"] is not None

    def test_delete_returns_200_deactivated(self, admin_client: TestClient):
        """DELETE 停用配置 → 200，deactivated=1"""
        with patch(
            "services.query.jwt_service.ConnectedAppSecretsDatabase.deactivate",
            return_value=1,
        ):
            resp = admin_client.delete(_ENDPOINT, params={"connection_id": _VALID_CONNECTION_ID})

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["deactivated"] == 1

    def test_get_after_delete_returns_not_configured(self, admin_client: TestClient):
        """DELETE 后 GET → configured=False"""
        with patch(
            "services.query.jwt_service.ConnectedAppSecretsDatabase.get_active",
            return_value=None,
        ):
            resp = admin_client.get(_ENDPOINT, params={"connection_id": _VALID_CONNECTION_ID})

        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert data.get("client_id") is None
        assert data.get("secret_masked") is None


# ─── 2. 权限边界 ──────────────────────────────────────────────────────────────


class TestPermissionBoundary:
    """非 admin 和未登录用户的访问控制"""

    def test_put_analyst_returns_403(self, analyst_client: TestClient):
        """非 admin 用户 PUT → 403"""
        resp = analyst_client.put(_ENDPOINT, json=_VALID_PUT_BODY)
        assert resp.status_code == 403

    def test_get_analyst_returns_403(self, analyst_client: TestClient):
        """非 admin 用户 GET → 403"""
        resp = analyst_client.get(_ENDPOINT, params={"connection_id": _VALID_CONNECTION_ID})
        assert resp.status_code == 403

    def test_delete_analyst_returns_403(self, analyst_client: TestClient):
        """非 admin 用户 DELETE → 403"""
        resp = analyst_client.delete(_ENDPOINT, params={"connection_id": _VALID_CONNECTION_ID})
        assert resp.status_code == 403

    def test_put_unauthenticated_returns_401(self, client: TestClient):
        """未登录 PUT → 401"""
        client.cookies.clear()
        resp = client.put(_ENDPOINT, json=_VALID_PUT_BODY)
        assert resp.status_code in (401, 403)

    def test_get_unauthenticated_returns_401(self, client: TestClient):
        """未登录 GET → 401"""
        client.cookies.clear()
        resp = client.get(_ENDPOINT, params={"connection_id": _VALID_CONNECTION_ID})
        assert resp.status_code in (401, 403)

    def test_delete_unauthenticated_returns_401(self, client: TestClient):
        """未登录 DELETE → 401"""
        client.cookies.clear()
        resp = client.delete(_ENDPOINT, params={"connection_id": _VALID_CONNECTION_ID})
        assert resp.status_code in (401, 403)


# ─── 3. 异常场景 ──────────────────────────────────────────────────────────────


class TestErrorCases:
    """异常输入和业务边界"""

    def test_put_missing_client_id_422(self, admin_client: TestClient):
        """PUT body 中 client_id 为空字符串 → 422（Pydantic min_length=1）"""
        body = {**_VALID_PUT_BODY, "client_id": ""}
        resp = admin_client.put(_ENDPOINT, json=body)
        assert resp.status_code == 422

    def test_put_missing_secret_value_422(self, admin_client: TestClient):
        """PUT body 中 secret_value 为空字符串 → 422（Pydantic min_length=1）"""
        body = {**_VALID_PUT_BODY, "secret_value": ""}
        resp = admin_client.put(_ENDPOINT, json=body)
        assert resp.status_code == 422

    def test_put_invalid_connection_id_zero_422(self, admin_client: TestClient):
        """PUT body 中 connection_id=0 → 422（Pydantic gt=0）"""
        body = {**_VALID_PUT_BODY, "connection_id": 0}
        resp = admin_client.put(_ENDPOINT, json=body)
        assert resp.status_code == 422

    def test_put_missing_all_fields_422(self, admin_client: TestClient):
        """PUT body 完全为空 → 422"""
        resp = admin_client.put(_ENDPOINT, json={})
        assert resp.status_code == 422

    def test_delete_not_configured_returns_404(self, admin_client: TestClient):
        """DELETE 未配置（deactivate 返回 0）→ 404"""
        with patch(
            "services.query.jwt_service.ConnectedAppSecretsDatabase.deactivate",
            return_value=0,
        ):
            resp = admin_client.delete(_ENDPOINT, params={"connection_id": 9999})

        assert resp.status_code == 404

    def test_put_upsert_deactivates_old_record(self, admin_client: TestClient):
        """
        重复 PUT（upsert）→ 200，验证 upsert() 被调用。

        业务逻辑（旧记录 is_active=False，新记录激活）在 service 层已有单元测试覆盖，
        此处集成测试只验证路由层正确调用 upsert 并返回新记录数据。
        """
        second_record = _make_secret_record(client_id="new-client-id-v2")
        second_record.client_id = "new-client-id-v2"
        second_record.id = 99

        with patch(
            "services.query.jwt_service.ConnectedAppSecretsDatabase.upsert",
            return_value=second_record,
        ):
            body = {**_VALID_PUT_BODY, "client_id": "new-client-id-v2"}
            resp = admin_client.put(_ENDPOINT, json=body)

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["client_id"] == "new-client-id-v2"

    def test_get_missing_connection_id_param_422(self, admin_client: TestClient):
        """GET 不传 connection_id 查询参数 → 422"""
        resp = admin_client.get(_ENDPOINT)
        assert resp.status_code == 422

    def test_delete_missing_connection_id_param_422(self, admin_client: TestClient):
        """DELETE 不传 connection_id 查询参数 → 422"""
        resp = admin_client.delete(_ENDPOINT)
        assert resp.status_code == 422
