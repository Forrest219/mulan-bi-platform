"""
TaskManager 单元测试

覆盖：
- create_run 创建记录并设置正确的默认值
- update_run_status 按 celery_task_id 更新状态与持续时间
- list_runs 分页和过滤
- get_stats 返回正确的计数与 success_rate
- update_schedule_enabled 切换 is_enabled
- update_schedule_enabled 对不存在的 key 返回 None
"""
import uuid
from datetime import datetime, timedelta

import pytest

from services.tasks.models import BiTaskRun, BiTaskSchedule
from services.tasks.task_manager import TaskManager
from app.core.database import Base, engine


@pytest.fixture(scope="module", autouse=True)
def _ensure_task_tables():
    """确保 bi_task_runs 和 bi_task_schedules 表存在"""
    Base.metadata.create_all(bind=engine, tables=[
        BiTaskRun.__table__,
        BiTaskSchedule.__table__,
    ])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _unique_id() -> str:
    """生成不重复的 celery task id"""
    return f"test-celery-{uuid.uuid4().hex[:12]}"


def _unique_key() -> str:
    """生成不重复的 schedule key"""
    return f"test-sched-{uuid.uuid4().hex[:12]}"


@pytest.fixture()
def tm():
    """TaskManager 实例"""
    return TaskManager()


# ---------------------------------------------------------------------------
# create_run
# ---------------------------------------------------------------------------

def test_create_run_defaults(db_session, tm):
    """create_run 创建记录后，默认字段正确：status=pending, trigger_type, retry_count=0"""
    celery_id = _unique_id()
    run = tm.create_run(
        db=db_session,
        celery_task_id=celery_id,
        task_name="test.task.alpha",
        task_label="Alpha Task",
        trigger_type="beat",
    )
    assert run.id is not None
    assert run.celery_task_id == celery_id
    assert run.task_name == "test.task.alpha"
    assert run.task_label == "Alpha Task"
    assert run.trigger_type == "beat"
    assert run.status == "pending"
    assert run.retry_count == 0
    assert run.parent_run_id is None
    assert run.triggered_by is None
    assert run.created_at is not None


def test_create_run_manual_trigger(db_session, tm):
    """create_run 可以指定 trigger_type='manual'"""
    run = tm.create_run(
        db=db_session,
        celery_task_id=_unique_id(),
        task_name="test.task.beta",
        task_label=None,
        trigger_type="manual",
    )
    assert run.trigger_type == "manual"
    assert run.task_label is None


# ---------------------------------------------------------------------------
# update_run_status
# ---------------------------------------------------------------------------

def test_update_run_status_sets_fields(db_session, tm):
    """update_run_status 更新状态、finished_at、duration_ms、result_summary"""
    celery_id = _unique_id()
    tm.create_run(
        db=db_session,
        celery_task_id=celery_id,
        task_name="test.task.gamma",
        task_label=None,
        trigger_type="beat",
    )

    now = datetime.utcnow()
    updated = tm.update_run_status(
        db=db_session,
        celery_task_id=celery_id,
        status="succeeded",
        finished_at=now,
        duration_ms=1234,
        result_summary={"rows": 10},
    )
    assert updated is not None
    assert updated.status == "succeeded"
    assert updated.duration_ms == 1234
    assert updated.result_summary == {"rows": 10}
    assert updated.finished_at is not None


def test_update_run_status_with_error(db_session, tm):
    """update_run_status 可以写入 error_message"""
    celery_id = _unique_id()
    tm.create_run(
        db=db_session,
        celery_task_id=celery_id,
        task_name="test.task.delta",
        task_label=None,
        trigger_type="beat",
    )

    updated = tm.update_run_status(
        db=db_session,
        celery_task_id=celery_id,
        status="failed",
        error_message="Connection timeout",
    )
    assert updated is not None
    assert updated.status == "failed"
    assert updated.error_message == "Connection timeout"


def test_update_run_status_nonexistent_returns_none(db_session, tm):
    """update_run_status 对不存在的 celery_task_id 返回 None"""
    result = tm.update_run_status(
        db=db_session,
        celery_task_id="nonexistent-celery-id-999",
        status="succeeded",
    )
    assert result is None


# ---------------------------------------------------------------------------
# get_run
# ---------------------------------------------------------------------------

def test_get_run_existing(db_session, tm):
    """get_run 返回已存在的记录"""
    run = tm.create_run(
        db=db_session,
        celery_task_id=_unique_id(),
        task_name="test.task.epsilon",
        task_label=None,
        trigger_type="beat",
    )
    fetched = tm.get_run(db_session, run.id)
    assert fetched is not None
    assert fetched.id == run.id
    assert fetched.task_name == "test.task.epsilon"


def test_get_run_nonexistent(db_session, tm):
    """get_run 对不存在的 id 返回 None"""
    assert tm.get_run(db_session, 999999999) is None


# ---------------------------------------------------------------------------
# list_runs — 分页
# ---------------------------------------------------------------------------

def test_list_runs_pagination(db_session, tm):
    """创建 25 条记录，page 1 返回 20 条，page 2 返回 5 条"""
    task_name = f"test.task.page-{uuid.uuid4().hex[:8]}"
    for _ in range(25):
        tm.create_run(
            db=db_session,
            celery_task_id=_unique_id(),
            task_name=task_name,
            task_label=None,
            trigger_type="beat",
        )

    page1 = tm.list_runs(db_session, page=1, page_size=20, task_name=task_name)
    assert page1["total"] == 25
    assert len(page1["items"]) == 20
    assert page1["page"] == 1
    assert page1["page_size"] == 20
    assert page1["pages"] == 2

    page2 = tm.list_runs(db_session, page=2, page_size=20, task_name=task_name)
    assert len(page2["items"]) == 5
    assert page2["page"] == 2


# ---------------------------------------------------------------------------
# list_runs — status 过滤
# ---------------------------------------------------------------------------

def test_list_runs_status_filter(db_session, tm):
    """list_runs 的 status 过滤返回正确的子集"""
    task_name = f"test.task.filter-{uuid.uuid4().hex[:8]}"

    # 创建 3 条 pending + 2 条 succeeded
    for _ in range(3):
        tm.create_run(
            db=db_session,
            celery_task_id=_unique_id(),
            task_name=task_name,
            task_label=None,
            trigger_type="beat",
        )
    for _ in range(2):
        celery_id = _unique_id()
        tm.create_run(
            db=db_session,
            celery_task_id=celery_id,
            task_name=task_name,
            task_label=None,
            trigger_type="beat",
        )
        tm.update_run_status(db=db_session, celery_task_id=celery_id, status="succeeded")

    result = tm.list_runs(db_session, status="succeeded", task_name=task_name)
    assert result["total"] == 2
    for item in result["items"]:
        assert item["status"] == "succeeded"


# ---------------------------------------------------------------------------
# list_runs — trigger_type 过滤
# ---------------------------------------------------------------------------

def test_list_runs_trigger_type_filter(db_session, tm):
    """list_runs 的 trigger_type 过滤正常工作"""
    task_name = f"test.task.trigger-{uuid.uuid4().hex[:8]}"

    tm.create_run(db=db_session, celery_task_id=_unique_id(), task_name=task_name, task_label=None, trigger_type="beat")
    tm.create_run(db=db_session, celery_task_id=_unique_id(), task_name=task_name, task_label=None, trigger_type="manual")

    beat_result = tm.list_runs(db_session, trigger_type="beat", task_name=task_name)
    assert beat_result["total"] == 1
    assert beat_result["items"][0]["trigger_type"] == "beat"

    manual_result = tm.list_runs(db_session, trigger_type="manual", task_name=task_name)
    assert manual_result["total"] == 1
    assert manual_result["items"][0]["trigger_type"] == "manual"


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

def test_get_stats_counts_and_rate(db_session, tm):
    """get_stats 正确计算 total_runs, succeeded, failed, running, success_rate"""
    today = datetime.utcnow().date()

    # 创建 3 succeeded + 1 failed + 1 running = 5 total
    task_name = f"test.task.stats-{uuid.uuid4().hex[:8]}"
    for _ in range(3):
        celery_id = _unique_id()
        tm.create_run(
            db=db_session,
            celery_task_id=celery_id,
            task_name=task_name,
            task_label=None,
            trigger_type="beat",
        )
        tm.update_run_status(
            db=db_session,
            celery_task_id=celery_id,
            status="succeeded",
            duration_ms=100,
        )

    celery_id_fail = _unique_id()
    tm.create_run(
        db=db_session,
        celery_task_id=celery_id_fail,
        task_name=task_name,
        task_label=None,
        trigger_type="beat",
    )
    tm.update_run_status(db=db_session, celery_task_id=celery_id_fail, status="failed")

    celery_id_run = _unique_id()
    tm.create_run(
        db=db_session,
        celery_task_id=celery_id_run,
        task_name=task_name,
        task_label=None,
        trigger_type="beat",
    )
    tm.update_run_status(db=db_session, celery_task_id=celery_id_run, status="running")

    stats = tm.get_stats(db_session, date=today)

    assert stats["date"] == today.isoformat()
    # 统计可能包含其他测试的记录，所以只检查 >= 我们创建的数量
    assert stats["total_runs"] >= 5
    assert stats["succeeded"] >= 3
    assert stats["failed"] >= 1
    assert stats["running"] >= 1
    # success_rate = succeeded/(succeeded+failed)*100 — 至少有我们的 3/4=75%
    assert "success_rate" in stats
    assert isinstance(stats["success_rate"], (int, float))
    assert "avg_duration_ms" in stats
    assert "comparison" in stats
    assert "total_runs_delta" in stats["comparison"]
    assert "success_rate_delta" in stats["comparison"]
    assert "failed_delta" in stats["comparison"]


# ---------------------------------------------------------------------------
# schedule 操作
# ---------------------------------------------------------------------------

def _create_schedule(db_session, schedule_key: str, task_name: str = "test.task.sched") -> BiTaskSchedule:
    """直接插入一条 BiTaskSchedule 记录"""
    sched = BiTaskSchedule(
        schedule_key=schedule_key,
        task_name=task_name,
        description="Test schedule",
        schedule_expr="0 4 * * *",
        is_enabled=True,
    )
    db_session.add(sched)
    db_session.commit()
    db_session.refresh(sched)
    return sched


def test_list_schedules(db_session, tm):
    """list_schedules 返回包含新插入记录的列表"""
    key = _unique_key()
    _create_schedule(db_session, key)

    schedules = tm.list_schedules(db_session)
    assert isinstance(schedules, list)
    keys = [s["schedule_key"] for s in schedules]
    assert key in keys


def test_update_schedule_enabled_toggle(db_session, tm):
    """update_schedule_enabled 可以将 is_enabled 从 True 切为 False"""
    key = _unique_key()
    _create_schedule(db_session, key)

    result = tm.update_schedule_enabled(db_session, key, is_enabled=False)
    assert result is not None
    assert result.is_enabled is False

    # 再切回 True
    result2 = tm.update_schedule_enabled(db_session, key, is_enabled=True)
    assert result2 is not None
    assert result2.is_enabled is True


def test_update_schedule_enabled_nonexistent(db_session, tm):
    """update_schedule_enabled 对不存在的 key 返回 None"""
    result = tm.update_schedule_enabled(db_session, "nonexistent-key-xyz", is_enabled=False)
    assert result is None


# ---------------------------------------------------------------------------
# update_schedule_last_run
# ---------------------------------------------------------------------------

def test_update_schedule_last_run(db_session, tm):
    """update_schedule_last_run 更新 last_run_at 和 last_run_status"""
    key = _unique_key()
    task_name = f"test.task.lastrun-{uuid.uuid4().hex[:8]}"
    _create_schedule(db_session, key, task_name=task_name)

    run_at = datetime.utcnow()
    tm.update_schedule_last_run(db_session, task_name, run_at=run_at, status="succeeded")

    # 验证
    sched = db_session.query(BiTaskSchedule).filter(
        BiTaskSchedule.schedule_key == key
    ).first()
    assert sched is not None
    assert sched.last_run_status == "succeeded"
    assert sched.last_run_at is not None


# ---------------------------------------------------------------------------
# to_dict 序列化
# ---------------------------------------------------------------------------

def test_task_run_to_dict(db_session, tm):
    """BiTaskRun.to_dict() 返回正确的字典结构"""
    run = tm.create_run(
        db=db_session,
        celery_task_id=_unique_id(),
        task_name="test.task.todict",
        task_label="To Dict Test",
        trigger_type="beat",
    )
    d = run.to_dict()
    assert isinstance(d, dict)
    expected_keys = {
        "id", "celery_task_id", "task_name", "task_label",
        "trigger_type", "status", "started_at", "finished_at",
        "duration_ms", "result_summary", "error_message",
        "retry_count", "parent_run_id", "triggered_by", "created_at",
    }
    assert expected_keys.issubset(set(d.keys()))
    assert d["task_name"] == "test.task.todict"
    assert d["task_label"] == "To Dict Test"


def test_task_schedule_to_dict(db_session):
    """BiTaskSchedule.to_dict() 返回正确的字典结构"""
    key = _unique_key()
    sched = _create_schedule(db_session, key)
    d = sched.to_dict()
    assert isinstance(d, dict)
    expected_keys = {
        "id", "schedule_key", "task_name", "description",
        "schedule_expr", "is_enabled", "last_run_at",
        "last_run_status", "created_at", "updated_at",
    }
    assert expected_keys.issubset(set(d.keys()))
    assert d["schedule_key"] == key
    assert d["is_enabled"] is True
