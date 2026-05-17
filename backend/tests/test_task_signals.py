"""Celery signal history recording regressions."""
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
import uuid

import pytest

from services.auth.models import User
from services.tasks.models import BiTaskRun
from services.tasks import signals


@contextmanager
def _db_context(db):
    yield db


def _task_id(prefix: str = "signal") -> str:
    return f"test-{prefix}-{uuid.uuid4().hex[:12]}"


def _sender(name: str = "services.tasks.tableau_tasks.sync_connection_task"):
    return SimpleNamespace(name=name)


def _task(headers=None, retries: int = 0):
    return SimpleNamespace(request=SimpleNamespace(headers=headers or {}, retries=retries))


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        (None, None),
        ("not-an-int", None),
    ],
)
def test_task_prerun_ignores_missing_or_invalid_triggered_by(db_session, monkeypatch, raw_value, expected):
    monkeypatch.setattr(signals, "get_db_context", lambda: _db_context(db_session))
    task_id = _task_id("prerun-invalid")
    headers = {"trigger_type": "manual"}
    if raw_value is not None:
        headers["triggered_by"] = raw_value

    signals.on_task_prerun(
        sender=_sender(),
        task_id=task_id,
        task=_task(headers=headers),
    )

    run = db_session.query(BiTaskRun).filter(BiTaskRun.celery_task_id == task_id).one()
    assert run.trigger_type == "manual"
    assert run.triggered_by == expected


def test_task_prerun_writes_triggered_by_from_headers(db_session, monkeypatch):
    monkeypatch.setattr(signals, "get_db_context", lambda: _db_context(db_session))
    user = db_session.query(User).filter(User.username == "admin").one()
    task_id = _task_id("prerun-user")

    signals.on_task_prerun(
        sender=_sender(),
        task_id=task_id,
        task=_task(headers={"trigger_type": "manual", "triggered_by": str(user.id)}),
    )

    run = db_session.query(BiTaskRun).filter(BiTaskRun.celery_task_id == task_id).one()
    assert run.trigger_type == "manual"
    assert run.triggered_by == user.id


def test_task_postrun_maps_error_result_to_failed_and_keeps_summary(db_session, monkeypatch):
    monkeypatch.setattr(signals, "get_db_context", lambda: _db_context(db_session))
    task_id = _task_id("postrun-error")
    run = BiTaskRun(
        celery_task_id=task_id,
        task_name="services.tasks.tableau_tasks.sync_connection_task",
        trigger_type="manual",
        status="running",
        started_at=datetime.utcnow(),
    )
    db_session.add(run)
    db_session.commit()

    result = {
        "status": "error",
        "message": "Token 解密失败",
        "sync_log_id": 14,
        "connection_id": 4,
    }
    signals.on_task_postrun(sender=_sender(), task_id=task_id, state="SUCCESS", retval=result)

    db_session.refresh(run)
    assert run.status == "failed"
    assert run.error_message == "Token 解密失败"
    assert run.result_summary == result
    assert run.finished_at is not None
    assert run.duration_ms is not None


def test_task_postrun_maps_skipped_result_to_cancelled(db_session, monkeypatch):
    monkeypatch.setattr(signals, "get_db_context", lambda: _db_context(db_session))
    task_id = _task_id("postrun-skipped")
    run = BiTaskRun(
        celery_task_id=task_id,
        task_name="services.tasks.tableau_tasks.sync_connection_task",
        trigger_type="manual",
        status="running",
        started_at=datetime.utcnow(),
    )
    db_session.add(run)
    db_session.commit()

    result = {"status": "skipped", "message": "同步任务正在进行中", "connection_id": 4}
    signals.on_task_postrun(sender=_sender(), task_id=task_id, state="SUCCESS", retval=result)

    db_session.refresh(run)
    assert run.status == "cancelled"
    assert run.error_message == "同步任务正在进行中"
    assert run.result_summary == result
