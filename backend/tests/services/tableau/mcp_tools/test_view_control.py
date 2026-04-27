"""
Tests for Tableau MCP Write Operation Tools - View Control (Spec 26 §4.2)

Tests cover:
- GetViewFilterURLTool
- CreateCustomViewTool
- UpdateCustomViewTool
- ListCustomViewsForViewTool
"""
import pytest
from unittest.mock import MagicMock, patch


class TestGetViewFilterURLTool:
    """Tests for GetViewFilterURLTool"""

    def test_tool_is_registered(self):
        """Tool should be registered"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        metadata = registry.get_metadata("get-view-filter-url")
        
        assert metadata is not None
        assert metadata.category == "view_control"
        assert metadata.requires_confirmation is False  # URL generation only

    def test_generates_filter_url_with_single_filter(self):
        """Generates URL with single filter correctly"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="get-view-filter-url",
            mcp_client=MagicMock(),
        )
        
        result = tool.execute(
            view_url="https://tableau.example.com/views/Workbook/View",
            filters=[{"field": "Region", "value": "East"}],
        )
        
        assert "filter_url" in result
        assert "vf_Region=East" in result["filter_url"]
        assert len(result["filters_applied"]) == 1

    def test_generates_filter_url_with_multiple_filters(self):
        """Generates URL with multiple filters"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="get-view-filter-url",
            mcp_client=MagicMock(),
        )
        
        result = tool.execute(
            view_url="https://tableau.example.com/views/Workbook/View",
            filters=[
                {"field": "Region", "value": "East"},
                {"field": "Year", "value": 2024},
            ],
        )
        
        assert "filter_url" in result
        assert "vf_Region=East" in result["filter_url"]
        assert "vf_Year=2024" in result["filter_url"]
        assert len(result["filters_applied"]) == 2

    def test_generates_filter_url_with_no_filters(self):
        """Returns base URL when no filters"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="get-view-filter-url",
            mcp_client=MagicMock(),
        )
        
        result = tool.execute(
            view_url="https://tableau.example.com/views/Workbook/View",
            filters=[],
        )
        
        assert result["filter_url"] == "https://tableau.example.com/views/Workbook/View"
        assert len(result["filters_applied"]) == 0

    def test_filter_url_with_existing_query_params(self):
        """Handles view URLs that already have query params"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="get-view-filter-url",
            mcp_client=MagicMock(),
        )
        
        result = tool.execute(
            view_url="https://tableau.example.com/views/Workbook/View?existing=param",
            filters=[{"field": "Region", "value": "West"}],
        )
        
        assert "existing=param" in result["filter_url"]
        assert "vf_Region=West" in result["filter_url"]

    def test_returns_warning_about_temporary_filter(self):
        """Returns warning that filter is temporary"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="get-view-filter-url",
            mcp_client=MagicMock(),
        )
        
        result = tool.execute(
            view_url="https://tableau.example.com/views/Workbook/View",
            filters=[{"field": "Region", "value": "East"}],
        )
        
        assert "warning" in result
        assert "temporary" in result["warning"].lower()


class TestCreateCustomViewTool:
    """Tests for CreateCustomViewTool"""

    def test_tool_requires_confirmation(self):
        """Tool should require confirmation"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = MCPToolRegistry()
        metadata = registry.get_metadata("create-custom-view")
        
        assert metadata is not None
        assert metadata.requires_confirmation is True

    def test_dry_run_returns_confirmation_plan(self):
        """dry_run returns confirmation plan"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="create-custom-view",
            mcp_client=MagicMock(),
        )
        
        plan = tool.dry_run(
            view_luid="view-123",
            view_name="My Custom View",
            filters=[{"field": "Region", "value": "East"}],
        )
        
        assert plan.tool_name == "create-custom-view"
        assert "create" in plan.changes[0]["type"]
        assert len(plan.warnings) > 0
        assert plan.rollback_hint is not None

    def test_execute_requires_view_luid(self):
        """execute raises error without view_luid"""
        from services.tableau.mcp_tools.base import WriteOperationError
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="create-custom-view",
            mcp_client=MagicMock(),
        )
        
        with pytest.raises(WriteOperationError):
            tool.execute(
                view_luid="",
                view_name="Test",
            )

    def test_execute_requires_view_name(self):
        """execute raises error without view_name"""
        from services.tableau.mcp_tools.base import WriteOperationError
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="create-custom-view",
            mcp_client=MagicMock(),
        )
        
        with pytest.raises(WriteOperationError):
            tool.execute(
                view_luid="view-123",
                view_name="",
            )


class TestUpdateCustomViewTool:
    """Tests for UpdateCustomViewTool"""

    def test_tool_requires_confirmation(self):
        """Tool should require confirmation"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = MCPToolRegistry()
        metadata = registry.get_metadata("update-custom-view")
        
        assert metadata is not None
        assert metadata.requires_confirmation is True

    def test_dry_run_returns_confirmation_plan(self):
        """dry_run returns confirmation plan"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="update-custom-view",
            mcp_client=MagicMock(),
        )
        
        plan = tool.dry_run(
            custom_view_luid="cv-123",
            filters=[{"field": "Region", "value": "West"}],
        )
        
        assert plan.tool_name == "update-custom-view"
        assert "update" in plan.changes[0]["type"]

    def test_execute_requires_custom_view_luid(self):
        """execute raises error without custom_view_luid"""
        from services.tableau.mcp_tools.base import WriteOperationError
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="update-custom-view",
            mcp_client=MagicMock(),
        )
        
        with pytest.raises(WriteOperationError):
            tool.execute(custom_view_luid="")


class TestListCustomViewsForViewTool:
    """Tests for ListCustomViewsForViewTool"""

    def test_tool_is_read_only(self):
        """Tool should not require confirmation"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = MCPToolRegistry()
        metadata = registry.get_metadata("list-custom-views-for-view")
        
        assert metadata is not None
        assert metadata.requires_confirmation is False

    def test_execute_requires_view_luid(self):
        """execute raises error without view_luid"""
        from services.tableau.mcp_tools.base import WriteOperationError
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="list-custom-views-for-view",
            mcp_client=MagicMock(),
        )
        
        with pytest.raises(WriteOperationError):
            tool.execute(view_luid="")
