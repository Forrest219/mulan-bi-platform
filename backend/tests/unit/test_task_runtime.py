"""Task Runtime 单元测试（Spec 24）

覆盖：
- state_machine: TaskRunStateMachine 状态流转逻辑
- service: TaskRunService 状态机服务（含 OCC 重试）
- event_bus: 事件发射（payload 截断逻辑）
- validators: 创建校验（intent 白名单 / timeout / 并发限制 / RBAC）

前置：pytest + conftest.py（db_session fixture with rollback isolation）
"""
import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import pytest

from sqlalchemy.exc import PendingRollbackError, OperationalError

from app.core.errors import TRError, AuthError
from services.task_runtime.models import (
    TaskRun, TaskStepRun, TaskRunStatus, TaskStepRunStatus, StepType,
    InvalidStateTransitionError
)
from services.task_runtime.state_machine import TaskRunStateMachine
from services.task_runtime.service import (
    TaskRunService, TaskRunStatus as SvcTaskRunStatus,
    can_transition, is_terminal, VALID_TRANSITIONS
)
from services.task_runtime.event_bus import (
    emit_event, emit_task_queued, emit_task_started, emit_task_completed,
    emit_task_failed, emit_task_cancelled, emit_step_started,
    emit_step_completed, emit_step_failed, TaskEventType
)
from services.task_runtime.validators import TaskRunValidator, get_allowed_intents
from services.task_runtime.models_db import BiTaskRun


# =============================================================================
# fixtures
# =============================================================================

@pytest.fixture
def mock_user():
    return {"id": 1, "role": "user"}


@pytest.fixture
def mock_admin_user():
    return {"id": 99, "role": "admin"}


@pytest.fixture
def sample_task_run(db_session, mock_user):
    """创建一条待测 TaskRun（status=queued）"""
    run = BiTaskRun(
        trace_id="trace-001",
        user_id=mock_user["id"],
        intent="nlq_query",
        status="queued",
        input_payload={"query": "销售额"},
        timeout_seconds=120,
    )
    db_session.add(run)
    db_session.flush()
    return run


# =============================================================================
# state_machine — 纯内存状态机（无需 DB）
# =============================================================================

class TestTaskRunStateMachine:
    """TaskRunStateMachine 状态流转测试"""

    def _make_run(self, status: TaskRunStatus) -> TaskRun:
        now = datetime.now(timezone.utc)
        return TaskRun(
            id="run-1",
            trace_id="trace-1",
            status=status,
            created_at=now,
            updated_at=now,
        )

    # ── 合法流转 ─────────────────────────────────────────────────────────────

    def test_pending_to_running_ok(self):
        run = self._make_run(TaskRunStatus.PENDING)
        result = TaskRunStateMachine.transition(run, TaskRunStatus.RUNNING)
        assert result.status == TaskRunStatus.RUNNING
        assert result.updated_at > run.created_at  # updated_at 被更新

    def test_pending_to_cancelled_ok(self):
        run = self._make_run(TaskRunStatus.PENDING)
        result = TaskRunStateMachine.transition(run, TaskRunStatus.CANCELLED)
        assert result.status == TaskRunStatus.CANCELLED

    def test_running_to_succeeded_ok(self):
        run = self._make_run(TaskRunStatus.RUNNING)
        result = TaskRunStateMachine.transition(run, TaskRunStatus.SUCCEEDED)
        assert result.status == TaskRunStatus.SUCCEEDED

    def test_running_to_failed_ok(self):
        run = self._make_run(TaskRunStatus.RUNNING)
        result = TaskRunStateMachine.transition(run, TaskRunStatus.FAILED)
        assert result.status == TaskRunStatus.FAILED

    def test_running_to_cancelled_ok(self):
        run = self._make_run(TaskRunStatus.RUNNING)
        result = TaskRunStateMachine.transition(run, TaskRunStatus.CANCELLED)
        assert result.status == TaskRunStatus.CANCELLED

    # ── 非法流转（终态不可逆）──────────────────────────────────────────────────

    def test_succeeded_is_terminal(self):
        run = self._make_run(TaskRunStatus.SUCCEEDED)
        assert TaskRunStateMachine.is_terminal(TaskRunStatus.SUCCEEDED)
        assert not TaskRunStateMachine.can_transition(TaskRunStatus.SUCCEEDED, TaskRunStatus.RUNNING)

    def test_failed_is_terminal(self):
        run = self._make_run(TaskRunStatus.FAILED)
        assert TaskRunStateMachine.is_terminal(TaskRunStatus.FAILED)

    def test_cancelled_is_terminal(self):
        run = self._make_run(TaskRunStatus.CANCELLED)
        assert TaskRunStateMachine.is_terminal(TaskRunStatus.CANCELLED)

    def test_pending_to_succeeded_illegal(self):
        run = self._make_run(TaskRunStatus.PENDING)
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            TaskRunStateMachine.transition(run, TaskRunStatus.SUCCEEDED)
        assert "非法状态流转" in str(exc_info.value)
        assert "pending" in str(exc_info.value)
        assert "succeeded" in str(exc_info.value)

    def test_running_to_pending_illegal(self):
        run = self._make_run(TaskRunStatus.RUNNING)
        with pytest.raises(InvalidStateTransitionError):
            TaskRunStateMachine.transition(run, TaskRunStatus.PENDING)

    # ── can_transition / is_terminal ─────────────────────────────────────────

    def test_can_transition_returns_bool(self):
        assert TaskRunStateMachine.can_transition(TaskRunStatus.PENDING, TaskRunStatus.RUNNING) is True
        assert TaskRunStateMachine.can_transition(TaskRunStatus.PENDING, TaskRunStatus.SUCCEEDED) is False

    def test_is_terminal_for_all_states(self):
        assert TaskRunStateMachine.is_terminal(TaskRunStatus.PENDING) is False
        assert TaskRunStateMachine.is_terminal(TaskRunStatus.RUNNING) is False
        assert TaskRunStateMachine.is_terminal(TaskRunStatus.SUCCEEDED) is True
        assert TaskRunStateMachine.is_terminal(TaskRunStatus.FAILED) is True
        assert TaskRunStateMachine.is_terminal(TaskRunStatus.CANCELLED) is True


# =============================================================================
# service — TaskRunService（需要 DB）
# =============================================================================

class TestTaskRunServiceTransition:
    """TaskRunService.transition 状态流转 + OCC 重试"""

    def test_transition_queued_to_running(self, db_session, sample_task_run):
        svc = TaskRunService(db_session)
        run = svc.transition(sample_task_run.id, SvcTaskRunStatus.RUNNING)
        assert run.status == SvcTaskRunStatus.RUNNING
        assert run.started_at is not None

    def test_transition_to_succeeded_sets_finished_at(self, db_session, sample_task_run):
        # 先到 running
        svc = TaskRunService(db_session)
        svc.transition(sample_task_run.id, SvcTaskRunStatus.RUNNING)
        # 再到 succeeded
        run = svc.transition(
            sample_task_run.id, SvcTaskRunStatus.SUCCEEDED,
            output_payload={"result": "done"}
        )
        assert run.status == SvcTaskRunStatus.SUCCEEDED
        assert run.finished_at is not None
        assert run.output_payload == {"result": "done"}

    def test_transition_illegal_raises_trerror(self, db_session, sample_task_run):
        svc = TaskRunService(db_session)
        with pytest.raises(TRError) as exc_info:
            svc.transition(sample_task_run.id, SvcTaskRunStatus.SUCCEEDED)
        assert "illegal_state_transition" in str(exc_info.value.code)

    def test_transition_expected_from_mismatch_raises(self, db_session, sample_task_run):
        svc = TaskRunService(db_session)
        with pytest.raises(TRError) as exc_info:
            svc.transition(sample_task_run.id, SvcTaskRunStatus.RUNNING, expected_from="succeeded")
        assert exc_info.value.code == "invalid_state_transition"

    def test_transition_not_found_raises(self, db_session):
        svc = TaskRunService(db_session)
        with pytest.raises(TRError) as exc_info:
            svc.transition(99999, SvcTaskRunStatus.RUNNING)
        assert exc_info.value.code == "task_run_not_found"

    def test_transition_occ_retry_on_pending_rollback(self, db_session, sample_task_run):
        """OCC 冲突时最多重试 3 次，第 3 次失败抛 state_write_conflict"""
        svc = TaskRunService(db_session)
        call_count = 0

        original_commit = db_session.commit

        def flaky_commit():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise PendingRollbackError()
            return original_commit()

        with patch.object(db_session, 'commit', side_effect=flaky_commit):
            with pytest.raises(TRError) as exc_info:
                svc.transition(sample_task_run.id, SvcTaskRunStatus.RUNNING)
        assert exc_info.value.code == "state_write_conflict"
        assert call_count == 3

    def test_transition_occ_retry_success_on_second_attempt(self, db_session, sample_task_run):
        """OCC 冲突第 2 次成功后正常返回"""
        call_count = 0
        original_commit = db_session.commit

        def flaky_commit():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PendingRollbackError()
            return original_commit()

        with patch.object(db_session, 'commit', side_effect=flaky_commit):
            run = svc.transition(sample_task_run.id, SvcTaskRunStatus.RUNNING)

        assert run.status == SvcTaskRunStatus.RUNNING
        assert call_count == 2


class TestTaskRunServiceShortcutMethods:
    """TaskRunService 快捷方法"""

    def test_to_running(self, db_session, sample_task_run):
        svc = TaskRunService(db_session)
        run = svc.to_running(sample_task_run.id)
        assert run.status == SvcTaskRunStatus.RUNNING

    def test_to_succeeded(self, db_session, sample_task_run):
        svc = TaskRunService(db_session)
        svc.to_running(sample_task_run.id)
        run = svc.to_succeeded(sample_task_run.id, output_payload={"out": 42})
        assert run.status == SvcTaskRunStatus.SUCCEEDED
        assert run.output_payload == {"out": 42}

    def test_to_failed_sets_error(self, db_session, sample_task_run):
        svc = TaskRunService(db_session)
        svc.to_running(sample_task_run.id)
        run = svc.to_failed(sample_task_run.id, "ERR_001", "something went wrong")
        assert run.status == SvcTaskRunStatus.FAILED
        assert run.error_code == "ERR_001"
        assert run.error_message == "something went wrong"

    def test_to_cancelling_and_to_cancelled(self, db_session, sample_task_run):
        svc = TaskRunService(db_session)
        svc.to_running(sample_task_run.id)
        svc.to_cancelling(sample_task_run.id)
        run = svc.to_cancelled(sample_task_run.id)
        assert run.status == SvcTaskRunStatus.CANCELLED


class TestTaskRunServiceCancel:
    """cancel() 幂等性 + 状态分支"""

    def test_cancel_terminal_state_idempotent(self, db_session, sample_task_run):
        svc = TaskRunService(db_session)
        svc.to_running(sample_task_run.id)
        svc.to_succeeded(sample_task_run.id)

        run, was_cancelled = svc.cancel(sample_task_run.id)
        assert run.status == SvcTaskRunStatus.SUCCEEDED  # 保持不变
        assert was_cancelled is False

    def test_cancel_queued_directly_cancelled(self, db_session, sample_task_run):
        svc = TaskRunService(db_session)
        run, was_cancelled = svc.cancel(sample_task_run.id)
        assert run.status == SvcTaskRunStatus.CANCELLED
        assert was_cancelled is True

    def test_cancel_running_goes_to_cancelling(self, db_session, sample_task_run):
        svc = TaskRunService(db_session)
        svc.to_running(sample_task_run.id)
        run, was_cancelled = svc.cancel(sample_task_run.id)
        assert run.status == SvcTaskRunStatus.CANCELLING
        assert was_cancelled is True


class TestTaskRunServiceGetters:
    """get_run / get_run_or_raise"""

    def test_get_run_returns_run(self, db_session, sample_task_run):
        svc = TaskRunService(db_session)
        run = svc.get_run(sample_task_run.id)
        assert run is not None
        assert run.id == sample_task_run.id

    def test_get_run_returns_none_for_missing(self, db_session):
        svc = TaskRunService(db_session)
        assert svc.get_run(99999) is None

    def test_get_run_or_raise_404(self, db_session):
        svc = TaskRunService(db_session)
        with pytest.raises(TRError) as exc_info:
            svc.get_run_or_raise(99999)
        assert exc_info.value.code == "task_run_not_found"


# =============================================================================
# service — module-level helpers
# =============================================================================

class TestServiceHelpers:
    """can_transition / is_terminal / VALID_TRANSITIONS"""

    def test_can_transition_valid(self):
        assert can_transition("queued", "running") is True
        assert can_transition("running", "succeeded") is True
        assert can_transition("running", "cancelling") is True
        assert can_transition("cancelling", "cancelled") is True

    def test_can_transition_invalid(self):
        assert can_transition("queued", "succeeded") is False
        assert can_transition("succeeded", "running") is False
        assert can_transition("failed", "cancelled") is False

    def test_is_terminal(self):
        assert is_terminal("succeeded") is True
        assert is_terminal("failed") is True
        assert is_terminal("cancelled") is True
        assert is_terminal("running") is False
        assert is_terminal("queued") is False


# =============================================================================
# event_bus — 事件发射（需要 DB）
# =============================================================================

class TestEmitEvent:
    """emit_event 基础逻辑 + 8KB 截断"""

    def test_emit_event_writes_row(self, db_session, sample_task_run):
        event = emit_event(
            db_session,
            task_run_id=sample_task_run.id,
            event_type=TaskEventType.TASK_QUEUED,
            payload={"trace_id": "trace-001"},
        )
        db_session.flush()
        assert event.id is not None
        assert event.task_run_id == sample_task_run.id
        assert event.event_type == TaskEventType.TASK_QUEUED

    def test_emit_event_truncates_large_payload(self, db_session, sample_task_run):
        large_payload = {"data": "x" * 20_000}  # > 8KB
        event = emit_event(
            db_session,
            task_run_id=sample_task_run.id,
            event_type=TaskEventType.TASK_COMPLETED,
            payload=large_payload,
        )
        db_session.flush()
        # 应该被截断为 {"_truncated": True, "ref": ...}
        assert event.payload.get("_truncated") is True


class TestEmitTaskEvents:
    """emit_task_* 事件 payload 结构"""

    def test_emit_task_queued_payload(self, db_session, sample_task_run):
        event = emit_task_queued(
            db_session,
            task_run_id=sample_task_run.id,
            trace_id="trace-001",
            intent="nlq_query",
            user_id=1,
        )
        db_session.flush()
        p = event.payload
        assert p["run_id"] == sample_task_run.id
        assert p["trace_id"] == "trace-001"
        assert p["intent"] == "nlq_query"
        assert p["user_id"] == 1

    def test_emit_task_started_payload(self, db_session, sample_task_run):
        now = datetime.now(timezone.utc)
        event = emit_task_started(db_session, sample_task_run.id, now)
        db_session.flush()
        assert event.event_type == TaskEventType.TASK_STARTED
        assert event.payload["run_id"] == sample_task_run.id

    def test_emit_task_completed_payload(self, db_session, sample_task_run):
        event = emit_task_completed(db_session, sample_task_run.id, output_ref="obj://out", latency_ms=1500)
        db_session.flush()
        p = event.payload
        assert p["run_id"] == sample_task_run.id
        assert p["output_ref"] == "obj://out"
        assert p["latency_ms"] == 1500

    def test_emit_task_failed_payload(self, db_session, sample_task_run):
        event = emit_task_failed(db_session, sample_task_run.id, "ERR_001", "timeout")
        db_session.flush()
        p = event.payload
        assert p["error_code"] == "ERR_001"
        assert p["error_message"] == "timeout"

    def test_emit_task_cancelled_payload(self, db_session, sample_task_run):
        now = datetime.now(timezone.utc)
        event = emit_task_cancelled(db_session, sample_task_run.id, now)
        db_session.flush()
        assert event.event_type == TaskEventType.TASK_CANCELLED


class TestEmitStepEvents:
    """emit_step_* 事件 payload 结构"""

    def test_emit_step_started_payload(self, db_session, sample_task_run):
        event = emit_step_started(
            db_session, sample_task_run.id,
            step_id=1, seq=0, step_type="route", capability_name="tableau_mcp"
        )
        db_session.flush()
        p = event.payload
        assert p["step_id"] == 1
        assert p["seq"] == 0
        assert p["step_type"] == "route"
        assert p["capability_name"] == "tableau_mcp"

    def test_emit_step_completed_payload(self, db_session, sample_task_run):
        event = emit_step_completed(db_session, sample_task_run.id, step_id=1, latency_ms=320)
        db_session.flush()
        assert event.payload["latency_ms"] == 320

    def test_emit_step_failed_payload(self, db_session, sample_task_run):
        event = emit_step_failed(db_session, sample_task_run.id, step_id=1, error_code="STEP_ERR")
        db_session.flush()
        assert event.payload["error_code"] == "STEP_ERR"


# =============================================================================
# validators — 创建校验（需要 DB + user）
# =============================================================================

class TestTaskRunValidatorCreate:
    """validate_create 校验"""

    def test_validate_create_valid(self, db_session, mock_user):
        validator = TaskRunValidator(db_session, mock_user)
        # 不抛异常即通过
        validator.validate_create(intent="nlq_query", timeout_seconds=120, conversation_id=None)

    def test_validate_create_invalid_intent(self, db_session, mock_user):
        validator = TaskRunValidator(db_session, mock_user)
        with pytest.raises(TRError) as exc_info:
            validator.validate_create(intent="invalid_intent_xyz", timeout_seconds=120, conversation_id=None)
        assert exc_info.value.code == "invalid_intent"

    def test_validate_create_timeout_too_low(self, db_session, mock_user):
        validator = TaskRunValidator(db_session, mock_user)
        with pytest.raises(TRError) as exc_info:
            validator.validate_create(intent="nlq_query", timeout_seconds=4, conversation_id=None)
        assert exc_info.value.code == "timeout_out_of_range"

    def test_validate_create_timeout_too_high(self, db_session, mock_user):
        validator = TaskRunValidator(db_session, mock_user)
        with pytest.raises(TRError) as exc_info:
            validator.validate_create(intent="nlq_query", timeout_seconds=601, conversation_id=None)
        assert exc_info.value.code == "timeout_out_of_range"

    def test_validate_create_agent_chat_requires_conversation_id(self, db_session, mock_user):
        validator = TaskRunValidator(db_session, mock_user)
        with pytest.raises(TRError) as exc_info:
            validator.validate_create(intent="agent_chat", timeout_seconds=120, conversation_id=None)
        assert exc_info.value.code == "conversation_not_owned"

    def test_validate_create_concurrent_limit(self, db_session, mock_user):
        """running >= 5 时拒绝新创建"""
        validator = TaskRunValidator(db_session, mock_user)
        # 创建 5 个 running TaskRun
        for i in range(5):
            run = BiTaskRun(
                trace_id=f"trace-concurrent-{i}",
                user_id=mock_user["id"],
                intent="nlq_query",
                status="running",
                input_payload={},
                timeout_seconds=120,
            )
            db_session.add(run)
        db_session.flush()

        with pytest.raises(TRError) as exc_info:
            validator.validate_create(intent="nlq_query", timeout_seconds=120, conversation_id=None)
        assert exc_info.value.code == "concurrent_limit_exceeded"


class TestTaskRunValidatorRBAC:
    """validate_rbac RBAC 权限校验"""

    def test_validate_rbac_regular_user_blocked_for_bulk_action(self, db_session, mock_user):
        validator = TaskRunValidator(db_session, mock_user)
        with pytest.raises(AuthError) as exc_info:
            validator.validate_rbac("bulk_action")
        assert exc_info.value.code == "insufficient_permissions"

    def test_validate_rbac_regular_user_blocked_for_health_scan(self, db_session, mock_user):
        validator = TaskRunValidator(db_session, mock_user)
        with pytest.raises(AuthError) as exc_info:
            validator.validate_rbac("health_scan")
        assert exc_info.value.code == "insufficient_permissions"

    def test_validate_rbac_admin_allowed_bulk_action(self, db_session, mock_admin_user):
        validator = TaskRunValidator(db_session, mock_admin_user)
        validator.validate_rbac("bulk_action")  # 不抛异常

    def test_validate_rbac_data_admin_allowed_health_scan(self, db_session):
        admin_user = {"id": 2, "role": "data_admin"}
        validator = TaskRunValidator(db_session, admin_user)
        validator.validate_rbac("health_scan")  # 不抛异常


class TestGetAllowedIntents:
    """get_allowed_intents 白名单加载"""

    def test_returns_list(self):
        intents = get_allowed_intents()
        assert isinstance(intents, list)

    def test_known_intents_in_whitelist(self):
        intents = get_allowed_intents()
        # 至少包含核心 intent
        assert "nlq_query" in intents or "agent_chat" in intents
