"""测试：任务状态 API"""


def test_get_task_status_not_found(admin_client):
    resp = admin_client.get("/api/tasks/nonexistent-task-id/status")
    assert resp.status_code in (200, 404), f"Unexpected status {resp.status_code}: {resp.text}"
