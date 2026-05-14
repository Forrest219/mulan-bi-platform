"""Help Agent request, planner, tool, and SSE schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EntryPoint(str, Enum):
    global_drawer = "global_drawer"
    inline_panel = "inline_panel"
    route_page = "route_page"


class SSEEventType(str, Enum):
    metadata = "metadata"
    thinking = "thinking"
    diagnostic_progress = "diagnostic_progress"
    tool_call = "tool_call"
    tool_result = "tool_result"
    token = "token"
    done = "done"
    error = "error"


class DiagnosticStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class PageSelection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary_entity: Optional[dict[str, Any]] = None
    entities: Optional[list[dict[str, Any]]] = None
    query_refs: Optional[dict[str, str]] = None

    run_id: Optional[str] = None
    task_run_id: Optional[Union[int, str]] = None
    connection_id: Optional[Union[int, str]] = None
    tableau_connection_id: Optional[Union[int, str]] = None
    skill_key: Optional[str] = None
    asset_id: Optional[Union[int, str]] = None


class PageContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    entry_point: Optional[EntryPoint] = None
    path: Optional[str] = None
    query: dict[str, Any] = Field(default_factory=dict)
    selection: Optional[PageSelection] = None
    visible_state: Optional[dict[str, Any]] = None
    client_time: Optional[str] = None


class HelpAgentRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str = ""
    conversation_id: Optional[Union[UUID, str]] = None
    entry_point: EntryPoint = EntryPoint.global_drawer
    page_context: Optional[PageContext] = None

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: Optional[str]) -> str:
        return (value or "").strip()


class RelatedEntity(BaseModel):
    type: str
    id: Union[str, int]
    reason: str = ""


class ToolCallPlan(BaseModel):
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    target_type: str
    target_id: str
    label: str
    reason: str = ""
    depth: int = 0

    @property
    def entity_key(self) -> str:
        return f"{self.tool_name}:{self.target_type}:{self.target_id}"

    @property
    def step_key(self) -> str:
        return f"{self.tool_name}:{self.target_id}"


class PlannerDecision(BaseModel):
    intent: str
    tool_calls: list[ToolCallPlan] = Field(default_factory=list)
    page_context_hint: dict[str, Any] = Field(default_factory=dict)
    conflict_with_selection: bool = False
    user_message_hint: Optional[str] = None


class DiagnosticFinding(BaseModel):
    severity: str = "info"
    code: str
    message: str


class DiagnosticRecommendation(BaseModel):
    priority: str = "P2"
    action: str


class ToolResultData(BaseModel):
    model_config = ConfigDict(extra="allow")

    tool: str
    snapshot_at: str
    target: dict[str, Any]
    facts: dict[str, Any] = Field(default_factory=dict)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    related_entities: list[dict[str, Any]] = Field(default_factory=list)


class DiagnosticProgressEvent(BaseModel):
    type: SSEEventType = SSEEventType.diagnostic_progress
    run_id: str
    step_key: str
    label: str
    status: DiagnosticStatus
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    execution_time_ms: Optional[int] = None
    message: Optional[str] = None


class ResponseData(BaseModel):
    snapshot_started_at: str
    snapshot_completed_at: str
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    related_entities: list[dict[str, Any]] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


class SSEEvent(BaseModel):
    type: SSEEventType
    conversation_id: Optional[str] = None
    run_id: Optional[str] = None
    trace_id: Optional[str] = None
    content: Optional[str] = None
    answer: Optional[str] = None
    error_code: Optional[str] = None
    message: Optional[str] = None
    user_hint: Optional[str] = None
    tool_name: Optional[str] = None
    tool_params: Optional[dict[str, Any]] = None
    result: Optional[dict[str, Any]] = None
    response_type: Optional[str] = None
    response_data: Optional[dict[str, Any]] = None
    tools_used: Optional[list[str]] = None
    steps_count: Optional[int] = None
    execution_time_ms: Optional[int] = None
    sources_count: Optional[int] = None
    top_sources: Optional[list[str]] = None


def utc_snapshot() -> str:
    return datetime.now().astimezone().isoformat()
