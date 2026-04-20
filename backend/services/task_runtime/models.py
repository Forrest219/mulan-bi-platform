"""Task Runtime - data models（Spec 24 P0）"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class InvalidStateTransitionError(Exception):
    """非法的 TaskRun 状态流转时抛出"""
    pass


class TaskRunStatus(str, Enum):
    """TaskRun 状态枚举

    合法流转：
    - PENDING → RUNNING
    - PENDING → CANCELLED
    - RUNNING → SUCCEEDED
    - RUNNING → FAILED
    - RUNNING → CANCELLED
    """
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStepRunStatus(str, Enum):
    """TaskStepRun 状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepType(str, Enum):
    """TaskStep 类型"""
    ROUTE = "route"        # 路由决策（选择数据源/连接）
    GENERATE = "generate"  # NLQ 生成（调用 LLM 生成 VizQL）
    EXECUTE = "execute"    # 执行查询（调用 MCP 执行）
    FORMAT = "format"      # 结果格式化


@dataclass
class TaskStepRun:
    """TaskStepRun 数据类

    Attributes:
        id: Step 唯一 ID
        task_run_id: 所属 TaskRun ID
        step_order: 执行顺序（0-based）
        step_type: Step 类型（route/generate/execute/format）
        status: 当前状态
        result: 执行结果（可选，JSON 序列化存储）
        error: 错误信息（可选）
        started_at: 开始时间
        finished_at: 结束时间（可选）
    """
    id: str
    task_run_id: str
    step_order: int
    step_type: StepType
    status: TaskStepRunStatus = TaskStepRunStatus.PENDING
    result: Optional[dict] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


@dataclass
class TaskRun:
    """TaskRun 数据类

    Attributes:
        id: TaskRun 唯一 ID（UUID）
        trace_id: 全链路追踪 ID
        status: 当前状态
        created_at: 创建时间
        updated_at: 最后更新时间
        steps: Step 列表
        result: 最终结果（可选）
        error: 错误信息（可选）
        task_run_id: 兼容字段（alias to id）
    """
    id: str
    trace_id: str
    status: TaskRunStatus = TaskRunStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    steps: list[TaskStepRun] = field(default_factory=list)
    result: Optional[dict] = None
    error: Optional[str] = None

    @property
    def task_run_id(self) -> str:
        """兼容字段：task_run_id alias to id"""
        return self.id
