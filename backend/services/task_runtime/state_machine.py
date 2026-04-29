"""Task Runtime - state machine（Spec 24 P0）"""
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .models import TaskRunStatus, TaskRun, InvalidStateTransitionError


class TaskRunStateMachine:
    """TaskRun 状态机

    合法流转规则（Spec 24 §4.1）：
    - queued → running（启动执行）
    - queued → failed（校验失败）
    - running → succeeded（成功完成）
    - running → failed（执行失败）
    - running → cancelling（取消中）
    - cancelling → cancelled（取消完成）
    - cancelling → failed（取消失败）

    终态：succeeded, failed, cancelled（无后续转移）
    """

    VALID_TRANSITIONS: dict[TaskRunStatus, set[TaskRunStatus]] = {
        TaskRunStatus.QUEUED: {
            TaskRunStatus.RUNNING,
            TaskRunStatus.FAILED,
            TaskRunStatus.CANCELLED,
        },
        TaskRunStatus.RUNNING: {
            TaskRunStatus.SUCCEEDED,
            TaskRunStatus.FAILED,
            TaskRunStatus.CANCELLING,
        },
        TaskRunStatus.CANCELLING: {
            TaskRunStatus.CANCELLED,
            TaskRunStatus.FAILED,
        },
        # terminal states: no further transitions allowed
        TaskRunStatus.SUCCEEDED: set(),
        TaskRunStatus.FAILED: set(),
        TaskRunStatus.CANCELLED: set(),
    }

    @classmethod
    def transition(cls, task_run: TaskRun, new_status: TaskRunStatus) -> TaskRun:
        """状态流转校验与执行。

        Args:
            task_run: 当前 TaskRun 实例
            new_status: 目标状态

        Returns:
            更新后的 TaskRun（with updated_at）

        Raises:
            InvalidStateTransitionError: 当流转不合法时
        """
        current = task_run.status
        allowed = cls.VALID_TRANSITIONS.get(current, set())

        if new_status not in allowed:
            raise InvalidStateTransitionError(
                f"非法状态流转：{current.value} → {new_status.value}。"
                f"允许的目标状态：{[s.value for s in allowed] if allowed else '无（终态）'}"
            )

        # Update status and timestamp
        task_run.status = new_status
        task_run.updated_at = datetime.now(timezone.utc)
        return task_run

    @classmethod
    def can_transition(cls, current: TaskRunStatus, target: TaskRunStatus) -> bool:
        """判断是否可流转（不抛异常）"""
        return target in cls.VALID_TRANSITIONS.get(current, set())

    @classmethod
    def is_terminal(cls, status: TaskRunStatus) -> bool:
        """判断是否为终态"""
        return len(cls.VALID_TRANSITIONS.get(status, set())) == 0
