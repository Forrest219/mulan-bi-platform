"""Data Agent 框架层 — Phase 0 + Phase 2

导出核心类供 Phase 1+ 使用。
"""

from .tool_base import (
    BaseTool,
    ToolContext,
    ToolResult,
    ToolRegistry,
    ToolMetadata,
    agent_tool,
    get_discovered_tool_classes,
)
from .response import AgentEvent, AgentResponse
from .engine import ReActEngine
from .prompts import build_react_system_prompt, DEFAULT_SYSTEM_PROMPT

__all__ = [
    "BaseTool",
    "ToolContext",
    "ToolResult",
    "ToolRegistry",
    "ToolMetadata",
    "agent_tool",
    "get_discovered_tool_classes",
    "AgentEvent",
    "AgentResponse",
    "ReActEngine",
    "build_react_system_prompt",
    "DEFAULT_SYSTEM_PROMPT",
]