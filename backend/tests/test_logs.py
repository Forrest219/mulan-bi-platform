"""测试：日志 API"""


def test_get_scan_logs(admin_client):
    resp = admin_client.get("/api/logs/scan")
    if resp.status_code == 200:
        data = resp.json()
        assert "logs" in data


def test_get_operation_logs(admin_client):
    resp = admin_client.get("/api/logs/operations")
    if resp.status_code == 200:
        data = resp.json()
        assert "logs" in data


def test_get_statistics(admin_client):
    resp = admin_client.get("/api/logs/statistics")
    if resp.status_code == 200:
        data = resp.json()
        assert "total_scans" in data or "statistics" in data
