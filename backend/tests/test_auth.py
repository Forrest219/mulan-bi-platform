"""测试：认证 API"""


def test_login_invalid_credentials(client):
    resp = client.post("/api/auth/login", json={"username": "nonexistent", "password": "wrong"})
    assert resp.status_code in (401, 400)


def test_me_without_auth(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code in (401, 403)


def test_login_success(admin_client):
    resp = admin_client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert "username" in data or "user" in data
