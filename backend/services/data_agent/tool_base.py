"""Data Agent 框架层 — Phase 0: 工具基类 + 注册表

Spec: docs/specs/36-data-agent-architecture-spec.md §3.1-3.2
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    execution_time_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
        }


@dataclass
class ToolContext:
    """工具执行上下文"""
    session_id: str
    user_id: int
    connection_id: Optional[int] = None
    trace_id: str = ""


class BaseTool(ABC):
    """所有 Agent 工具的基类

    子类必须实现：
    - name: str — 工具唯一标识
    - description: str — 用于 LLM 选择工具时的描述
    - parameters_schema: dict — JSON Schema，描述输入参数
    - async execute(params, context) -> ToolResult
    """

    name: str = ""
    description: str = ""
    parameters_schema: dict = {}

    @abstractmethod
    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """执行工具，返回结果"""
        ...


class ToolRegistry:
    """工具注册表，管理所有可用工具

    重复注册同名工具抛异常。
    """

    def __init__(self):
        self._tools: dict = {}

    def register(self, tool: BaseTool) -> None:
        """注册工具"""
        if not tool.name:
            raise ValueError("工具 name 不能为空")
        if tool.name in self._tools:
            raise ValueError(f"工具已注册: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        """获取工具，不存在抛 KeyError"""
        if name not in self._tools:
            raise KeyError(f"工具不存在: {name}")
        return self._tools[name]

    def list_tools(self) -> list:
        """返回所有已注册工具"""
        return list(self._tools.values())

    def get_tool_descriptions(self) -> list:
        """返回所有工具的 name + description + parameters_schema，
        用于构造 LLM 的 system prompt"""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters_schema": tool.parameters_schema,
            }
            for tool in self._tools.values()
        ]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)