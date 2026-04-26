"""
Tableau MCP Write Operations Tools - Registry (Spec 26)

Provides tool registration and discovery for MCP write operations.
Tools are registered by name and can be looked up for execution.
"""
import logging
from typing import Dict, Type, Optional, Any, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ToolMetadata:
    """Metadata about a registered MCP tool"""
    name: str
    description: str
    requires_confirmation: bool
    category: str  # field_resolution | view_control | semantic_writeback | parameter_control
    parameters: Dict[str, Any]


class MCPToolRegistry:
    """
    Registry for MCP write operation tools.
    
    Provides:
    - Tool registration
    - Tool discovery by name
    - Tool listing by category
    - Tool instantiation with dependencies
    """
    
    _instance: Optional["MCPToolRegistry"] = None
    _tools: Dict[str, Type["TableauMCPToolBase"]] = {}
    _metadata: Dict[str, ToolMetadata] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
            cls._instance._metadata = {}
        return cls._instance
    
    @classmethod
    def get_tool_registry(cls) -> "MCPToolRegistry":
        """Get the singleton registry instance"""
        return cls()
    
    def register(
        self,
        tool_class: Type["TableauMCPToolBase"],
        metadata: ToolMetadata,
    ) -> None:
        """
        Register a tool class with its metadata.
        
        Args:
            tool_class: The tool class (not instance)
            metadata: Tool metadata including name, description, etc.
        """
        self._tools[metadata.name] = tool_class
        self._metadata[metadata.name] = metadata
        logger.info(f"Registered MCP tool: {metadata.name} (category: {metadata.category})")
    
    def get_tool(self, name: str) -> Optional[Type["TableauMCPToolBase"]]:
        """
        Get a tool class by name.
        
        Args:
            name: Tool name
            
        Returns:
            Tool class or None if not found
        """
        return self._tools.get(name)
    
    def get_metadata(self, name: str) -> Optional[ToolMetadata]:
        """
        Get tool metadata by name.
        
        Args:
            name: Tool name
            
        Returns:
            ToolMetadata or None if not found
        """
        return self._metadata.get(name)
    
    def list_tools(self, category: str = None) -> Dict[str, ToolMetadata]:
        """
        List all registered tools, optionally filtered by category.
        
        Args:
            category: Optional category filter
            
        Returns:
            Dict mapping tool name to metadata
        """
        if category is None:
            return dict(self._metadata)
        return {
            name: meta 
            for name, meta in self._metadata.items() 
            if meta.category == category
        }
    
    def list_categories(self) -> list:
        """List all tool categories"""
        return list(set(meta.category for meta in self._metadata.values()))
    
    def create_tool(
        self,
        name: str,
        mcp_client,
        semantic_service=None,
    ) -> Optional["TableauMCPToolBase"]:
        """
        Create an instance of a tool.
        
        Args:
            name: Tool name
            mcp_client: TableauMCPClient instance
            semantic_service: Optional SemanticMaintenanceService instance
            
        Returns:
            Tool instance or None if tool not found
        """
        tool_class = self.get_tool(name)
        if tool_class is None:
            return None
        return tool_class(mcp_client=mcp_client, semantic_service=semantic_service)
    
    def get_tools_by_category(self, category: str) -> Dict[str, Type["TableauMCPToolBase"]]:
        """
        Get all tool classes in a category.
        
        Args:
            category: Category name
            
        Returns:
            Dict mapping tool name to tool class
        """
        return {
            name: tool_class
            for name, tool_class in self._tools.items()
            if self._metadata[name].category == category
        }


def register_tool(
    name: str,
    description: str,
    category: str,
    requires_confirmation: bool = True,
) -> Callable:
    """
    Decorator to register a tool class.
    
    Usage:
        @register_tool(
            name="update-field-caption",
            description="Update field caption in Tableau",
            category="semantic_writeback",
            requires_confirmation=True,
        )
        class UpdateFieldCaptionTool(TableauMCPToolBase):
            ...
    """
    def decorator(cls: Type[TableauMCPToolBase]) -> Type[TableauMCPToolBase]:
        metadata = ToolMetadata(
            name=name,
            description=description,
            requires_confirmation=requires_confirmation,
            category=category,
            parameters={},  # Populated by tool class
        )
        MCPToolRegistry().register(cls, metadata)
        return cls
    
    return decorator


# Import base class for decorators
from .base import TableauMCPToolBase
