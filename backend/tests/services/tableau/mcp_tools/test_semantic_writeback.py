"""
Tests for Tableau MCP Write Operation Tools - Semantic Writeback (Spec 26 §4.3)

Tests cover:
- UpdateFieldCaptionTool
- UpdateFieldDescriptionTool
- PublishFieldSemanticTool
"""
import pytest
from unittest.mock import MagicMock, patch


class TestUpdateFieldCaptionTool:
    """Tests for UpdateFieldCaptionTool"""

    def test_tool_requires_confirmation(self):
        """Tool should require confirmation"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        metadata = registry.get_metadata("update-field-caption")
        
        assert metadata is not None
        assert metadata.requires_confirmation is True

    def test_dry_run_returns_confirmation_plan(self):
        """dry_run returns confirmation plan"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="update-field-caption",
            mcp_client=MagicMock(),
        )
        
        plan = tool.dry_run(
            datasource_luid="ds-123",
            field_name="Region",
            new_caption="区域",
        )
        
        assert plan.tool_name == "update-field-caption"
        assert "update" in plan.changes[0]["type"]
        assert plan.changes[0]["new_caption"] == "区域"
        assert len(plan.warnings) > 0
        assert plan.rollback_hint is not None

    def test_execute_requires_datasource_luid(self):
        """execute raises error without datasource_luid"""
        from services.tableau.mcp_tools.base import WriteOperationError
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="update-field-caption",
            mcp_client=MagicMock(),
        )
        
        with pytest.raises(WriteOperationError):
            tool.execute(
                datasource_luid="",
                field_name="Region",
                new_caption="New Caption",
            )

    def test_execute_requires_field_name(self):
        """execute raises error without field_name"""
        from services.tableau.mcp_tools.base import WriteOperationError
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="update-field-caption",
            mcp_client=MagicMock(),
        )
        
        with pytest.raises(WriteOperationError):
            tool.execute(
                datasource_luid="ds-123",
                field_name="",
                new_caption="New Caption",
            )

    def test_execute_requires_new_caption(self):
        """execute raises error without new_caption"""
        from services.tableau.mcp_tools.base import WriteOperationError
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="update-field-caption",
            mcp_client=MagicMock(),
        )
        
        with pytest.raises(WriteOperationError):
            tool.execute(
                datasource_luid="ds-123",
                field_name="Region",
                new_caption="",
            )

    def test_execute_returns_update_result(self):
        """execute returns expected result structure"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="update-field-caption",
            mcp_client=MagicMock(),
        )
        
        result = tool.execute(
            datasource_luid="ds-123",
            field_name="Region",
            new_caption="区域",
            update_semantic_layer=False,
        )
        
        assert result["updated"] is True
        assert result["new_caption"] == "区域"
        assert result["field_name"] == "Region"


class TestUpdateFieldDescriptionTool:
    """Tests for UpdateFieldDescriptionTool"""

    def test_tool_requires_confirmation(self):
        """Tool should require confirmation"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        metadata = registry.get_metadata("update-field-description")
        
        assert metadata is not None
        assert metadata.requires_confirmation is True

    def test_dry_run_returns_confirmation_plan(self):
        """dry_run returns confirmation plan"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="update-field-description",
            mcp_client=MagicMock(),
        )
        
        plan = tool.dry_run(
            datasource_luid="ds-123",
            field_name="Sales",
            new_description="Total sales amount in USD",
        )
        
        assert plan.tool_name == "update-field-description"
        assert "update" in plan.changes[0]["type"]

    def test_execute_requires_description(self):
        """execute raises error when description is None"""
        from services.tableau.mcp_tools.base import WriteOperationError
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="update-field-description",
            mcp_client=MagicMock(),
        )
        
        with pytest.raises(WriteOperationError):
            tool.execute(
                datasource_luid="ds-123",
                field_name="Sales",
                new_description=None,
            )


class TestPublishFieldSemanticTool:
    """Tests for PublishFieldSemanticTool"""

    def test_tool_requires_confirmation(self):
        """Tool should require confirmation"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        metadata = registry.get_metadata("publish-field-semantic")
        
        assert metadata is not None
        assert metadata.requires_confirmation is True

    def test_execute_requires_field_id(self):
        """execute raises error without field_id"""
        from services.tableau.mcp_tools.base import WriteOperationError
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="publish-field-semantic",
            mcp_client=MagicMock(),
        )
        
        with pytest.raises(WriteOperationError):
            tool.execute(field_id=None, connection_id=1)

    def test_execute_requires_connection_id(self):
        """execute raises error without connection_id"""
        from services.tableau.mcp_tools.base import WriteOperationError
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="publish-field-semantic",
            mcp_client=MagicMock(),
        )
        
        with pytest.raises(WriteOperationError):
            tool.execute(field_id=1, connection_id=None)

    def test_dry_run_returns_field_info(self):
        """dry_run includes field info in plan"""
        from services.tableau.mcp_tools import MCPToolRegistry
        
        registry = MCPToolRegistry()
        tool = registry.create_tool(
            name="publish-field-semantic",
            mcp_client=MagicMock(),
            semantic_service=MagicMock(),
        )
        
        plan = tool.dry_run(field_id=1)
        
        assert plan.tool_name == "publish-field-semantic"
        assert plan.action_description is not None


class TestWriteOperationError:
    """Tests for write operation error classes"""

    def test_write_operation_error(self):
        """WriteOperationError has correct structure"""
        from services.tableau.mcp_tools.base import WriteOperationError
        
        err = WriteOperationError(
            message="Write failed",
            details={"field_id": 123},
        )
        
        assert err.code == "WRITE_OPERATION_FAILED"
        assert err.message == "Write failed"
        assert err.details["field_id"] == 123

    def test_intent_verification_error(self):
        """IntentVerificationError has correct structure"""
        from services.tableau.mcp_tools.base import IntentVerificationError
        
        err = IntentVerificationError(
            message="Field type mismatch",
            details={"expected": "DIMENSION", "actual": "MEASURE"},
        )
        
        assert err.code == "INTENT_VERIFY_FAILED"
        assert "Field type mismatch" in err.message
