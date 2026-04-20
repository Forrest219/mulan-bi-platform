"""
语义维护 - 发布管理 API 集成测试

路由前缀：/api/semantic-maintenance
端点：
  POST /publish/diff         - 预览发布差异
  POST /publish/datasource   - 发布数据源语义
  POST /publish/fields       - 批量发布字段语义
  POST /publish/retry        - 重试失败发布
  POST /publish/rollback     - 回滚已发布内容

覆盖范围：
- 未认证访问被拦截（401）
- 权限不足被拦截（403）
- 发布到不存在的 connection 时返回正确错误码（404）
- Happy path（需要 Tableau Server）标记为 skip

注意：所有需要真实 Tableau Server 连接的测试均标记为
  @pytest.mark.skip(reason="需要 Tableau MCP")
"""
import pytest
from fastapi.testclient import TestClient


# -------------------------------------------------------------------------
# 测试数据常量
# -------------------------------------------------------------------------
_NONEXISTENT_CONNECTION_ID = 999999

_PUBLISH_DS_PAYLOAD = {
    "ds_id": 1,
    "connection_id": _NONEXISTENT_CONNECTION_ID,
    "simulate": True,
}

_PUBLISH_FIELDS_PAYLOAD = {
    "connection_id": _NONEXISTENT_CONNECTION_ID,
    "field_ids": [1, 2, 3],
    "simulate": True,
}

_DIFF_PAYLOAD = {
    "connection_id": _NONEXISTENT_CONNECTION_ID,
    "object_type": "datasource",
    "object_id": 1,
}

_RETRY_PAYLOAD = {
    "log_id": 1,
    "connection_id": _NONEXISTENT_CONNECTION_ID,
}

_ROLLBACK_PAYLOAD = {
    "log_id": 1,
    "connection_id": _NONEXISTENT_CONNECTION_ID,
}


# -------------------------------------------------------------------------
# 未认证访问被拦截
# -------------------------------------------------------------------------

def test_publish_diff_unauthenticated(client: TestClient):
    """未登录时，POST /api/semantic-maintenance/publish/diff 返回 401"""
    client.cookies.clear()
    resp = client.post("/api/semantic-maintenance/publish/diff", json=_DIFF_PAYLOAD)
    assert resp.status_code == 401


def test_publish_datasource_unauthenticated(client: TestClient):
    """未登录时，POST /api/semantic-maintenance/publish/datasource 返回 401"""
    client.cookies.clear()
    resp = client.post("/api/semantic-maintenance/publish/datasource", json=_PUBLISH_DS_PAYLOAD)
    assert resp.status_code == 401


def test_publish_fields_unauthenticated(client: TestClient):
    """未登录时，POST /api/semantic-maintenance/publish/fields 返回 401"""
    client.cookies.clear()
    resp = client.post("/api/semantic-maintenance/publish/fields", json=_PUBLISH_FIELDS_PAYLOAD)
    assert resp.status_code == 401


def test_publish_retry_unauthenticated(client: TestClient):
    """未登录时，POST /api/semantic-maintenance/publish/retry 返回 401"""
    client.cookies.clear()
    resp = client.post("/api/semantic-maintenance/publish/retry", json=_RETRY_PAYLOAD)
    assert resp.status_code == 401


def test_publish_rollback_unauthenticated(client: TestClient):
    """未登录时，POST /api/semantic-maintenance/publish/rollback 返回 401"""
    client.cookies.clear()
    resp = client.post("/api/semantic-maintenance/publish/rollback", json=_ROLLBACK_PAYLOAD)
    assert resp.status_code == 401


# -------------------------------------------------------------------------
# 权限不足被拦截（analyst 不是 admin/publisher）
# -------------------------------------------------------------------------

def test_publish_datasource_requires_publisher_or_admin(analyst_client: TestClient):
    """analyst 角色尝试发布数据源语义，返回 403（需要 publisher 或 admin）"""
    resp = analyst_client.post(
        "/api/semantic-maintenance/publish/datasource",
        json=_PUBLISH_DS_PAYLOAD,
    )
    assert resp.status_code == 403


def test_publish_fields_requires_publisher_or_admin(analyst_client: TestClient):
    """analyst 角色尝试批量发布字段语义，返回 403"""
    resp = analyst_client.post(
        "/api/semantic-maintenance/publish/fields",
        json=_PUBLISH_FIELDS_PAYLOAD,
    )
    assert resp.status_code == 403


def test_publish_retry_requires_publisher_or_admin(analyst_client: TestClient):
    """analyst 角色尝试重试发布，返回 403"""
    resp = analyst_client.post(
        "/api/semantic-maintenance/publish/retry",
        json=_RETRY_PAYLOAD,
    )
    assert resp.status_code == 403


def test_publish_rollback_requires_admin(analyst_client: TestClient):
    """analyst 角色尝试回滚发布，返回 403（仅 admin 可回滚）"""
    resp = analyst_client.post(
        "/api/semantic-maintenance/publish/rollback",
        json=_ROLLBACK_PAYLOAD,
    )
    assert resp.status_code == 403


# -------------------------------------------------------------------------
# admin 访问不存在的 connection 时返回正确错误码
# -------------------------------------------------------------------------

def test_publish_diff_nonexistent_connection_returns_404(admin_client: TestClient):
    """admin 调用 diff 接口时，connection_id 不存在，返回 404"""
    resp = admin_client.post(
        "/api/semantic-maintenance/publish/diff",
        json=_DIFF_PAYLOAD,
    )
    assert resp.status_code == 404


def test_publish_datasource_nonexistent_connection_returns_404(admin_client: TestClient):
    """admin 发布数据源语义时，connection_id 不存在，返回 404"""
    resp = admin_client.post(
        "/api/semantic-maintenance/publish/datasource",
        json=_PUBLISH_DS_PAYLOAD,
    )
    assert resp.status_code == 404


def test_publish_fields_nonexistent_connection_returns_404(admin_client: TestClient):
    """admin 批量发布字段时，connection_id 不存在，返回 404"""
    resp = admin_client.post(
        "/api/semantic-maintenance/publish/fields",
        json=_PUBLISH_FIELDS_PAYLOAD,
    )
    assert resp.status_code == 404


def test_publish_retry_nonexistent_connection_returns_404(admin_client: TestClient):
    """admin 重试发布时，connection_id 不存在，返回 404"""
    resp = admin_client.post(
        "/api/semantic-maintenance/publish/retry",
        json=_RETRY_PAYLOAD,
    )
    assert resp.status_code == 404


def test_publish_rollback_nonexistent_connection_returns_404(admin_client: TestClient):
    """admin 回滚发布时，connection_id 不存在，返回 404"""
    resp = admin_client.post(
        "/api/semantic-maintenance/publish/rollback",
        json=_ROLLBACK_PAYLOAD,
    )
    assert resp.status_code == 404


# -------------------------------------------------------------------------
# diff 接口 object_type 校验
# -------------------------------------------------------------------------

def test_publish_diff_invalid_object_type_returns_400(admin_client: TestClient):
    """
    diff 接口对 object_type 的校验：传入无效类型时，
    如果 connection 不存在则先 404；如果 connection 存在则 400。
    此处用不存在的 connection，期望 404。
    （若要测 400 路径需要 Tableau MCP）
    """
    resp = admin_client.post(
        "/api/semantic-maintenance/publish/diff",
        json={
            "connection_id": _NONEXISTENT_CONNECTION_ID,
            "object_type": "invalid_type",
            "object_id": 1,
        },
    )
    # connection 不存在，先返回 404（权限校验在前）
    assert resp.status_code == 404


# -------------------------------------------------------------------------
# Happy path（需要真实 Tableau Server）
# -------------------------------------------------------------------------

@pytest.mark.skip(reason="需要 Tableau MCP：必须有真实的 Tableau Server 连接")
def test_publish_datasource_happy_path(admin_client: TestClient):
    """
    发布数据源语义 happy path。
    前置条件：
      1. 数据库中存在 tableau_connections 记录（connection_id）
      2. 数据库中存在对应 semantic_maintenance 数据源语义（ds_id）
      3. Tableau Server 可达且 PAT token 有效
    """
    payload = {
        "ds_id": 1,
        "connection_id": 1,
        "simulate": True,  # 模拟模式，不真正写入 Tableau
    }
    resp = admin_client.post("/api/semantic-maintenance/publish/datasource", json=payload)
    assert resp.status_code == 200


@pytest.mark.skip(reason="需要 Tableau MCP：必须有真实的 Tableau Server 连接")
def test_publish_fields_happy_path(admin_client: TestClient):
    """
    批量发布字段语义 happy path。
    前置条件同上。
    """
    payload = {
        "connection_id": 1,
        "field_ids": [1],
        "simulate": True,
    }
    resp = admin_client.post("/api/semantic-maintenance/publish/fields", json=payload)
    assert resp.status_code == 200
