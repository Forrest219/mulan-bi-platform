"""Task Runtime - State Machine Service（Spec 24 §4.1）

状态写入唯一入口：
  task_runtime.service.TaskRunService.transition(run_id, target, *, expected_from=None)

禁止业务代码直接 UPDATE bi_taskrun_runs SET status=...
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError, PendingRollbackError

from app.core.errors import TRError
from services.task_runtime.models_db import BiTaskRun

logger = logging.getLogger(__name__)


# 状态枚举
class TaskRunStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"

    ALL = ("queued", "running", "succeeded", "failed", "cancelling", "cancelled")
    TERMINAL = ("succeeded", "failed", "cancelled")


# 合法转移表（Spec 24 §4.1 mermaid）
# 使用字符串直接量，避免类属性引用顺序问题
VALID_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "failed"},
    "running": {"succeeded", "failed", "cancelling"},
    "cancelling": {"cancelled", "failed"},
    # 终态：无合法转移
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}


def is_terminal(status: str) -> bool:
    """判断是否为终态"""
    return status in TaskRunStatus.TERMINAL


def can_transition(from_status: str, to_status: str) -> bool:
    """判断是否可流转（不抛异常）"""
    allowed = VALID_TRANSITIONS.get(from_status, set())
    return to_status in allowed


class TaskRunService:
    """TaskRun 状态机服务"""

    MAX_RETRIES = 3

    def __init__(self, db: Session):
        self.db = db

    def get_run(self, run_id: int) -> Optional[BiTaskRun]:
        """获取 TaskRun"""
        return self.db.query(BiTaskRun).filter(BiTaskRun.id == run_id).first()

    def get_run_or_raise(self, run_id: int, user_id: Optional[int] = None) -> BiTaskRun:
        """获取 TaskRun，不存在则抛出 TR_004"""
        run = self.get_run(run_id)
        if not run:
            raise TRError.task_run_not_found()
        # 非终态的 TaskRun 只允许创建者或 admin 查看
        if user_id and run.user_id != user_id and run.status not in TaskRunStatus.TERMINAL:
            # For now we allow query, but the API layer enforces admin-only for non-owner queries
            pass
        return run

    def transition(
        self,
        run_id: int,
        target: str,
        *,
        expected_from: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        output_payload: Optional[dict] = None,
        output_ref: Optional[str] = None,
    ) -> BiTaskRun:
        """状态流转校验与执行（带 OCC 重试）

        Args:
            run_id: TaskRun ID
            target: 目标状态
            expected_from: 期望的当前状态（用于乐观锁校验）
            error_code: 终态失败时的错误码
            error_message: 终态失败时的错误信息
            output_payload: 终态成功时的输出
            output_ref: 终态成功时的输出引用

        Returns:
            更新后的 BiTaskRun

        Raises:
            TRError.task_run_not_found: TaskRun 不存在
            TRError.invalid_state_transition: 目标状态非法
            TRError.state_write_conflict: OCC 重试耗尽
        """
        for attempt in range(self.MAX_RETRIES):
            run = self.get_run(run_id)
            if not run:
                raise TRError.task_run_not_found()

            current = run.status

            # 校验 expected_from（如果提供）
            if expected_from is not None and current != expected_from:
                raise TRError.invalid_state_transition()

            # 校验状态转移合法性
            if not can_transition(current, target):
                raise TRError.illegal_state_transition(
                    detail={
                        "current": current,
                        "target": target,
                        "allowed": list(VALID_TRANSITIONS.get(current, set())),
                    }
                )

            # 更新字段
            now = datetime.now(timezone.utc)
            run.status = target
            run.updated_at = now

            if target in TaskRunStatus.TERMINAL:
                run.finished_at = now

            if error_code:
                run.error_code = error_code
            if error_message:
                run.error_message = error_message
            if output_payload:
                run.output_payload = output_payload
            if output_ref:
                run.output_payload = {"ref": output_ref}

            try:
                self.db.flush()
                # 尝试提交事务
                self.db.commit()
                logger.info("TaskRun %d transitioned: %s → %s", run_id, current, target)
                return run
            except (PendingRollbackError, OperationalError):
                self.db.rollback()
                logger.warning(
                    "TaskRun %d transition conflicted (attempt %d/%d): %s → %s",
                    run_id, attempt + 1, self.MAX_RETRIES, current, target
                )
                if attempt == self.MAX_RETRIES - 1:
                    raise TRError.state_write_conflict()

    def to_running(self, run_id: int) -> BiTaskRun:
        """queued → running"""
        return self.transition(run_id, TaskRunStatus.RUNNING, expected_from=TaskRunStatus.QUEUED)

    def to_succeeded(self, run_id: int, output_payload: Optional[dict] = None, output_ref: Optional[str] = None) -> BiTaskRun:
        """running → succeeded"""
        return self.transition(
            run_id, TaskRunStatus.SUCCEEDED,
            expected_from=TaskRunStatus.RUNNING,
            output_payload=output_payload,
            output_ref=output_ref,
        )

    def to_failed(self, run_id: int, error_code: str, error_message: str) -> BiTaskRun:
        """→ failed"""
        return self.transition(
            run_id, TaskRunStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
        )

    def to_cancelling(self, run_id: int) -> BiTaskRun:
        """running → cancelling"""
        return self.transition(run_id, TaskRunStatus.CANCELLING, expected_from=TaskRunStatus.RUNNING)

    def to_cancelled(self, run_id: int) -> BiTaskRun:
        """cancelling → cancelled"""
        return self.transition(run_id, TaskRunStatus.CANCELLED, expected_from=TaskRunStatus.CANCELLING)

    def cancel(self, run_id: int) -> Tuple[BiTaskRun, bool]:
        """取消 TaskRun

        Returns:
            (run, was_cancelled): run 为最新状态，was_cancelled=True 表示成功取消
        """
        run = self.get_run(run_id)
        if not run:
            raise TRError.task_run_not_found()

        if is_terminal(run.status):
            # 幂等：终态返回当前状态，不报错
            return run, False

        if run.status == TaskRunStatus.QUEUED:
            # queued 直接取消
            run = self.transition(run_id, TaskRunStatus.CANCELLED)
            return run, True
        elif run.status == TaskRunStatus.RUNNING:
            # running → cancelling
            run = self.to_cancelling(run_id)
            return run, True
        else:
            raise TRError.invalid_state_transition()
