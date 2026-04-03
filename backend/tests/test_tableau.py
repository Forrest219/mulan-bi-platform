"""测试：Tableau API"""


def test_get_connections_without_auth(client):
    resp = client.get("/api/tableau/connections")
    assert resp.status_code in (401, 403)


def test_get_connections(admin_client):
    resp = admin_client.get("/api/tableau/connections")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "connections" in data
    assert isinstance(data["connections"], list)


def test_get_assets_requires_connection_id(admin_client):
    """GET /api/tableau/assets 需要 connection_id，未提供时返回 422"""
    resp = admin_client.get("/api/tableau/assets")
    assert resp.status_code == 422, f"Expected 422 for missing connection_id, got {resp.status_code}: {resp.text}"
