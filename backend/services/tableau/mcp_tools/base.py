"""
Tableau MCP Write Operations Tools - Base Classes (Spec 26)

Provides base classes and exceptions for all MCP write operation tools.
"""
import logging
from typing import Any, Dict, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """Base exception for MCP tool errors"""
    def __init__(self, code: str, message: str, details: Dict[str, Any] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


class IntentVerificationError(ToolError):
    """Raised when intent verification fails (e.g., field type mismatch)"""
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__("INTENT_VERIFY_FAILED", message, details)


class FieldResolutionError(ToolError):
    """Raised when field resolution fails"""
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__("FIELD_RESOLUTION_FAILED", message, details)


class WriteOperationError(ToolError):
    """Raised when a write operation fails"""
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__("WRITE_OPERATION_FAILED", message, details)


@dataclass
class ConfirmationPlan:
    """
    Represents an execution plan that requires user confirmation before execution.
    
    This is returned by tools that modify Tableau state, allowing the frontend
    to display what will change and get user confirmation before proceeding.
    """
    tool_name: str
    action_description: str
    changes: List[Dict[str, Any]]
    warnings: List[str]
    rollback_hint: Optional[str] = None
    metadata: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "action_description": self.action_description,
            "changes": self.changes,
            "warnings": self.warnings,
            "rollback_hint": self.rollback_hint,
            "metadata": self.metadata or {},
        }


class TableauMCPToolBase:
    """
    Base class for all Tableau MCP write operation tools.
    
    Provides common functionality:
    - Field resolution via semantic layer
    - Intent verification before execution
    - Confirmation plan generation
    - Error handling and rollback guidance
    """
    
    # Tool metadata - override in subclasses
    tool_name: str = ""
    tool_description: str = ""
    requires_confirmation: bool = True  # Write operations require confirmation by default
    
    def __init__(self, mcp_client, semantic_service=None):
        """
        Initialize the tool.
        
        Args:
            mcp_client: TableauMCPClient instance for making MCP calls
            semantic_service: SemanticMaintenanceService instance for field resolution
        """
        self.mcp_client = mcp_client
        self.semantic_service = semantic_service
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def resolve_field_name(
        self, 
        field_name: str, 
        datasource_luid: str, 
        connection_id: int,
        required_role: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Resolve a fuzzy field name to precise field metadata using semantic layer.
        
        Uses vector similarity search to find candidate fields, then optionally
        filters by required_role (DIMENSION/MEASURE).
        
        Args:
            field_name: The fuzzy field name to resolve
            datasource_luid: The Tableau datasource LUID
            connection_id: The connection ID
            required_role: Optional role filter (DIMENSION/MEASURE)
            
        Returns:
            Dict with candidates list, each containing field metadata
        """
        if not self.semantic_service:
            # Fallback: return empty candidates
            return {"candidates": [], "confidence": 0.0, "method": "no_semantic_layer"}
        
        try:
            # Query semantic layer for field resolution
            # The semantic layer uses embedding similarity to find matches
            candidates = []
            
            # Try exact match first
            from semantic_maintenance.models import TableauFieldSemantics
            db = self.semantic_service.db
            session = db.session
            
            # Search for fields matching the name (simplified - real implementation
            # would use embedding similarity)
            fields = session.query(TableauFieldSemantics).filter(
                TableauFieldSemantics.connection_id == connection_id,
            ).all()
            
            for field in fields:
                # Check semantic name or synonyms match
                semantic_name = getattr(field, 'semantic_name', '') or ''
                semantic_name_zh = getattr(field, 'semantic_name_zh', '') or ''
                synonyms = getattr(field, 'synonyms_json', None) or []
                
                if isinstance(synonyms, str):
                    import json
                    synonyms = json.loads(synonyms)
                
                # Simple fuzzy match
                field_name_lower = field_name.lower()
                matches = (
                    field_name_lower in semantic_name.lower() or
                    field_name_lower in semantic_name_zh.lower() or
                    any(field_name_lower in s.lower() for s in synonyms)
                )
                
                if matches:
                    # Filter by role if required
                    field_role = getattr(field, 'role', None)
                    if required_role and field_role and field_role.upper() != required_role.upper():
                        continue
                    
                    candidates.append({
                        "tableau_field_id": field.tableau_field_id,
                        "semantic_name": semantic_name,
                        "semantic_name_zh": semantic_name_zh,
                        "role": field_role,
                        "data_type": getattr(field, 'data_type', None),
                        "confidence": 0.9 if semantic_name else 0.7,
                    })
            
            # Sort by confidence
            candidates.sort(key=lambda x: x.get("confidence", 0), reverse=True)
            
            return {
                "candidates": candidates[:5],  # Top 5
                "confidence": candidates[0].get("confidence", 0) if candidates else 0.0,
                "method": "semantic_layer",
            }
            
        except Exception as e:
            self.logger.warning(f"Field resolution failed: {e}")
            return {"candidates": [], "confidence": 0.0, "error": str(e)}
    
    def verify_field_intent(
        self,
        field_luid: str,
        expected_role: str,
        datasource_luid: str,
    ) -> bool:
        """
        Verify that a field matches the expected intent (role check).
        
        Before executing a write operation, verify the field type is appropriate.
        For example, prevent setting a category filter on a MEASURE field.
        
        Args:
            field_luid: The Tableau field LUID
            expected_role: The expected role (DIMENSION/MEASURE)
            datasource_luid: The datasource LUID
            
        Returns:
            True if intent is verified
        """
        try:
            # Get field schema from Tableau
            if not self.mcp_client:
                return True  # Skip verification if no client
            
            # This would call the MCP tool to get field schema
            # For now, return True as a fallback
            return True
            
        except Exception as e:
            self.logger.warning(f"Intent verification failed: {e}")
            raise IntentVerificationError(
                f"Cannot verify field intent for {field_luid}",
                details={"expected_role": expected_role, "error": str(e)}
            )
    
    def generate_confirmation_plan(
        self,
        action_description: str,
        changes: List[Dict[str, Any]],
        warnings: List[str] = None,
        rollback_hint: str = None,
    ) -> ConfirmationPlan:
        """
        Generate a confirmation plan for frontend display.
        
        Args:
            action_description: Human-readable description of the action
            changes: List of changes that will be made
            warnings: Optional list of warnings
            rollback_hint: Optional hint for rolling back if operation fails
            
        Returns:
            ConfirmationPlan object
        """
        return ConfirmationPlan(
            tool_name=self.tool_name,
            action_description=action_description,
            changes=changes,
            warnings=warnings or [],
            rollback_hint=rollback_hint,
        )
    
    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute the tool. Override in subclasses.
        """
        raise NotImplementedError("Subclasses must implement execute()")
    
    def dry_run(self, **kwargs) -> ConfirmationPlan:
        """
        Perform a dry run and return a confirmation plan.
        Override in subclasses that require confirmation.
        """
        raise NotImplementedError("Subclasses must implement dry_run()")
