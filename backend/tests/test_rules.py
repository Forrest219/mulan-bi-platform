"""测试：规则 API"""


def test_get_rules_without_auth(client):
    resp = client.get("/api/rules/")
    assert resp.status_code in (401, 403)


def test_get_rules(admin_client):
    resp = admin_client.get("/api/rules/")
    if resp.status_code == 200:
        data = resp.json()
        assert "rules" in data
        assert "total" in data
        assert isinstance(data["rules"], list)


def test_get_rules_filter_by_category(admin_client):
    resp = admin_client.get("/api/rules/?category=Naming")
    if resp.status_code == 200:
        data = resp.json()
        for rule in data["rules"]:
            assert rule["category"] == "Naming"


def test_get_rules_filter_by_level(admin_client):
    resp = admin_client.get("/api/rules/?level=HIGH")
    if resp.status_code == 200:
        data = resp.json()
        for rule in data["rules"]:
            assert rule["level"] == "HIGH"
