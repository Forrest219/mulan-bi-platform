"""
Tests for Tableau MCP Write Operation Tools - Field Resolution (Spec 26 §4.1)

Tests cover:
- GetFieldSchemaTool
- ResolveFieldNameTool
- GetDatasourceFieldsSummaryTool
"""
import pytest
from unittest.mock import MagicMock, patch


class TestGetFieldSchemaTool:
    """Tests for GetFieldSchemaTool"""

    def test_requires_field_name_or_luid(self):
        """Must provide either field_name or field_luid"""
        from services.tableau.mcp_tools.base import TableauMCPToolBase, FieldResolutionError
        
        tool = TableauMCPToolBase(mcp_client=MagicMock())
        
        # Should raise error when neither is provided
        with pytest.raises(FieldResolutionError):
            tool.resolve_field_name(
                field_name="",
                datasource_luid="ds-123",
                connection_id=1,
            )

    def test_resolve_field_name_returns_candidates(self):
        """resolve_field_name returns candidates list"""
        from services.tableau.mcp_tools.base import TableauMCPToolBase
        
        tool = TableauMCPToolBase(
            mcp_client=MagicMock(),
            semantic_service=MagicMock(),
        )
        
        result = tool.resolve_field_name(
            field_name="region",
            datasource_luid="ds-123",
            connection_id=1,
        )
        
        assert "candidates" in result
        assert "confidence" in result
        assert "method" in result

    def test_resolve_field_name_with_role_filter(self):
        """resolve_field_name filters by required_role"""
        from services.tableau.mcp_tools.base import TableauMCPToolBase
        
        tool = TableauMCPToolBase(
            mcp_client=MagicMock(),
            semantic_service=MagicMock(),
        )
        
        result = tool.resolve_field_name(
            field_name="sales",
            datasource_luid="ds-123",
            connection_id=1,
            required_role="MEASURE",
        )
        
        # Should return result even if empty
        assert "candidates" in result
        assert "confidence" in result

    def test_generate_confirmation_plan(self):
        """generate_confirmation_plan creates proper structure"""
        from services.tableau.mcp_tools.base import TableauMCPToolBase, ConfirmationPlan
        
        tool = TableauMCPToolBase(mcp_client=MagicMock())
        
        plan = tool.generate_confirmation_plan(
            action_description="Update field caption",
            changes=[{"type": "update", "field": "Region"}],
            warnings=["Warning 1"],
            rollback_hint="Rollback hint",
        )
        
        assert isinstance(plan, ConfirmationPlan)
        assert plan.action_description == "Update field caption"
        assert len(plan.changes) == 1
        assert "Warning 1" in plan.warnings
        assert plan.rollback_hint == "Rollback hint"

    def test_confirmation_plan_to_dict(self):
        """ConfirmationPlan serializes to dict correctly"""
        from services.tableau.mcp_tools.base import TableauMCPToolBase, ConfirmationPlan
        
        tool = TableauMCPToolBase(mcp_client=MagicMock())
        
        plan = tool.generate_confirmation_plan(
            action_description="Test action",
            changes=[{"type": "create"}],
        )
        
        d = plan.to_dict()
        assert d["action_description"] == "Test action"
        assert d["changes"][0]["type"] == "create"
        assert "rollback_hint" in d


class TestResolveFieldNameTool:
    """Tests for ResolveFieldNameTool"""

    def test_tool_is_registered(self):
        """Tool should be registered in registry"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        metadata = registry.get_metadata("resolve-field-name")
        
        assert metadata is not None
        assert metadata.category == "field_resolution"
        assert metadata.requires_confirmation is False

    def test_tool_creates_instance(self):
        """Tool can be created via registry"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="resolve-field-name",
            mcp_client=MagicMock(),
            semantic_service=MagicMock(),
        )
        
        assert tool is not None
        assert tool.tool_name == "resolve-field-name"


class TestGetDatasourceFieldsSummaryTool:
    """Tests for GetDatasourceFieldsSummaryTool"""

    def test_tool_is_registered(self):
        """Tool should be registered"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        metadata = registry.get_metadata("get-datasource-fields-summary")
        
        assert metadata is not None
        assert metadata.category == "field_resolution"
        assert metadata.requires_confirmation is False

    def test_fields_summary_returns_correct_structure(self):
        """Execute returns expected structure"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        mock_client = MagicMock()
        mock_client.get_datasource_metadata.return_value = {
            "fields": [
                {"fieldName": "Region", "role": "DIMENSION", "dataType": "STRING", "isHidden": False},
                {"fieldName": "Sales", "role": "MEASURE", "dataType": "REAL", "isHidden": False},
            ]
        }
        
        tool = registry.create_tool(
            name="get-datasource-fields-summary",
            mcp_client=mock_client,
        )
        
        result = tool.execute(
            datasource_luid="ds-123",
            connection_id=1,
        )
        
        assert "fields" in result
        assert "total_count" in result
        assert "dimension_count" in result
        assert "measure_count" in result
        assert result["total_count"] == 2
        assert result["dimension_count"] == 1
        assert result["measure_count"] == 1


class TestFieldResolutionError:
    """Tests for error classes"""

    def test_field_resolution_error(self):
        """FieldResolutionError has correct structure"""
        from services.tableau.mcp_tools.base import FieldResolutionError
        
        err = FieldResolutionError(
            message="Field not found",
            details={"field_name": "test"},
        )
        
        assert err.code == "FIELD_RESOLUTION_FAILED"
        assert err.message == "Field not found"
        assert err.details["field_name"] == "test"

    def test_tool_error_base(self):
        """ToolError base class works"""
        from services.tableau.mcp_tools.base import ToolError
        
        err = ToolError(
            code="TEST_ERROR",
            message="Test error",
            details={"key": "value"},
        )
        
        assert err.code == "TEST_ERROR"
        assert str(err) == "[TEST_ERROR] Test error"
