"""Data Agent 框架层 — Phase 0 + Phase 2: 工具基类 + 注册表 + 动态发现

Spec: docs/specs/36-data-agent-architecture-spec.md §3.1-3.2
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
    """工具执行上下文（基础版）"""
    session_id: str
    user_id: int
    connection_id: Optional[int] = None
    trace_id: str = ""


@dataclass
class ToolMetadata:
    """工具元数据 — 用于动态发现和管理面板展示

    Attributes:
        category: 工具分类（query / analysis / visualization / reporting）
        version: 工具版本号
        dependencies: 工具依赖声明（如 requires_database, requires_tableau）
        output_schema: 输出结构描述（JSON Schema 格式，可选）
        tags: 额外标签（便于筛选）
    """
    category: str = "general"
    version: str = "1.0.0"
    dependencies: List[str] = field(default_factory=list)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)


class BaseTool(ABC):
    """所有 Agent 工具的基类

    子类必须实现：
    - name: str — 工具唯一标识
    - description: str — 用于 LLM 选择工具时的描述
    - parameters_schema: dict — JSON Schema，描述输入参数
    - async execute(params, context) -> ToolResult

    可选覆写：
    - metadata: ToolMetadata — 工具元数据（分类、版本、依赖等）
    """

    name: str = ""
    description: str = ""
    parameters_schema: dict = {}
    metadata: ToolMetadata = ToolMetadata()

    @abstractmethod
    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """执行工具，返回结果"""
        ...

    def get_full_metadata(self) -> dict:
        """返回包含名称、描述、参数和元数据的完整工具信息"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters_schema": self.parameters_schema,
            "category": self.metadata.category,
            "version": self.metadata.version,
            "dependencies": self.metadata.dependencies,
            "output_schema": self.metadata.output_schema,
            "tags": self.metadata.tags,
        }


# ---------------------------------------------------------------------------
# 工具自注册装饰器
# ---------------------------------------------------------------------------

# 全局注册表：收集通过 @agent_tool 装饰的工具类
_auto_discovered_tools: List[type] = []


def agent_tool(cls: type) -> type:
    """装饰器 — 自动注册工具类到全局发现列表。

    用法::

        @agent_tool
        class MyTool(BaseTool):
            name = "my_tool"
            ...

    运行时通过 ``get_discovered_tool_classes()`` 获取所有已发现的工具类。
    """
    if not issubclass(cls, BaseTool):
        raise TypeError(f"@agent_tool 只能装饰 BaseTool 子类, 收到: {cls}")
    _auto_discovered_tools.append(cls)
    return cls


def get_discovered_tool_classes() -> List[type]:
    """返回所有通过 @agent_tool 装饰器注册的工具类"""
    return list(_auto_discovered_tools)


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------


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

    def auto_discover(self) -> int:
        """自动发现并注册所有通过 @agent_tool 装饰器声明的工具。

        Returns:
            新注册的工具数量。
        """
        count = 0
        for tool_cls in get_discovered_tool_classes():
            instance = tool_cls()
            if instance.name and instance.name not in self._tools:
                self._tools[instance.name] = instance
                count += 1
        return count

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

    def get_tools_metadata(self) -> list:
        """返回所有工具的完整元数据（含分类、版本、依赖等），
        用于 GET /api/agent/tools 端点"""
        return [tool.get_full_metadata() for tool in self._tools.values()]

    def get_tools_by_category(self, category: str) -> list:
        """按分类筛选工具"""
        return [
            tool for tool in self._tools.values()
            if tool.metadata.category == category
        ]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)