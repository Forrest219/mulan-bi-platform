"""
Mulan BI Platform — Task Runtime 错误码（Spec 24 §5）
TR_001~TR_010

错误码统一在 app/errors/error_codes.py 注册（与 SPEC 01 错误码规范一致）。
"""
from app.core.errors import MulanError


class TRError:
    """Task Runtime 错误码"""

    @staticmethod
    def invalid_intent():
        """TR_001: intent 不在白名单"""
        return MulanError("TR_001", "intent 不在白名单中", 400)

    @staticmethod
    def timeout_out_of_range():
        """TR_002: timeout 超出范围 [5, 600]"""
        return MulanError("TR_002", "timeout_seconds 超出允许范围 [5, 600]", 400)

    @staticmethod
    def conversation_not_owned():
        """TR_003: conversation_id 不属于当前用户"""
        return MulanError("TR_003", "conversation_id 不属于当前用户", 403)

    @staticmethod
    def task_run_not_found():
        """TR_004: TaskRun 不存在或无权访问"""
        return MulanError("TR_004", "TaskRun 不存在或无权访问", 404)

    @staticmethod
    def invalid_state_transition():
        """TR_005: 当前状态不允许该操作（如取消已完成）"""
        return MulanError("TR_005", "当前状态不允许该操作", 409)

    @staticmethod
    def task_timeout():
        """TR_006: TaskRun 总超时"""
        return MulanError("TR_006", "TaskRun 总超时", 504)

    @staticmethod
    def illegal_state_transition(detail: dict = None):
        """TR_007: 非法状态转移（内部 bug）"""
        return MulanError("TR_007", "非法状态转移", 500, detail)

    @staticmethod
    def concurrent_limit_exceeded():
        """TR_008: 并发上限，用户 5 个 running TaskRun"""
        return MulanError("TR_008", "并发运行任务数超限（最多 5 个）", 429)

    @staticmethod
    def capability_invocation_failed(detail: dict = None):
        """TR_009: 下游 capability 调用失败"""
        return MulanError("TR_009", "下游 capability 调用失败", 502, detail)

    @staticmethod
    def state_write_conflict():
        """TR_010: 状态写入冲突，OCC 重试耗尽"""
        return MulanError("TR_010", "状态写入冲突，请重试", 500)
