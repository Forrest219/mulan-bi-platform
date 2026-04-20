"""
用户管理 API 集成测试

覆盖：
- 未认证访问被拦截（401/403）
- admin 可创建用户
- analyst/user 不能创建用户（权限矩阵）
- 创建用户后可查询
- 角色修改（admin 可改他人角色，analyst 不可）
- 不能删除自己（源码中有此限制，返回 400）

路由前缀：/api/users
"""
import time
import pytest
from fastapi.testclient import TestClient

# -------------------------------------------------------------------------
# 帮助函数
# -------------------------------------------------------------------------

def _unique_username(prefix: str = "test_user") -> str:
    """生成不重复的测试用户名（毫秒时间戳后缀）"""
    return f"{prefix}_{int(time.time() * 1000) % 100000000}"


def _create_user(admin_client: TestClient, username: str, role: str = "user") -> dict:
    """用 admin_client 创建用户，返回 response JSON（期望 200）"""
    resp = admin_client.post(
        "/api/users/",
        json={
            "username": username,
            "display_name": f"Display {username}",
            "password": "Test1234!",
            "email": f"{username}@mulan.local",
            "role": role,
        },
    )
    assert resp.status_code == 200, f"创建用户失败: {resp.status_code} {resp.text}"
    return resp.json()


def _delete_user(admin_client: TestClient, user_id: int):
    """清理：删除指定用户"""
    admin_client.delete(f"/api/users/{user_id}")


# -------------------------------------------------------------------------
# 未认证访问
# -------------------------------------------------------------------------

def test_list_users_unauthenticated(client: TestClient):
    """未登录时，GET /api/users/ 返回 401 或 403"""
    client.cookies.clear()
    resp = client.get("/api/users/")
    assert resp.status_code in (401, 403)


def test_create_user_unauthenticated(client: TestClient):
    """未登录时，POST /api/users/ 返回 401 或 403"""
    client.cookies.clear()
    resp = client.post(
        "/api/users/",
        json={
            "username": "ghost_user",
            "display_name": "Ghost",
            "password": "Ghost123!",
            "email": "ghost@mulan.local",
            "role": "user",
        },
    )
    assert resp.status_code in (401, 403)


# -------------------------------------------------------------------------
# admin 可创建用户
# -------------------------------------------------------------------------

def test_admin_can_create_user(admin_client: TestClient):
    """admin 创建用户，响应包含 user 字段和 message"""
    username = _unique_username("create_test")
    resp = admin_client.post(
        "/api/users/",
        json={
            "username": username,
            "display_name": "Create Test",
            "password": "Test1234!",
            "email": f"{username}@mulan.local",
            "role": "user",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "user" in data
    assert "message" in data
    assert data["user"]["username"] == username
    _delete_user(admin_client, data["user"]["id"])


def test_admin_can_create_user_with_analyst_role(admin_client: TestClient):
    """admin 可以创建 analyst 角色的用户"""
    username = _unique_username("analyst_role")
    data = _create_user(admin_client, username, role="analyst")
    assert data["user"]["role"] == "analyst"
    _delete_user(admin_client, data["user"]["id"])


def test_create_user_with_invalid_role_returns_400(admin_client: TestClient):
    """创建用户时传入无效角色，返回 400"""
    resp = admin_client.post(
        "/api/users/",
        json={
            "username": _unique_username("invalid_role"),
            "display_name": "Invalid",
            "password": "Test1234!",
            "role": "superadmin_does_not_exist",
        },
    )
    assert resp.status_code == 400


def test_create_duplicate_username_returns_400(admin_client: TestClient):
    """创建重复用户名的用户返回 400"""
    username = _unique_username("dup_user")
    data = _create_user(admin_client, username)
    try:
        resp = admin_client.post(
            "/api/users/",
            json={
                "username": username,
                "display_name": "Dup",
                "password": "Test1234!",
                "role": "user",
            },
        )
        assert resp.status_code == 400
    finally:
        _delete_user(admin_client, data["user"]["id"])


# -------------------------------------------------------------------------
# 非 admin 不能创建/管理用户
# -------------------------------------------------------------------------

def test_analyst_cannot_create_user(analyst_client: TestClient):
    """analyst 角色尝试创建用户，返回 401 或 403"""
    resp = analyst_client.post(
        "/api/users/",
        json={
            "username": _unique_username("analyst_create"),
            "display_name": "Analyst Created",
            "password": "Test1234!",
            "role": "user",
        },
    )
    assert resp.status_code in (401, 403)


def test_analyst_cannot_list_users(analyst_client: TestClient):
    """analyst 角色无法获取用户列表，返回 401 或 403"""
    resp = analyst_client.get("/api/users/")
    assert resp.status_code in (401, 403)


# -------------------------------------------------------------------------
# 创建后可查询
# -------------------------------------------------------------------------

def test_created_user_appears_in_list(admin_client: TestClient):
    """创建用户后，在 GET /api/users/ 列表中可以找到"""
    username = _unique_username("list_test")
    data = _create_user(admin_client, username)
    user_id = data["user"]["id"]
    try:
        resp = admin_client.get("/api/users/")
        assert resp.status_code == 200
        users = resp.json()["users"]
        user_ids = [u["id"] for u in users]
        assert user_id in user_ids
    finally:
        _delete_user(admin_client, user_id)


def test_list_users_response_has_correct_shape(admin_client: TestClient):
    """GET /api/users/ 响应包含 users 列表和 total 字段"""
    resp = admin_client.get("/api/users/")
    assert resp.status_code == 200
    data = resp.json()
    assert "users" in data
    assert "total" in data
    assert isinstance(data["users"], list)
    assert data["total"] == len(data["users"])


# -------------------------------------------------------------------------
# 角色修改
# -------------------------------------------------------------------------

def test_admin_can_update_user_role(admin_client: TestClient):
    """admin 可以修改其他用户的角色"""
    username = _unique_username("role_update")
    data = _create_user(admin_client, username, role="user")
    user_id = data["user"]["id"]
    try:
        resp = admin_client.put(
            f"/api/users/{user_id}/role",
            json={"role": "analyst"},
        )
        assert resp.status_code == 200
        assert "message" in resp.json()
    finally:
        _delete_user(admin_client, user_id)


def test_analyst_cannot_update_user_role(admin_client: TestClient, analyst_client: TestClient):
    """analyst 不能修改用户角色，返回 401 或 403"""
    username = _unique_username("role_update_target")
    data = _create_user(admin_client, username, role="user")
    user_id = data["user"]["id"]
    try:
        resp = analyst_client.put(
            f"/api/users/{user_id}/role",
            json={"role": "analyst"},
        )
        assert resp.status_code in (401, 403)
    finally:
        _delete_user(admin_client, user_id)


def test_update_user_role_with_invalid_role_returns_400(admin_client: TestClient):
    """修改用户角色时传入无效角色，返回 400"""
    username = _unique_username("bad_role")
    data = _create_user(admin_client, username)
    user_id = data["user"]["id"]
    try:
        resp = admin_client.put(
            f"/api/users/{user_id}/role",
            json={"role": "not_a_valid_role"},
        )
        assert resp.status_code == 400
    finally:
        _delete_user(admin_client, user_id)


def test_update_role_of_nonexistent_user_returns_404(admin_client: TestClient):
    """修改不存在用户的角色，返回 404"""
    resp = admin_client.put(
        "/api/users/999999/role",
        json={"role": "analyst"},
    )
    assert resp.status_code == 404


# -------------------------------------------------------------------------
# 不能删除自己
# -------------------------------------------------------------------------

def test_admin_cannot_delete_self(admin_client: TestClient):
    """admin 不能删除自己（源码 users.py 中有此防护，返回 400）"""
    # 先获取当前 admin 的 id
    resp = admin_client.get("/api/users/")
    assert resp.status_code == 200
    users = resp.json()["users"]
    admin_user = next((u for u in users if u["username"] == "admin"), None)
    assert admin_user is not None, "找不到 admin 用户"

    resp = admin_client.delete(f"/api/users/{admin_user['id']}")
    assert resp.status_code == 400


# -------------------------------------------------------------------------
# 删除用户
# -------------------------------------------------------------------------

def test_admin_can_delete_user(admin_client: TestClient):
    """admin 可以删除其他用户"""
    username = _unique_username("to_delete")
    data = _create_user(admin_client, username)
    user_id = data["user"]["id"]

    resp = admin_client.delete(f"/api/users/{user_id}")
    assert resp.status_code == 200
    assert "message" in resp.json()


def test_delete_nonexistent_user_returns_404(admin_client: TestClient):
    """删除不存在的用户返回 404"""
    resp = admin_client.delete("/api/users/999999")
    assert resp.status_code == 404


def test_analyst_cannot_delete_user(admin_client: TestClient, analyst_client: TestClient):
    """analyst 不能删除用户，返回 401 或 403"""
    username = _unique_username("analyst_del_target")
    data = _create_user(admin_client, username)
    user_id = data["user"]["id"]
    try:
        resp = analyst_client.delete(f"/api/users/{user_id}")
        assert resp.status_code in (401, 403)
    finally:
        _delete_user(admin_client, user_id)
