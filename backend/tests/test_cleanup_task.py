"""
Spec 33 §3.4: 90天清理任务 dry-run 测试

覆盖：
- cleanup_old_task_runs(dry_run=True) 返回 count_candidates
- cleanup_old_task_runs(dry_run=False) 实际删除并返回 count_deleted
- GET /api/tasks/cleanup-dry-run 返回 200 且含 count_candidates
- 非 admin 访问 cleanup-dry-run 返回 403
"""
import uuid
from datetime import datetime, timedelta

import pytest

from services.tasks.cleanup_tasks import cleanup_old_task_runs
from services.tasks.models import BiTaskRun


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _unique_id() -> str:
    return f"test-cleanup-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# cleanup_old_task_runs — 逻辑层单元测试
# ---------------------------------------------------------------------------

def test_cleanup_dry_run_returns_count(db_session):
    """dry_run=True 时返回 count_candidates，不删除任何记录"""
    task_name = f"test.cleanup.{uuid.uuid4().hex[:8]}"

    # 插入 3 条可清理记录（90天前 + succeeded）
    old_date = datetime.now() - timedelta(days=91)
    for i in range(3):
        run = BiTaskRun(
            celery_task_id=_unique_id(),
            task_name=task_name,
            task_label=None,
            trigger_type="beat",
            status="succeeded",
            started_at=old_date,
            finished_at=old_date,
        )
        db_session.add(run)

    # 插入 1 条不应清理的记录（90天内）
    recent = datetime.now() - timedelta(days=30)
    run_recent = BiTaskRun(
        celery_task_id=_unique_id(),
        task_name=task_name,
        task_label=None,
        trigger_type="beat",
        status="succeeded",
        started_at=recent,
    )
    db_session.add(run_recent)

    db_session.commit()

    result = cleanup_old_task_runs(dry_run=True)

    assert result["dry_run"] is True
    assert result["count_candidates"] == 3
    assert result["retention_days"] == 90
    # 验证没有被删除
    remaining = db_session.query(BiTaskRun).filter(
        BiTaskRun.task_name == task_name
    ).count()
    assert remaining == 4


def test_cleanup_dry_run_excludes_recent_and_running(db_session):
    """只清理 90天前且 status 为 succeeded/failed/cancelled 的记录"""
    task_name = f"test.cleanup.{uuid.uuid4().hex[:8]}"
    old_date = datetime.now() - timedelta(days=91)

    # succeeded（应清理）
    r1 = BiTaskRun(celery_task_id=_unique_id(), task_name=task_name,
                   trigger_type="beat", status="succeeded", started_at=old_date)
    # failed（应清理）
    r2 = BiTaskRun(celery_task_id=_unique_id(), task_name=task_name,
                   trigger_type="beat", status="failed", started_at=old_date)
    # cancelled（应清理）
    r3 = BiTaskRun(celery_task_id=_unique_id(), task_name=task_name,
                   trigger_type="beat", status="cancelled", started_at=old_date)
    # running（不应清理）
    r4 = BiTaskRun(celery_task_id=_unique_id(), task_name=task_name,
                   trigger_type="beat", status="running", started_at=old_date)
    # pending（不应清理）
    r5 = BiTaskRun(celery_task_id=_unique_id(), task_name=task_name,
                   trigger_type="beat", status="pending", started_at=old_date)

    for r in [r1, r2, r3, r4, r5]:
        db_session.add(r)
    db_session.commit()

    result = cleanup_old_task_runs(dry_run=True)

    assert result["count_candidates"] == 3
    # running 和 pending 记录仍在
    remaining = db_session.query(BiTaskRun).filter(
        BiTaskRun.task_name == task_name,
        BiTaskRun.status.in_(["running", "pending"])
    ).count()
    assert remaining == 2


def test_cleanup_dry_run_no_candidates(db_session):
    """无待清理记录时返回 0"""
    result = cleanup_old_task_runs(dry_run=True)
    assert result["dry_run"] is True
    assert result["count_candidates"] == 0


def test_cleanup_actual_delete(db_session):
    """dry_run=False 时实际删除记录"""
    task_name = f"test.cleanup.{uuid.uuid4().hex[:8]}"
    old_date = datetime.now() - timedelta(days=91)

    for i in range(2):
        run = BiTaskRun(
            celery_task_id=_unique_id(),
            task_name=task_name,
            trigger_type="beat",
            status="succeeded",
            started_at=old_date,
        )
        db_session.add(run)
    db_session.commit()

    result = cleanup_old_task_runs(dry_run=False)

    assert result["dry_run"] is False
    assert result["count_deleted"] == 2
    remaining = db_session.query(BiTaskRun).filter(
        BiTaskRun.task_name == task_name
    ).count()
    assert remaining == 0


# ---------------------------------------------------------------------------
# GET /api/tasks/cleanup-dry-run — API 集成测试
# ---------------------------------------------------------------------------

def test_cleanup_dry_run_api_returns_candidates(admin_client, db_session):
    """GET /api/tasks/cleanup-dry-run 返回 200 且含 count_candidates"""
    task_name = f"test.api.cleanup.{uuid.uuid4().hex[:8]}"
    old_date = datetime.now() - timedelta(days=91)

    for i in range(5):
        run = BiTaskRun(
            celery_task_id=_unique_id(),
            task_name=task_name,
            trigger_type="beat",
            status="failed",
            started_at=old_date,
        )
        db_session.add(run)
    db_session.commit()

    resp = admin_client.get("/api/tasks/cleanup-dry-run")
    assert resp.status_code == 200
    data = resp.json()
    assert "count_candidates" in data
    assert "dry_run" in data
    assert data["dry_run"] is True
    assert data["count_candidates"] >= 5


def test_cleanup_dry_run_api_analyst_forbidden(analyst_client):
    """analyst 角色访问 cleanup-dry-run 返回 403"""
    resp = analyst_client.get("/api/tasks/cleanup-dry-run")
    assert resp.status_code == 403


def test_cleanup_dry_run_api_unauthenticated(client):
    """未登录访问返回 401/403"""
    client.cookies.clear()
    resp = client.get("/api/tasks/cleanup-dry-run")
    assert resp.status_code in (401, 403)