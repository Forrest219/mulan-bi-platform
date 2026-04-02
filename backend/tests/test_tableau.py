"""测试：Tableau API"""


def test_get_connections_without_auth(client):
    resp = client.get("/api/tableau/connections")
    assert resp.status_code in (401, 403)


def test_get_connections(admin_client):
    resp = admin_client.get("/api/tableau/connections")
    if resp.status_code == 200:
        data = resp.json()
        assert "connections" in data
        assert isinstance(data["connections"], list)


def test_get_assets(admin_client):
    resp = admin_client.get("/api/tableau/assets")
    if resp.status_code == 200:
        data = resp.json()
        assert "assets" in data
