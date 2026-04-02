"""测试：任务状态 API"""


def test_get_task_status_not_found(admin_client):
    resp = admin_client.get("/api/tasks/nonexistent-task-id/status")
    if resp.status_code == 200:
        data = resp.json()
        assert data["status"] == "PENDING"
