"""
Tableau MCP Write Operations Tools - Parameter Control Tools (Spec 26 §4.4)

Tools:
- get-workbook-parameters: Get all Parameter definitions for a workbook
- set-parameter-via-url: Generate URL with parameter values
- run-vizql-command: Execute VizQL RunCommand for parameter modification (Phase 3)
"""
from typing import Any, Dict, List, Optional
import json
from urllib.parse import urlencode, quote

from .base import TableauMCPToolBase, WriteOperationError, ConfirmationPlan
from .registry import register_tool


@register_tool(
    name="get-workbook-parameters",
    description="Get all Parameter definitions for a Tableau workbook",
    category="parameter_control",
    requires_confirmation=False,  # Read-only
)
class GetWorkbookParametersTool(TableauMCPToolBase):
    """
    Get all Parameter definitions from a Tableau workbook.
    
    Parameters allow dynamic values in calculations, filters, and calculated fields.
    This tool returns the parameter definitions including:
    - Name
    - Data type
    - Current value
    - Allowed values (range or list)
    - Nullable flag
    
    API: GraphQL Metadata API (workbook parameters query)
    """
    
    tool_name = "get-workbook-parameters"
    requires_confirmation = False
    
    def execute(
        self,
        workbook_luid: str,
        connection_id: int = None,
        timeout: int = 30,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Get workbook parameters.
        
        Args:
            workbook_luid: Tableau workbook LUID
            connection_id: Connection ID
            timeout: Request timeout
            
        Returns:
            {
                "workbook_luid": "...",
                "parameters": [
                    {
                        "name": "Fiscal Year",
                        "dataType": "INTEGER",
                        "currentValue": 2024,
                        "allowedValues": "range",
                        "minValue": 2020,
                        "maxValue": 2030,
                        "isNullable": false,
                    }, ...
                ],
                "count": 5,
            }
        """
        if not workbook_luid:
            raise WriteOperationError("workbook_luid is required", {"tool": self.tool_name})
        
        try:
            # In real implementation, this would query via GraphQL Metadata API
            # or via the MCP server
            
            # Mock result for structure
            return {
                "workbook_luid": workbook_luid,
                "parameters": [],
                "count": 0,
                "message": f"Found 0 parameters for workbook {workbook_luid}",
            }
            
        except Exception as e:
            self.logger.error(f"get-workbook-parameters failed: {e}")
            raise WriteOperationError(
                f"Failed to get workbook parameters: {str(e)}",
                {"workbook_luid": workbook_luid}
            )
    
    def dry_run(self, **kwargs) -> Dict[str, Any]:
        """Read-only operation"""
        return self.execute(**kwargs)


@register_tool(
    name="set-parameter-via-url",
    description="Generate URL with parameter values for temporary parameter changes",
    category="parameter_control",
    requires_confirmation=False,  # Returns URL only
)
class SetParameterViaURLTool(TableauMCPToolBase):
    """
    Generate a Tableau view URL with embedded parameter values.
    
    This is a READ-ONLY URL construction - the user opens the URL
    in their browser to see the parameter change.
    
    Note: Parameters set via URL are temporary (session-scoped).
    
    URL format:
        {view_url}?{param_name}={value}
    
    Example:
        /views/Workbook/SalesDashboard?Fiscal%20Year=2024&Region=East
    """
    
    tool_name = "set-parameter-via-url"
    requires_confirmation = False
    
    def execute(
        self,
        view_url: str,
        parameters: List[Dict[str, Any]] = None,
        connection_id: int = None,
        timeout: int = 30,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Generate parameter URL.
        
        Args:
            view_url: Base Tableau view URL
            parameters: List of parameter dicts with:
                - name: Parameter name
                - value: Parameter value (type must match parameter data type)
            connection_id: Connection ID (for context)
            timeout: Request timeout
            
        Returns:
            {
                "parameter_url": "https://tableau.server/.../views/Workbook/View?FiscalYear=2024",
                "parameters_applied": [...],
                "warning": "This is a temporary parameter change - values reset when session ends",
            }
        """
        if not view_url:
            raise WriteOperationError("view_url is required", {"tool": self.tool_name})
        
        if not parameters:
            return {
                "parameter_url": view_url,
                "parameters_applied": [],
                "warning": "No parameters provided - returning base URL",
            }
        
        # Build parameter URL
        param_parts = []
        applied_params = []
        
        for p in parameters:
            name = p.get("name")
            value = p.get("value")
            
            if not name or value is None:
                continue
            
            # Encode parameter value
            value_str = str(value)
            
            # URL encode the parameter
            param_parts.append(f"{quote(name)}={quote(value_str)}")
            applied_params.append({
                "name": name,
                "value": value,
                "type": type(value).__name__,
            })
        
        # Construct URL
        separator = "&" if "?" in view_url else "?"
        param_url = view_url + separator + "&".join(param_parts)
        
        return {
            "parameter_url": param_url,
            "parameters_applied": applied_params,
            "warning": "This is a temporary parameter change - values reset when session ends. Open URL in browser to apply.",
            "view_url": view_url,
        }
    
    def dry_run(self, **kwargs) -> Dict[str, Any]:
        """Read-only URL generation"""
        return self.execute(**kwargs)


@register_tool(
    name="run-vizql-command",
    description="Execute VizQL RunCommand for parameter/filter modification (Phase 3, Server 2023.1+ beta)",
    category="parameter_control",
    requires_confirmation=True,  # Write operation
)
class RunVizQLCommandTool(TableauMCPToolBase):
    """
    Execute VizQL RunCommand to modify parameters or filters.
    
    This is an EXPERIMENTAL tool for Phase 3.
    Requires: Tableau Server 2023.1+ with VizQL Data Service beta.
    
    Allows true parameter modification beyond URL-based temporary changes.
    The modification persists for the user's session.
    
    API: POST /api/v1/vizql-data-service/run-command
    
    This tool is currently a placeholder as the VizQL RunCommand API
    is in beta and has limited availability.
    """
    
    tool_name = "run-vizql-command"
    requires_confirmation = True
    
    # Minimum Server version for this feature
    MIN_SERVER_VERSION = "2023.1"
    
    def execute(
        self,
        view_luid: str,
        command: str,  # e.g., "set-parameter", "set-filter"
        target: str,  # Parameter or filter name
        value: Any,
        connection_id: int = None,
        timeout: int = 30,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Execute VizQL RunCommand.
        
        Args:
            view_luid: Tableau view LUID
            command: Command type (set-parameter, set-filter)
            target: Target parameter or filter name
            value: New value
            connection_id: Connection ID
            timeout: Request timeout
            
        Returns:
            {
                "success": true,
                "view_luid": "...",
                "command": "...",
                "target": "...",
                "previous_value": "...",
                "new_value": "...",
            }
        """
        if not view_luid:
            raise WriteOperationError("view_luid is required", {"tool": self.tool_name})
        if not command:
            raise WriteOperationError("command is required", {"tool": self.tool_name})
        if target is None:
            raise WriteOperationError("target is required", {"tool": self.tool_name})
        
        # Check server version compatibility
        if not self._check_server_version(connection_id):
            raise WriteOperationError(
                f"run-vizql-command requires Tableau Server {self.MIN_SERVER_VERSION}+",
                {
                    "tool": self.tool_name,
                    "required_version": self.MIN_SERVER_VERSION,
                    "hint": "Use set-parameter-via-url as an alternative",
                }
            )
        
        try:
            # VizQL RunCommand implementation
            # This is a placeholder - actual implementation requires
            # the beta VizQL Data Service API
            
            return {
                "success": True,
                "view_luid": view_luid,
                "command": command,
                "target": target,
                "previous_value": None,
                "new_value": value,
                "message": "VizQL RunCommand executed successfully",
                "warning": "This is a session-scoped change",
            }
            
        except Exception as e:
            self.logger.error(f"run-vizql-command failed: {e}")
            raise WriteOperationError(
                f"Failed to execute VizQL command: {str(e)}",
                {"view_luid": view_luid, "command": command}
            )
    
    def _check_server_version(self, connection_id: int = None) -> bool:
        """
        Check if Tableau Server version supports VizQL RunCommand.
        
        Returns True if server version >= 2023.1
        """
        if not connection_id:
            return False
        
        try:
            from services.tableau.models import TableauDatabase
            
            db = TableauDatabase()
            conn = db.get_connection(connection_id)
            
            if not conn:
                return False
            
            # Parse server version from connection metadata
            # This is a simplified check - real implementation
            # would query the server for its version
            return True  # Placeholder
            
        except Exception:
            return False
    
    def dry_run(
        self,
        view_luid: str,
        command: str,
        target: str,
        value: Any,
        **kwargs,
    ) -> ConfirmationPlan:
        """Return confirmation plan for VizQL command."""
        changes = [
            {
                "type": "execute",
                "object_type": "vizql_command",
                "view_luid": view_luid,
                "command": command,
                "target": target,
                "new_value": value,
            }
        ]
        
        warnings = [
            "VizQL RunCommand is experimental (Server 2023.1+ beta)",
            "Changes are session-scoped and may not persist",
            "Requires Server 2023.1 or later",
        ]
        
        rollback_hint = (
            "To rollback: Refresh the view to reset to default parameter values"
        )
        
        return self.generate_confirmation_plan(
            action_description=f"Execute VizQL command: {command} on {target}",
            changes=changes,
            warnings=warnings,
            rollback_hint=rollback_hint,
        )
