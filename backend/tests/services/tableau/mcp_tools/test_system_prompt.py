"""
Tests for Tableau MCP Write Operation Tools - System Prompt & Registry (Spec 26 §5)

Tests cover:
- MCPToolRegistry
- TableauAgentPromptTemplate
- ConfirmationDialogBuilder
"""
import pytest
from unittest.mock import MagicMock


class TestMCPToolRegistry:
    """Tests for MCPToolRegistry"""

    def test_registry_is_singleton(self):
        """Registry should be singleton"""
        from services.tableau.mcp_tools.registry import MCPToolRegistry, get_tool_registry
        
        reg1 = MCPToolRegistry()
        reg2 = MCPToolRegistry()
        
        assert reg1 is reg2
        
        # Also test the factory function
        factory1 = get_tool_registry()
        factory2 = get_tool_registry()
        
        assert factory1 is factory2

    def test_list_tools_returns_all_registered(self):
        """list_tools returns all registered tools"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        tools = registry.list_tools()
        
        # Should have at least the write operation tools
        assert "resolve-field-name" in tools
        assert "get-view-filter-url" in tools
        assert "update-field-caption" in tools
        assert "publish-field-semantic" in tools

    def test_list_tools_filters_by_category(self):
        """list_tools can filter by category"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        field_tools = registry.list_tools(category="field_resolution")
        
        assert "get-field-schema" in field_tools
        assert "resolve-field-name" in field_tools
        assert "get-datasource-fields-summary" in field_tools
        
        # Should not have tools from other categories
        for tool_name in field_tools:
            assert field_tools[tool_name].category == "field_resolution"

    def test_list_categories_returns_all_categories(self):
        """list_categories returns all unique categories"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        categories = registry.list_categories()
        
        assert "field_resolution" in categories
        assert "view_control" in categories
        assert "semantic_writeback" in categories
        assert "parameter_control" in categories

    def test_get_tool_returns_class(self):
        """get_tool returns the tool class"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        tool_class = registry.get_tool("resolve-field-name")
        
        assert tool_class is not None

    def test_create_tool_creates_instance(self):
        """create_tool creates a tool instance"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        tool = registry.create_tool(
            name="get-view-filter-url",
            mcp_client=MagicMock(),
        )
        
        assert tool is not None
        assert tool.tool_name == "get-view-filter-url"

    def test_create_tool_with_dependencies(self):
        """create_tool passes dependencies"""
        from services.tableau.mcp_tools.registry import get_tool_registry
        
        registry = get_tool_registry()
        mock_client = MagicMock()
        mock_service = MagicMock()
        
        tool = registry.create_tool(
            name="resolve-field-name",
            mcp_client=mock_client,
            semantic_service=mock_service,
        )
        
        assert tool.mcp_client is mock_client
        assert tool.semantic_service is mock_service


class TestTableauAgentPromptTemplate:
    """Tests for TableauAgentPromptTemplate"""

    def test_build_system_prompt_returns_string(self):
        """build_system_prompt returns a non-empty string"""
        from services.tableau.mcp_tools.system_prompt import TableauAgentPromptTemplate
        
        prompt = TableauAgentPromptTemplate.build_system_prompt()
        
        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "MULAN TABLEAU AGENT SYSTEM PROMPT" in prompt

    def test_prompt_contains_all_sections(self):
        """Prompt contains all required sections"""
        from services.tableau.mcp_tools.system_prompt import TableauAgentPromptTemplate
        
        prompt = TableauAgentPromptTemplate.build_system_prompt()
        
        assert "SECTION 1" in prompt
        assert "SECTION 2" in prompt or "TOOL CATALOG" in prompt
        assert "SECTION 3" in prompt or "TOOL CALLING STRATEGY" in prompt
        assert "SECTION 4" in prompt or "WRITE OPERATION SAFETY" in prompt
        assert "SECTION 5" in prompt or "ERROR HANDLING" in prompt

    def test_prompt_contains_write_rules(self):
        """Prompt contains write operation safety rules"""
        from services.tableau.mcp_tools.system_prompt import TableauAgentPromptTemplate
        
        prompt = TableauAgentPromptTemplate.build_system_prompt()
        
        assert "CONFIRMATION" in prompt
        assert "WRITE OPERATION" in prompt or "写操作" in prompt

    def test_prompt_contains_decision_tree(self):
        """Prompt contains decision tree"""
        from services.tableau.mcp_tools.system_prompt import TableauAgentPromptTemplate
        
        prompt = TableauAgentPromptTemplate.build_system_prompt()
        
        assert "DECISION TREE" in prompt or "判断" in prompt

    def test_get_write_operation_tools(self):
        """get_write_operation_tools returns correct list"""
        from services.tableau.mcp_tools.system_prompt import TableauAgentPromptTemplate
        
        write_tools = TableauAgentPromptTemplate.get_write_operation_tools()
        
        assert "update-field-caption" in write_tools
        assert "update-field-description" in write_tools
        assert "publish-field-semantic" in write_tools
        assert "create-custom-view" in write_tools
        assert "update-custom-view" in write_tools
        assert "run-vizql-command" in write_tools

    def test_get_read_only_tools(self):
        """get_read_only_tools returns correct list"""
        from services.tableau.mcp_tools.system_prompt import TableauAgentPromptTemplate
        
        read_tools = TableauAgentPromptTemplate.get_read_only_tools()
        
        assert "get-field-schema" in read_tools
        assert "resolve-field-name" in read_tools
        assert "get-datasource-fields-summary" in read_tools
        assert "get-view-filter-url" in read_tools
        assert "set-parameter-via-url" in read_tools

    def test_extra_rules_appended(self):
        """Extra rules are appended to prompt"""
        from services.tableau.mcp_tools.system_prompt import TableauAgentPromptTemplate
        
        prompt = TableauAgentPromptTemplate.build_system_prompt(
            extra_rules="CUSTOM RULE: Always say hello first."
        )
        
        assert "CUSTOM RULE" in prompt


class TestConfirmationDialogBuilder:
    """Tests for ConfirmationDialogBuilder"""

    def test_build_write_confirmation(self):
        """build_write_confirmation returns expected structure"""
        from services.tableau.mcp_tools.system_prompt import ConfirmationDialogBuilder
        
        result = ConfirmationDialogBuilder.build_write_confirmation(
            tool_name="update-field-caption",
            action_description="Update field caption",
            changes=[{"type": "update", "field": "Region"}],
            warnings=["Warning 1"],
            rollback_hint="Rollback hint",
        )
        
        assert result["type"] == "confirmation_dialog"
        assert result["tool_name"] == "update-field-caption"
        assert result["action_description"] == "Update field caption"
        assert len(result["changes"]) == 1
        assert "Warning 1" in result["warnings"]
        assert result["rollback_hint"] == "Rollback hint"

    def test_build_field_candidates_prompt_single(self):
        """build_field_candidates_prompt handles single candidate"""
        from services.tableau.mcp_tools.system_prompt import ConfirmationDialogBuilder
        
        result = ConfirmationDialogBuilder.build_field_candidates_prompt(
            candidates=[
                {"tableau_field_id": "Region", "role": "DIMENSION", "data_type": "STRING"}
            ],
            original_query="region",
        )
        
        assert "Region" in result
        assert "DIMENSION" in result

    def test_build_field_candidates_prompt_multiple(self):
        """build_field_candidates_prompt handles multiple candidates"""
        from services.tableau.mcp_tools.system_prompt import ConfirmationDialogBuilder
        
        result = ConfirmationDialogBuilder.build_field_candidates_prompt(
            candidates=[
                {"tableau_field_id": "Region", "role": "DIMENSION", "data_type": "STRING"},
                {"tableau_field_id": "Region Code", "role": "DIMENSION", "data_type": "INTEGER"},
            ],
            original_query="region",
        )
        
        assert "找到 2 个" in result or "2" in result
        assert "Region" in result
        assert "Region Code" in result

    def test_build_field_candidates_prompt_empty(self):
        """build_field_candidates_prompt handles no candidates"""
        from services.tableau.mcp_tools.system_prompt import ConfirmationDialogBuilder
        
        result = ConfirmationDialogBuilder.build_field_candidates_prompt(
            candidates=[],
            original_query="xyz",
        )
        
        assert "无法找到" in result or "not found" in result.lower()


class TestMCPToolDispatcher:
    """Tests for MCPToolDispatcher"""

    def test_list_tools(self):
        """list_tools returns all available tools"""
        from services.tableau.mcp_tools.dispatcher import get_dispatcher
        
        dispatcher = get_dispatcher()
        tools = dispatcher.list_tools()
        
        assert len(tools) > 0
        assert "resolve-field-name" in tools

    def test_get_tool_info(self):
        """get_tool_info returns metadata"""
        from services.tableau.mcp_tools.dispatcher import get_dispatcher
        
        dispatcher = get_dispatcher()
        info = dispatcher.get_tool_info("get-view-filter-url")
        
        assert info is not None
        assert info["name"] == "get-view-filter-url"
        assert "category" in info
        assert "requires_confirmation" in info

    def test_prepare_tool_read_only(self):
        """prepare_tool executes read-only tools directly"""
        from services.tableau.mcp_tools.dispatcher import get_dispatcher
        
        dispatcher = get_dispatcher(mcp_client=MagicMock())
        
        result = dispatcher.prepare_tool(
            tool_name="get-view-filter-url",
            view_url="https://example.com/view",
            filters=[],
        )
        
        # Should execute directly for read-only tools
        assert "filter_url" in result

    def test_prepare_tool_write_operation(self):
        """prepare_tool returns confirmation plan for write operations"""
        from services.tableau.mcp_tools.dispatcher import get_dispatcher
        
        dispatcher = get_dispatcher(mcp_client=MagicMock())
        
        result = dispatcher.prepare_tool(
            tool_name="create-custom-view",
            view_luid="view-123",
            view_name="Test View",
        )
        
        # Should return confirmation plan
        assert "tool_name" in result or "confirmation_plan" in result

    def test_execute_tool_requires_confirmation(self):
        """execute_tool requires confirmation for write operations"""
        from services.tableau.mcp_tools.dispatcher import get_dispatcher
        
        dispatcher = get_dispatcher(mcp_client=MagicMock())
        
        result = dispatcher.execute_tool(
            tool_name="update-field-caption",
            confirmation_received=False,
            datasource_luid="ds-123",
            field_name="Region",
            new_caption="New Caption",
        )
        
        # Should indicate confirmation is needed
        assert result.get("requires_confirmation") is True

    def test_execute_tool_with_confirmation(self):
        """execute_tool executes when confirmation received"""
        from services.tableau.mcp_tools.dispatcher import get_dispatcher
        
        dispatcher = get_dispatcher(mcp_client=MagicMock())
        
        result = dispatcher.execute_tool(
            tool_name="update-field-caption",
            confirmation_received=True,
            datasource_luid="ds-123",
            field_name="Region",
            new_caption="New Caption",
            update_semantic_layer=False,
        )
        
        # Should execute
        assert result.get("updated") is True

    def test_get_confirmation_needed(self):
        """get_confirmation_needed returns plan for write tools"""
        from services.tableau.mcp_tools.dispatcher import get_dispatcher
        
        dispatcher = get_dispatcher(mcp_client=MagicMock())
        
        plan = dispatcher.get_confirmation_needed(
            tool_name="update-custom-view",
            custom_view_luid="cv-123",
        )
        
        assert plan is not None
