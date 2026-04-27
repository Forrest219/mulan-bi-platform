"""
Tests for Tableau MCP Write Operation Tools - Parameter Control (Spec 26 §4.4)

Tests cover:
- GetWorkbookParametersTool
- SetParameterViaURLTool
- RunVizQLCommandTool
"""
import pytest
from unittest.mock import MagicMock


class TestGetWorkbookParametersTool:
    """Tests for GetWorkbookParametersTool"""

    def test_tool_is_registered(self):
        """Tool should be registered"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        metadata = registry.get_metadata("get-workbook-parameters")
        
        assert metadata is not None
        assert metadata.category == "parameter_control"
        assert metadata.requires_confirmation is False  # Read-only

    def test_execute_requires_workbook_luid(self):
        """execute raises error without workbook_luid"""
        from services.tableau.mcp_tools.base import WriteOperationError
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        tool = registry.create_tool(
            name="get-workbook-parameters",
            mcp_client=MagicMock(),
        )
        
        with pytest.raises(WriteOperationError):
            tool.execute(workbook_luid="")

    def test_returns_parameters_structure(self):
        """Returns expected result structure"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        tool = registry.create_tool(
            name="get-workbook-parameters",
            mcp_client=MagicMock(),
        )
        
        result = tool.execute(workbook_luid="wb-123")
        
        assert "workbook_luid" in result
        assert "parameters" in result
        assert "count" in result


class TestSetParameterViaURLTool:
    """Tests for SetParameterViaURLTool"""

    def test_tool_is_registered(self):
        """Tool should be registered"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        metadata = registry.get_tool_registry().get_metadata("set-parameter-via-url")
        
        assert metadata is not None
        assert metadata.category == "parameter_control"
        assert metadata.requires_confirmation is False  # URL generation only

    def test_generates_url_with_single_parameter(self):
        """Generates URL with single parameter"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        tool = registry.create_tool(
            name="set-parameter-via-url",
            mcp_client=MagicMock(),
        )
        
        result = tool.execute(
            view_url="https://tableau.example.com/views/Workbook/View",
            parameters=[{"name": "Fiscal Year", "value": 2024}],
        )
        
        assert "parameter_url" in result
        assert "Fiscal+Year=2024" in result["parameter_url"]
        assert len(result["parameters_applied"]) == 1

    def test_generates_url_with_multiple_parameters(self):
        """Generates URL with multiple parameters"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        tool = registry.create_tool(
            name="set-parameter-via-url",
            mcp_client=MagicMock(),
        )
        
        result = tool.execute(
            view_url="https://tableau.example.com/views/Workbook/View",
            parameters=[
                {"name": "Fiscal Year", "value": 2024},
                {"name": "Region", "value": "East"},
            ],
        )
        
        assert "parameter_url" in result
        assert "parameters_applied" in result
        assert len(result["parameters_applied"]) == 2

    def test_returns_base_url_when_no_parameters(self):
        """Returns base URL when no parameters"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        tool = registry.create_tool(
            name="set-parameter-via-url",
            mcp_client=MagicMock(),
        )
        
        result = tool.execute(
            view_url="https://tableau.example.com/views/Workbook/View",
            parameters=[],
        )
        
        assert result["parameter_url"] == "https://tableau.example.com/views/Workbook/View"
        assert len(result["parameters_applied"]) == 0

    def test_returns_warning_about_temporary_change(self):
        """Returns warning that change is temporary"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        tool = registry.create_tool(
            name="set-parameter-via-url",
            mcp_client=MagicMock(),
        )
        
        result = tool.execute(
            view_url="https://tableau.example.com/views/Workbook/View",
            parameters=[{"name": "Year", "value": 2024}],
        )
        
        assert "warning" in result
        assert "temporary" in result["warning"].lower()


class TestRunVizQLCommandTool:
    """Tests for RunVizQLCommandTool"""

    def test_tool_requires_confirmation(self):
        """Tool should require confirmation"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        metadata = registry.get_metadata("run-vizql-command")
        
        assert metadata is not None
        assert metadata.requires_confirmation is True

    def test_execute_requires_view_luid(self):
        """execute raises error without view_luid"""
        from services.tableau.mcp_tools.base import WriteOperationError
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        tool = registry.create_tool(
            name="run-vizql-command",
            mcp_client=MagicMock(),
        )
        
        with pytest.raises(WriteOperationError):
            tool.execute(
                view_luid="",
                command="set-parameter",
                target="Fiscal Year",
                value=2024,
            )

    def test_execute_requires_command(self):
        """execute raises error without command"""
        from services.tableau.mcp_tools.base import WriteOperationError
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        tool = registry.create_tool(
            name="run-vizql-command",
            mcp_client=MagicMock(),
        )
        
        with pytest.raises(WriteOperationError):
            tool.execute(
                view_luid="view-123",
                command="",
                target="Fiscal Year",
                value=2024,
            )

    def test_execute_requires_target(self):
        """execute raises error without target"""
        from services.tableau.mcp_tools.base import WriteOperationError
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        tool = registry.create_tool(
            name="run-vizql-command",
            mcp_client=MagicMock(),
        )
        
        with pytest.raises(WriteOperationError):
            tool.execute(
                view_luid="view-123",
                command="set-parameter",
                target=None,
                value=2024,
            )

    def test_dry_run_returns_confirmation_plan(self):
        """dry_run returns confirmation plan"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        tool = registry.create_tool(
            name="run-vizql-command",
            mcp_client=MagicMock(),
        )
        
        plan = tool.dry_run(
            view_luid="view-123",
            command="set-parameter",
            target="Fiscal Year",
            value=2024,
        )
        
        assert plan.tool_name == "run-vizql-command"
        assert "vizql_command" in plan.changes[0]["type"]
        assert len(plan.warnings) > 0
        assert "experimental" in plan.warnings[0].lower() or "beta" in plan.warnings[0].lower()
