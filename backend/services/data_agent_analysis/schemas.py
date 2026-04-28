"""
Data Agent Analysis Pydantic Schemas — API 请求/响应模型

Spec 28 §8 — API 设计
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================================
# 会话管理
# ============================================================================


class CreateAnalysisSessionRequest(BaseModel):
    """创建分析会话请求"""

    task_type: str = Field(..., description="任务类型：causation / report / insight")
    subject: Optional[str] = Field(None, description="分析主题")
    params: Optional[Dict[str, Any]] = Field(None, description="任务参数")
    metadata: Optional[Dict[str, Any]] = Field(None, description="任务元数据（不含 user_id）")


class AnalysisSessionResponse(BaseModel):
    """分析会话响应"""

    id: str
    agent_type: str
    task_type: str
    status: str
    current_step: int
    created_at: str
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None
    expired_at: Optional[str] = None

    class Config:
        from_attributes = True


class CausationRequest(BaseModel):
    """快捷归因分析请求"""

    metric: str = Field(..., description="指标名")
    dimensions: List[str] = Field(default_factory=list, description="候选维度列表")
    time_range: Dict[str, str] = Field(..., description="时间范围")
    threshold: float = Field(0.1, description="异动阈值")


class CausationResponse(BaseModel):
    """快捷归因分析响应"""

    session_id: str
    message: str = "归因分析已启动"


class SessionProgressResponse(BaseModel):
    """会话进度响应"""

    session_id: str
    status: str
    current_step: int
    total_steps: int
    step_summaries: List[Dict[str, Any]]
    hypothesis_tree: Optional[Dict[str, Any]] = None


# ============================================================================
# 洞察管理
# ============================================================================


class InsightPublishRequest(BaseModel):
    """洞察发布请求"""

    session_id: Optional[str] = Field(None, description="关联会话 ID")
    insight_type: str = Field(..., description="洞察类型：anomaly / trend / correlation / causation")
    title: str = Field(..., description="标题")
    summary: str = Field(..., description="一句话总结")
    detail_json: Dict[str, Any] = Field(..., description="完整洞察详情")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度 0-1")
    datasource_ids: List[int] = Field(default_factory=list, description="涉及的数据源 ID")
    visibility: str = Field("private", description="可见性：private / team / public")
    push_targets: Optional[List[str]] = Field(None, description="推送渠道")
    allowed_roles: Optional[List[str]] = Field(None, description="允许查看的角色")
    metric_names: Optional[List[str]] = Field(None, description="涉及的指标名")
    impact_scope: Optional[str] = Field(None, description="影响范围描述")


class InsightResponse(BaseModel):
    """洞察响应"""

    id: str
    insight_type: str
    title: str
    summary: str
    confidence: float
    status: str
    visibility: str
    datasource_ids: List[int]
    published_at: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


# ============================================================================
# 报告管理
# ============================================================================


class ReportCreateRequest(BaseModel):
    """报告创建请求"""

    session_id: Optional[str] = Field(None, description="关联会话 ID")
    subject: str = Field(..., description="报告主题")
    time_range: Optional[str] = Field(None, description="分析时间范围")
    include_sections: Optional[List[str]] = Field(None, description="包含的章节类型")
    output_format: List[str] = Field(default_factory=lambda: ["json", "markdown"], description="输出格式")
    datasource_ids: List[int] = Field(default_factory=list, description="涉及的数据源 ID")
    visibility: str = Field("private", description="可见性")
    allowed_roles: Optional[List[str]] = Field(None, description="允许查看的角色")


class ReportResponse(BaseModel):
    """报告响应"""

    id: str
    subject: str
    status: str
    visibility: str
    author: int
    created_at: str
    updated_at: Optional[str] = None
    published_at: Optional[str] = None

    class Config:
        from_attributes = True


class ReportDetailResponse(ReportResponse):
    """报告详情响应"""

    session_id: Optional[str] = None
    time_range: Optional[str] = None
    content_json: Optional[Dict[str, Any]] = None
    content_md: Optional[str] = None


# ============================================================================
# 工具调用
# ============================================================================


class ToolCallRequest(BaseModel):
    """工具调用请求"""

    tool_name: str = Field(..., description="工具名称")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="工具参数")


class ToolCallResponse(BaseModel):
    """工具调用响应"""

    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time_ms: int


# ============================================================================
# 错误响应
# ============================================================================


class ErrorResponse(BaseModel):
    """错误响应"""

    error_code: str = Field(..., description="错误码")
    message: str = Field(..., description="错误消息")
    detail: Optional[Dict[str, Any]] = Field(None, description="错误详情")
    trace_id: Optional[str] = Field(None, description="追踪 ID")


# ============================================================================
# 错误码定义
# ============================================================================


class DataAgentErrorCode:
    """Data Agent 错误码"""

    DAT_001 = "无效的指标名"
    DAT_002 = "会话不存在"
    DAT_003 = "会话状态冲突"
    DAT_004 = "SQL 执行超时"
    DAT_005 = "数据不可用"
    DAT_006 = "推理引擎错误"
    DAT_007 = "下游服务不可用"