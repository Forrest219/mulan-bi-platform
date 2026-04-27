"""
Tableau MCP Write Operations Tools - Dispatcher (Spec 26)

Provides the MCP dispatcher that routes tool calls to the appropriate tool handlers.
Coordinates between the MCP client, semantic layer, and tool registry.
"""
import logging
from typing import Any, Dict, List, Optional

from .registry import get_tool_registry, MCPToolRegistry
from .base import TableauMCPToolBase, ToolError, ConfirmationPlan

logger = logging.getLogger(__name__)


class MCPToolDispatcher:
    """
    Dispatcher for MCP write operation tools.
    
    Routes tool calls to the appropriate tool handlers based on tool name.
    Provides:
    - Tool discovery
    - Tool execution with proper error handling
    - Confirmation plan generation for write operations
    - Rollback guidance
    """
    
    def __init__(
        self,
        mcp_client=None,
        semantic_service=None,
    ):
        """
        Initialize the dispatcher.
        
        Args:
            mcp_client: TableauMCPClient instance
            semantic_service: SemanticMaintenanceService instance
        """
        self.mcp_client = mcp_client
        self.semantic_service = semantic_service
        self.registry = get_tool_registry()
        
        # Lazy import to avoid circular dependency
        self._tools = {}
        self._initialized = False
    
    def _ensure_initialized(self):
        """Ensure tools are registered"""
        if self._initialized:
            return
        
        # Import all tool modules to trigger registration
        try:
            from . import field_resolution
            from . import view_control
            from . import semantic_writeback
            from . import parameter_control
        except ImportError as e:
            logger.warning(f"Failed to import some tool modules: {e}")
        
        self._initialized = True
    
    def list_tools(self, category: str = None) -> Dict[str, Dict[str, Any]]:
        """
        List all available tools.
        
        Args:
            category: Optional category filter
            
        Returns:
            Dict mapping tool name to tool metadata
        """
        self._ensure_initialized()
        
        result = {}
        for name, metadata in self.registry.list_tools(category=category).items():
            result[name] = {
                "name": metadata.name,
                "description": metadata.description,
                "category": metadata.category,
                "requires_confirmation": metadata.requires_confirmation,
            }
        return result
    
    def get_tool_info(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific tool.
        
        Args:
            tool_name: Tool name
            
        Returns:
            Tool metadata or None if not found
        """
        self._ensure_initialized()
        
        metadata = self.registry.get_metadata(tool_name)
        if not metadata:
            return None
        
        return {
            "name": metadata.name,
            "description": metadata.description,
            "category": metadata.category,
            "requires_confirmation": metadata.requires_confirmation,
        }
    
    def prepare_tool(
        self,
        tool_name: str,
        dry_run: bool = True,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        """
        Prepare a tool execution (dry run mode).
        
        Returns the confirmation plan for write operations without executing.
        
        Args:
            tool_name: Tool name
            dry_run: If True, return confirmation plan without executing
            **kwargs: Tool arguments
            
        Returns:
            ConfirmationPlan dict or None if tool not found
        """
        self._ensure_initialized()
        
        tool = self.registry.create_tool(
            name=tool_name,
            mcp_client=self.mcp_client,
            semantic_service=self.semantic_service,
        )
        
        if not tool:
            raise ToolError(
                code="TOOL_NOT_FOUND",
                message=f"Tool not found: {tool_name}",
                details={"tool_name": tool_name}
            )
        
        metadata = self.registry.get_metadata(tool_name)
        
        # Read-only tools and URL generators don't need confirmation
        if not metadata or not metadata.requires_confirmation:
            return tool.execute(**kwargs)
        
        # Return confirmation plan
        if dry_run:
            return tool.dry_run(**kwargs)
        
        return None
    
    def execute_tool(
        self,
        tool_name: str,
        confirmation_received: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Execute a tool with optional confirmation.
        
        Args:
            tool_name: Tool name
            confirmation_received: If True, user has confirmed the operation
            **kwargs: Tool arguments
            
        Returns:
            Tool execution result
            
        Raises:
            ToolError: If tool not found or confirmation required but not received
        """
        self._ensure_initialized()
        
        tool = self.registry.create_tool(
            name=tool_name,
            mcp_client=self.mcp_client,
            semantic_service=self.semantic_service,
        )
        
        if not tool:
            raise ToolError(
                code="TOOL_NOT_FOUND",
                message=f"Tool not found: {tool_name}",
                details={"tool_name": tool_name}
            )
        
        metadata = self.registry.get_metadata(tool_name)
        
        # Check if confirmation is required
        if metadata and metadata.requires_confirmation and not confirmation_received:
            # Return the confirmation plan instead of executing
            plan = tool.dry_run(**kwargs)
            if isinstance(plan, ConfirmationPlan):
                return {
                    "requires_confirmation": True,
                    "confirmation_plan": plan.to_dict(),
                }
            return {
                "requires_confirmation": True,
                "confirmation_plan": plan,
            }
        
        # Execute the tool
        try:
            result = tool.execute(**kwargs)
            return result
        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name}: {e}")
            raise
    
    def get_confirmation_needed(
        self,
        tool_name: str,
        **kwargs,
    ) -> Optional[ConfirmationPlan]:
        """
        Get the confirmation plan for a tool without executing.
        
        Args:
            tool_name: Tool name
            **kwargs: Tool arguments
            
        Returns:
            ConfirmationPlan or None if confirmation not needed
        """
        self._ensure_initialized()
        
        tool = self.registry.create_tool(
            name=tool_name,
            mcp_client=self.mcp_client,
            semantic_service=self.semantic_service,
        )
        
        if not tool:
            return None
        
        metadata = self.registry.get_metadata(tool_name)
        
        if not metadata or not metadata.requires_confirmation:
            return None
        
        return tool.dry_run(**kwargs)


def get_dispatcher(
    mcp_client=None,
    semantic_service=None,
) -> MCPToolDispatcher:
    """
    Get an MCP tool dispatcher instance.
    
    Args:
        mcp_client: TableauMCPClient instance
        semantic_service: SemanticMaintenanceService instance
        
    Returns:
        MCPToolDispatcher instance
    """
    return MCPToolDispatcher(
        mcp_client=mcp_client,
        semantic_service=semantic_service,
    )
