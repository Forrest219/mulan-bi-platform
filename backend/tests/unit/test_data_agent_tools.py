"""单元测试：Data Agent tool_base — ToolResult / ToolContext / ToolRegistry / BaseTool

覆盖范围：
- ToolResult: to_dict, 字段默认值
- ToolContext: 字段赋值
- ToolMetadata: 默认值
- BaseTool: get_full_metadata
- ToolRegistry: register, get, list_tools, get_tool_descriptions, contains, len
- ToolRegistry: 重复注册、空名称错误
- ToolRegistry: auto_discover, get_tools_metadata, get_tools_by_category
- agent_tool 装饰器: 注册 + 类型检查
"""
import os
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "")

from services.data_agent.tool_base import (
    ToolResult,
    ToolContext,
    ToolMetadata,
    BaseTool,
    ToolRegistry,
    agent_tool,
    get_discovered_tool_classes,
    _auto_discovered_tools,
)


# =====================================================================
# ToolResult
# =====================================================================


class TestToolResult:
    """ToolResult 数据类测试"""

    def test_success_result(self):
        result = ToolResult(success=True, data={"count": 42})
        assert result.success is True
        assert result.data == {"count": 42}
        assert result.error is None
        assert result.execution_time_ms == 0

    def test_error_result(self):
        result = ToolResult(success=False, error="timeout")
        assert result.success is False
        assert result.error == "timeout"

    def test_to_dict(self):
        result = ToolResult(success=True, data=[1, 2, 3], execution_time_ms=150)
        d = result.to_dict()
        assert d["success"] is True
        assert d["data"] == [1, 2, 3]
        assert d["error"] is None
        assert d["execution_time_ms"] == 150


# =====================================================================
# ToolContext
# =====================================================================


class TestToolContext:
    """ToolContext 数据类测试"""

    def test_basic_context(self):
        ctx = ToolContext(session_id="sess-123", user_id=1)
        assert ctx.session_id == "sess-123"
        assert ctx.user_id == 1
        assert ctx.connection_id is None
        assert ctx.trace_id == ""

    def test_full_context(self):
        ctx = ToolContext(
            session_id="sess-456",
            user_id=2,
            connection_id=10,
            trace_id="trace-abc",
        )
        assert ctx.connection_id == 10
        assert ctx.trace_id == "trace-abc"


# =====================================================================
# ToolMetadata
# =====================================================================


class TestToolMetadata:
    """ToolMetadata 数据类测试"""

    def test_defaults(self):
        meta = ToolMetadata()
        assert meta.category == "general"
        assert meta.version == "1.0.0"
        assert meta.dependencies == []
        assert meta.output_schema == {}
        assert meta.tags == []

    def test_custom_metadata(self):
        meta = ToolMetadata(
            category="analysis",
            version="2.0.0",
            dependencies=["requires_database"],
            tags=["advanced"],
        )
        assert meta.category == "analysis"
        assert meta.version == "2.0.0"
        assert "requires_database" in meta.dependencies


# =====================================================================
# BaseTool / get_full_metadata
# =====================================================================


class _DummyTool(BaseTool):
    name = "dummy"
    description = "A test tool"
    parameters_schema = {"type": "object"}
    metadata = ToolMetadata(category="test", version="0.1.0")

    async def execute(self, params, context):
        return ToolResult(success=True, data="ok")


class TestBaseTool:
    """BaseTool 基类测试"""

    def test_get_full_metadata(self):
        tool = _DummyTool()
        meta = tool.get_full_metadata()
        assert meta["name"] == "dummy"
        assert meta["description"] == "A test tool"
        assert meta["category"] == "test"
        assert meta["version"] == "0.1.0"
        assert meta["parameters_schema"] == {"type": "object"}


# =====================================================================
# ToolRegistry
# =====================================================================


class TestToolRegistry:
    """ToolRegistry 注册表测试"""

    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = _DummyTool()
        reg.register(tool)
        assert reg.get("dummy") is tool

    def test_register_empty_name_raises(self):
        reg = ToolRegistry()

        class EmptyNameTool(BaseTool):
            name = ""
            async def execute(self, params, context):
                pass

        with pytest.raises(ValueError, match="不能为空"):
            reg.register(EmptyNameTool())

    def test_register_duplicate_raises(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        with pytest.raises(ValueError, match="已注册"):
            reg.register(_DummyTool())

    def test_get_nonexistent_raises(self):
        reg = ToolRegistry()
        with pytest.raises(KeyError, match="不存在"):
            reg.get("nonexistent")

    def test_list_tools(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        tools = reg.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "dummy"

    def test_get_tool_descriptions(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        descs = reg.get_tool_descriptions()
        assert len(descs) == 1
        assert descs[0]["name"] == "dummy"
        assert descs[0]["description"] == "A test tool"
        assert "parameters_schema" in descs[0]

    def test_get_tools_metadata(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        metas = reg.get_tools_metadata()
        assert len(metas) == 1
        assert metas[0]["category"] == "test"

    def test_get_tools_by_category(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())

        # 匹配
        found = reg.get_tools_by_category("test")
        assert len(found) == 1

        # 不匹配
        empty = reg.get_tools_by_category("analysis")
        assert len(empty) == 0

    def test_contains(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        assert "dummy" in reg
        assert "nonexistent" not in reg

    def test_len(self):
        reg = ToolRegistry()
        assert len(reg) == 0
        reg.register(_DummyTool())
        assert len(reg) == 1


# =====================================================================
# agent_tool 装饰器
# =====================================================================


class TestAgentToolDecorator:
    """@agent_tool 装饰器测试"""

    def test_decorator_registers_tool(self):
        """装饰器将工具类添加到全局发现列表"""
        initial_count = len(_auto_discovered_tools)

        @agent_tool
        class _TestAutoTool(BaseTool):
            name = "auto_test"
            async def execute(self, params, context):
                return ToolResult(success=True)

        assert len(_auto_discovered_tools) == initial_count + 1
        assert _auto_discovered_tools[-1] is _TestAutoTool

        # 清理
        _auto_discovered_tools.pop()

    def test_decorator_rejects_non_basetool(self):
        """装饰器拒绝非 BaseTool 子类"""
        with pytest.raises(TypeError, match="BaseTool 子类"):
            @agent_tool
            class NotATool:
                pass


# =====================================================================
# auto_discover
# =====================================================================


class TestAutoDiscover:
    """ToolRegistry.auto_discover 测试"""

    def test_auto_discover_registers_tools(self):
        """auto_discover 注册已发现的工具"""
        # 先手动加入一个工具到全局列表
        @agent_tool
        class _AutoDiscoveredTool(BaseTool):
            name = "auto_discovered_test"
            async def execute(self, params, context):
                return ToolResult(success=True)

        try:
            reg = ToolRegistry()
            count = reg.auto_discover()
            # 应该至少发现 1 个（我们刚注册的）
            assert count >= 1
            assert "auto_discovered_test" in reg
        finally:
            # 清理
            _auto_discovered_tools.remove(_AutoDiscoveredTool)
