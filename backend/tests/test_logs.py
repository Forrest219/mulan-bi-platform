"""测试：日志 API"""


def test_get_scan_logs(admin_client):
    resp = admin_client.get("/api/logs/scan")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "logs" in data


def test_get_operation_logs(admin_client):
    resp = admin_client.get("/api/logs/operations")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "logs" in data


def test_get_statistics(admin_client):
    resp = admin_client.get("/api/logs/statistics")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "total_scans" in data or "statistics" in data
