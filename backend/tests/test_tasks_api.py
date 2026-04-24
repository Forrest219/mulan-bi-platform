"""
任务管理 API 集成测试

覆盖：
- GET /schedules 返回调度列表
- GET /runs 返回分页响应
- GET /runs/{run_id} 不存在的 id 返回 404
- GET /stats 返回统计对象
- PATCH /schedules/{key} 不存在的 key 返回 404
- POST /trigger 非白名单任务返回 400
- 未认证访问被拦截
- analyst 无法操作 admin-only 端点
"""
import pytest
from fastapi.testclient import TestClient

from services.tasks.models import BiTaskRun, BiTaskSchedule
from app.core.database import Base, engine


@pytest.fixture(scope="module", autouse=True)
def _ensure_task_tables():
    """确保 bi_task_runs 和 bi_task_schedules 表存在"""
    Base.metadata.create_all(bind=engine, tables=[
        BiTaskRun.__table__,
        BiTaskSchedule.__table__,
    ])


PREFIX = "/api/tasks"


# ---------------------------------------------------------------------------
# GET /schedules — analyst+ 可访问
# ---------------------------------------------------------------------------

def test_list_schedules_returns_list(admin_client: TestClient):
    """GET /schedules 返回包含 items 和 total 的 JSON"""
    resp = admin_client.get(f"{PREFIX}/schedules")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)


def test_list_schedules_analyst_allowed(analyst_client: TestClient):
    """analyst 角色也可以查看调度列表"""
    resp = analyst_client.get(f"{PREFIX}/schedules")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data


def test_list_schedules_unauthenticated(client: TestClient):
    """未登录访问调度列表，返回 401 或 403"""
    client.cookies.clear()
    resp = client.get(f"{PREFIX}/schedules")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /runs — 分页查询
# ---------------------------------------------------------------------------

def test_list_runs_returns_paginated(admin_client: TestClient):
    """GET /runs 返回分页结构"""
    resp = admin_client.get(f"{PREFIX}/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "pages" in data
    assert isinstance(data["items"], list)


def test_list_runs_with_filters(admin_client: TestClient):
    """GET /runs 传入过滤参数不报错"""
    resp = admin_client.get(
        f"{PREFIX}/runs",
        params={"status": "succeeded", "page": 1, "page_size": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["page_size"] == 5


def test_list_runs_invalid_page_size(admin_client: TestClient):
    """page_size 超过 100 返回 400"""
    resp = admin_client.get(
        f"{PREFIX}/runs",
        params={"page_size": 200},
    )
    assert resp.status_code == 400


def test_list_runs_unauthenticated(client: TestClient):
    """未登录访问执行记录，返回 401 或 403"""
    client.cookies.clear()
    resp = client.get(f"{PREFIX}/runs")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /runs/{run_id} — 单条记录
# ---------------------------------------------------------------------------

def test_get_run_not_found(admin_client: TestClient):
    """GET /runs/99999 不存在的 id 返回 404"""
    resp = admin_client.get(f"{PREFIX}/runs/99999")
    assert resp.status_code == 404
    data = resp.json()
    assert data["detail"]["error_code"] == "TASK_001"


def test_get_run_unauthenticated(client: TestClient):
    """未登录访问单条记录，返回 401 或 403"""
    client.cookies.clear()
    resp = client.get(f"{PREFIX}/runs/1")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /stats — 任务统计
# ---------------------------------------------------------------------------

def test_get_stats_returns_expected_keys(admin_client: TestClient):
    """GET /stats 返回统计对象，包含必需字段"""
    resp = admin_client.get(f"{PREFIX}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "date" in data
    assert "total_runs" in data
    assert "succeeded" in data
    assert "failed" in data
    assert "running" in data
    assert "success_rate" in data
    assert "avg_duration_ms" in data
    assert "comparison" in data


def test_get_stats_with_date_param(admin_client: TestClient):
    """GET /stats?date=2025-01-01 传入日期参数正常返回"""
    resp = admin_client.get(f"{PREFIX}/stats", params={"date": "2025-01-01"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["date"] == "2025-01-01"


def test_get_stats_unauthenticated(client: TestClient):
    """未登录访问统计，返回 401 或 403"""
    client.cookies.clear()
    resp = client.get(f"{PREFIX}/stats")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# PATCH /schedules/{key} — admin only
# ---------------------------------------------------------------------------

def test_patch_schedule_nonexistent(admin_client: TestClient):
    """PATCH 不存在的 schedule_key 返回 404"""
    resp = admin_client.patch(
        f"{PREFIX}/schedules/nonexistent-key-xyz",
        json={"is_enabled": False},
    )
    assert resp.status_code == 404
    data = resp.json()
    assert data["detail"]["error_code"] == "TASK_002"


def test_patch_schedule_missing_field(admin_client: TestClient):
    """PATCH 缺少 is_enabled 参数返回 400"""
    resp = admin_client.patch(
        f"{PREFIX}/schedules/some-key",
        json={},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert data["detail"]["error_code"] == "TASK_006"


def test_patch_schedule_analyst_forbidden(analyst_client: TestClient):
    """analyst 角色不能修改调度配置（admin only），返回 403"""
    resp = analyst_client.patch(
        f"{PREFIX}/schedules/some-key",
        json={"is_enabled": False},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /trigger — admin only, 白名单
# ---------------------------------------------------------------------------

def test_trigger_invalid_task_name(admin_client: TestClient):
    """POST /trigger 非白名单任务返回 400"""
    resp = admin_client.post(
        f"{PREFIX}/trigger",
        json={"task_name": "not.in.whitelist.task"},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert data["detail"]["error_code"] == "TASK_003"


def test_trigger_analyst_forbidden(analyst_client: TestClient):
    """analyst 角色不能手动触发任务，返回 403"""
    resp = analyst_client.post(
        f"{PREFIX}/trigger",
        json={"task_name": "services.tasks.tableau_tasks.sync_connection_task"},
    )
    assert resp.status_code == 403


def test_trigger_unauthenticated(client: TestClient):
    """未登录触发任务，返回 401 或 403"""
    client.cookies.clear()
    resp = client.post(
        f"{PREFIX}/trigger",
        json={"task_name": "anything"},
    )
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /{task_id}/status — legacy endpoint
# ---------------------------------------------------------------------------

def test_legacy_status_unauthenticated(client: TestClient):
    """未登录查询 legacy 状态端点，返回 401 或 403"""
    client.cookies.clear()
    resp = client.get(f"{PREFIX}/some-task-id/status")
    assert resp.status_code in (401, 403)
