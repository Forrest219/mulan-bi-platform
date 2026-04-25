"""
AgentResponse + AgentEvent data classes

Spec: docs/specs/36-data-agent-architecture-spec.md §3.4-3.5
"""

from dataclasses import dataclass, field
from typing import Any, Optional
import time


@dataclass
class AgentResponse:
    """统一响应模型 — 最终回答时使用"""
    answer: str
    type: str  # 'text' | 'table' | 'number' | 'chart_spec' | 'error'
    data: Any  # 额外结构化数据
    trace_id: str
    confidence: float
    tools_used: list[str]
    steps_count: int
    session_id: str


@dataclass
class AgentEvent:
    """
    流式事件 — SSE 传输
    
    类型:
    - metadata: 元数据（conversation_id 等）
    - thinking: Agent 推理过程
    - tool_call: 正在调用的工具及参数
    - tool_result: 工具返回结果
    - token: 回答 token（逐字输出）
    - done: 完成信号（包含最终结果）
    - error: 错误
    """
    type: str
    content: Any
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "content": self.content,
            "timestamp": self.timestamp,
        }