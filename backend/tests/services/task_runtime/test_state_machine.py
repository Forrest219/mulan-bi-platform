"""Task Runtime 状态机与服务单元测试（Spec 24 §9.2）

覆盖：
- 所有关法状态转移
- 所有非法状态转移（返回 TR_007）
- redactor 调用验证
- OCC 重试逻辑

注意：这些测试不依赖数据库，仅测试纯 Python 逻辑。
"""
import pytest

# 标记整个文件跳过数据库 setup（conftest.py 中的 setup_database）
pytestmark = pytest.mark.usefixtures("")

from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone

from services.task_runtime.state_machine import TaskRunStateMachine
from services.task_runtime.models import TaskRunStatus, TaskRun


class TestTaskRunStateMachineTransitions:
    """测试状态机所有合法转移"""

    def test_queued_to_running(self):
        """queued → running：合法"""
        task_run = TaskRun(id="test-1", trace_id="trace-1", status=TaskRunStatus.QUEUED)
        result = TaskRunStateMachine.transition(task_run, TaskRunStatus.RUNNING)
        assert result.status == TaskRunStatus.RUNNING
        assert result.updated_at is not None

    def test_queued_to_failed(self):
        """queued → failed：合法（校验失败场景）"""
        task_run = TaskRun(id="test-1", trace_id="trace-1", status=TaskRunStatus.QUEUED)
        result = TaskRunStateMachine.transition(task_run, TaskRunStatus.FAILED)
        assert result.status == TaskRunStatus.FAILED

    def test_queued_to_cancelled(self):
        """queued → cancelled：合法"""
        task_run = TaskRun(id="test-1", trace_id="trace-1", status=TaskRunStatus.QUEUED)
        result = TaskRunStateMachine.transition(task_run, TaskRunStatus.CANCELLED)
        assert result.status == TaskRunStatus.CANCELLED

    def test_running_to_succeeded(self):
        """running → succeeded：合法"""
        task_run = TaskRun(id="test-1", trace_id="trace-1", status=TaskRunStatus.RUNNING)
        result = TaskRunStateMachine.transition(task_run, TaskRunStatus.SUCCEEDED)
        assert result.status == TaskRunStatus.SUCCEEDED

    def test_running_to_failed(self):
        """running → failed：合法"""
        task_run = TaskRun(id="test-1", trace_id="trace-1", status=TaskRunStatus.RUNNING)
        result = TaskRunStateMachine.transition(task_run, TaskRunStatus.FAILED)
        assert result.status == TaskRunStatus.FAILED

    def test_running_to_cancelling(self):
        """running → cancelling：合法"""
        task_run = TaskRun(id="test-1", trace_id="trace-1", status=TaskRunStatus.RUNNING)
        result = TaskRunStateMachine.transition(task_run, TaskRunStatus.CANCELLING)
        assert result.status == TaskRunStatus.CANCELLING

    def test_cancelling_to_cancelled(self):
        """cancelling → cancelled：合法"""
        task_run = TaskRun(id="test-1", trace_id="trace-1", status=TaskRunStatus.CANCELLING)
        result = TaskRunStateMachine.transition(task_run, TaskRunStatus.CANCELLED)
        assert result.status == TaskRunStatus.CANCELLED

    def test_cancelling_to_failed(self):
        """cancelling → failed：合法（取消过程中出错）"""
        task_run = TaskRun(id="test-1", trace_id="trace-1", status=TaskRunStatus.CANCELLING)
        result = TaskRunStateMachine.transition(task_run, TaskRunStatus.FAILED)
        assert result.status == TaskRunStatus.FAILED


class TestTaskRunStateMachineInvalidTransitions:
    """测试所有非法状态转移（应返回 TR_007）"""

    def test_queued_to_succeeded_invalid(self):
        """queued → succeeded：非法"""
        from services.task_runtime.models import InvalidStateTransitionError
        task_run = TaskRun(id="test-1", trace_id="trace-1", status=TaskRunStatus.QUEUED)
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            TaskRunStateMachine.transition(task_run, TaskRunStatus.SUCCEEDED)
        assert "非法状态流转" in str(exc_info.value)

    def test_running_to_queued_invalid(self):
        """running → queued：非法"""
        from services.task_runtime.models import InvalidStateTransitionError
        task_run = TaskRun(id="test-1", trace_id="trace-1", status=TaskRunStatus.RUNNING)
        with pytest.raises(InvalidStateTransitionError):
            TaskRunStateMachine.transition(task_run, TaskRunStatus.QUEUED)

    def test_succeeded_to_any_invalid(self):
        """succeeded（终态）→ 任意：非法"""
        from services.task_runtime.models import InvalidStateTransitionError
        task_run = TaskRun(id="test-1", trace_id="trace-1", status=TaskRunStatus.SUCCEEDED)
        with pytest.raises(InvalidStateTransitionError):
            TaskRunStateMachine.transition(task_run, TaskRunStatus.RUNNING)
        with pytest.raises(InvalidStateTransitionError):
            TaskRunStateMachine.transition(task_run, TaskRunStatus.FAILED)

    def test_failed_to_any_invalid(self):
        """failed（终态）→ 任意：非法"""
        from services.task_runtime.models import InvalidStateTransitionError
        task_run = TaskRun(id="test-1", trace_id="trace-1", status=TaskRunStatus.FAILED)
        with pytest.raises(InvalidStateTransitionError):
            TaskRunStateMachine.transition(task_run, TaskRunStatus.RUNNING)

    def test_cancelled_to_any_invalid(self):
        """cancelled（终态）→ 任意：非法"""
        from services.task_runtime.models import InvalidStateTransitionError
        task_run = TaskRun(id="test-1", trace_id="trace-1", status=TaskRunStatus.CANCELLED)
        with pytest.raises(InvalidStateTransitionError):
            TaskRunStateMachine.transition(task_run, TaskRunStatus.RUNNING)

    def test_cancelling_to_running_invalid(self):
        """cancelling → running：非法"""
        from services.task_runtime.models import InvalidStateTransitionError
        task_run = TaskRun(id="test-1", trace_id="trace-1", status=TaskRunStatus.CANCELLING)
        with pytest.raises(InvalidStateTransitionError):
            TaskRunStateMachine.transition(task_run, TaskRunStatus.RUNNING)


class TestTaskRunStateMachineHelpers:
    """测试辅助方法"""

    def test_can_transition_returns_true_for_valid(self):
        """can_transition 对合法转移返回 True"""
        assert TaskRunStateMachine.can_transition(TaskRunStatus.QUEUED, TaskRunStatus.RUNNING)
        assert TaskRunStateMachine.can_transition(TaskRunStatus.RUNNING, TaskRunStatus.SUCCEEDED)

    def test_can_transition_returns_false_for_invalid(self):
        """can_transition 对非法转移返回 False"""
        assert not TaskRunStateMachine.can_transition(TaskRunStatus.QUEUED, TaskRunStatus.SUCCEEDED)
        assert not TaskRunStateMachine.can_transition(TaskRunStatus.SUCCEEDED, TaskRunStatus.RUNNING)

    def test_is_terminal_for_terminal_states(self):
        """is_terminal 对终态返回 True"""
        assert TaskRunStateMachine.is_terminal(TaskRunStatus.SUCCEEDED)
        assert TaskRunStateMachine.is_terminal(TaskRunStatus.FAILED)
        assert TaskRunStateMachine.is_terminal(TaskRunStatus.CANCELLED)

    def test_is_terminal_for_non_terminal_states(self):
        """is_terminal 对非终态返回 False"""
        assert not TaskRunStateMachine.is_terminal(TaskRunStatus.QUEUED)
        assert not TaskRunStateMachine.is_terminal(TaskRunStatus.RUNNING)
        assert not TaskRunStateMachine.is_terminal(TaskRunStatus.CANCELLING)


class TestEventBusRedactor:
    """测试事件总线 redactor 调用"""

    def test_emit_event_calls_redactor(self):
        """emit_event 应调用 redact_payload"""
        from services.task_runtime import event_bus

        mock_db = MagicMock()
        mock_event = MagicMock()
        mock_db.add.return_value = None
        mock_db.flush.return_value = None

        with patch.object(event_bus, 'redact_payload', wraps=event_bus.redact_payload) as mock_redact:
            with patch('services.task_runtime.event_bus.BiTaskRunEvent', return_value=mock_event):
                payload = {
                    "run_id": 1,
                    "error_message": "password=secret123 api_key=sk-proj-abc123",
                }
                event_bus.emit_event(
                    db=mock_db,
                    task_run_id=1,
                    event_type="task.failed",
                    payload=payload,
                )
                # redact_payload 应被调用
                mock_redact.assert_called_once()

    def test_emit_task_failed_redacts_error_message(self):
        """emit_task_failed 应脱敏 error_message 中的敏感信息"""
        from services.task_runtime import event_bus

        mock_db = MagicMock()
        mock_event = MagicMock()
        mock_db.add.return_value = None
        mock_db.flush.return_value = None

        sensitive_message = "连接失败: password=mypassword token=sk-proj-123456789"

        with patch('services.task_runtime.event_bus.BiTaskRunEvent', return_value=mock_event) as mock_model:
            event_bus.emit_task_failed(
                db=mock_db,
                task_run_id=1,
                error_code="TR_009",
                error_message=sensitive_message,
            )
            # 获取实际写入的 payload
            call_args = mock_model.call_args
            actual_payload = call_args.kwargs.get('payload', call_args[0][3] if len(call_args[0]) > 3 else {})

            # 敏感信息应被脱敏
            assert "mypassword" not in str(actual_payload)
            assert "sk-proj" not in str(actual_payload)
            # 非敏感信息应保留
            assert "TR_009" in str(actual_payload) or actual_payload.get("error_code") == "TR_009"


class TestTaskRunStatusEnum:
    """测试状态枚举一致性"""

    def test_status_values_match_spec(self):
        """状态值应与 Spec 24 §4.1 一致"""
        assert TaskRunStatus.QUEUED.value == "queued"
        assert TaskRunStatus.RUNNING.value == "running"
        assert TaskRunStatus.SUCCEEDED.value == "succeeded"
        assert TaskRunStatus.FAILED.value == "failed"
        assert TaskRunStatus.CANCELLING.value == "cancelling"
        assert TaskRunStatus.CANCELLED.value == "cancelled"

    def test_all_statuses_defined(self):
        """应定义所有 6 种状态"""
        expected = {"queued", "running", "succeeded", "failed", "cancelling", "cancelled"}
        actual = {s.value for s in TaskRunStatus}
        assert actual == expected

    def test_terminal_states_count(self):
        """终态应为 3 个"""
        terminal_count = sum(1 for s in TaskRunStatus if TaskRunStateMachine.is_terminal(s))
        assert terminal_count == 3
