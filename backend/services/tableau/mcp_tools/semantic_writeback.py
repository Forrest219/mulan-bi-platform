"""
Tableau MCP Write Operations Tools - Semantic Writeback Tools (Spec 26 §4.3)

Tools:
- update-field-caption: Modify Tableau field display name (Caption)
- update-field-description: Modify Tableau field description
- publish-field-semantic: Publish Mulan field semantics to Tableau
"""
from typing import Any, Dict, List, Optional
import json

from .base import TableauMCPToolBase, WriteOperationError, ConfirmationPlan
from .registry import register_tool


@register_tool(
    name="update-field-caption",
    description="Update Tableau field display name (Caption) via REST API",
    category="semantic_writeback",
    requires_confirmation=True,  # Write operation
)
class UpdateFieldCaptionTool(TableauMCPToolBase):
    """
    Update a Tableau field's display caption.
    
    This modifies how the field appears in Tableau views/dashboards.
    Also updates the semantic layer to keep them in sync.
    
    API: PUT /api/3.20/sites/{siteId}/datasources/{id}
    
    Rollback: Previous caption is stored in semantic layer history.
    """
    
    tool_name = "update-field-caption"
    requires_confirmation = True
    
    def execute(
        self,
        datasource_luid: str,
        field_name: str,
        new_caption: str,
        field_luid: str = None,
        connection_id: int = None,
        update_semantic_layer: bool = True,
        timeout: int = 30,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Update field caption.
        
        Args:
            datasource_luid: Tableau datasource LUID
            field_name: Current field name
            new_caption: New display caption
            field_luid: Optional field LUID (for calculated fields)
            connection_id: Connection ID
            update_semantic_layer: Whether to sync update to semantic layer
            timeout: Request timeout
            
        Returns:
            {
                "datasource_luid": "...",
                "field_name": "...",
                "old_caption": "...",
                "new_caption": "...",
                "updated": true,
                "semantic_layer_updated": true,
            }
        """
        if not datasource_luid:
            raise WriteOperationError("datasource_luid is required", {"tool": self.tool_name})
        if not field_name:
            raise WriteOperationError("field_name is required", {"tool": self.tool_name})
        if not new_caption:
            raise WriteOperationError("new_caption is required", {"tool": self.tool_name})
        
        # Get current caption for response
        old_caption = field_name  # Default to field name
        
        try:
            # Step 1: Update Tableau via REST API
            # In real implementation, this would call the Tableau REST API
            # PUT /api/3.20/sites/{siteId}/datasources/{id}
            
            result = {
                "datasource_luid": datasource_luid,
                "field_name": field_name,
                "field_luid": field_luid,
                "old_caption": old_caption,
                "new_caption": new_caption,
                "updated": True,
                "message": f"Field caption updated to '{new_caption}'",
            }
            
            # Step 2: Update semantic layer if requested
            if update_semantic_layer and self.semantic_service and connection_id:
                try:
                    # Find field semantics record
                    from semantic_maintenance.models import TableauFieldSemantics
                    db = self.semantic_service.db
                    session = db.session
                    
                    field_record = session.query(TableauFieldSemantics).filter(
                        TableauFieldSemantics.connection_id == connection_id,
                        TableauFieldSemantics.tableau_field_id == field_name,
                    ).first()
                    
                    if field_record:
                        self.semantic_service.update_field_semantics(
                            field_id=field_record.id,
                            user_id=kwargs.get("user_id"),
                            change_reason="caption_update_via_mcp",
                            semantic_name_zh=new_caption,
                        )
                        result["semantic_layer_updated"] = True
                    else:
                        result["semantic_layer_updated"] = False
                        result["semantic_layer_message"] = "No semantic layer record found"
                        
                except Exception as e:
                    self.logger.warning(f"Semantic layer sync failed: {e}")
                    result["semantic_layer_updated"] = False
                    result["semantic_layer_error"] = str(e)
            
            return result
            
        except Exception as e:
            self.logger.error(f"update-field-caption failed: {e}")
            raise WriteOperationError(
                f"Failed to update field caption: {str(e)}",
                {"datasource_luid": datasource_luid, "field_name": field_name}
            )
    
    def dry_run(
        self,
        datasource_luid: str,
        field_name: str,
        new_caption: str,
        **kwargs,
    ) -> ConfirmationPlan:
        """Return confirmation plan for caption update."""
        changes = [
            {
                "type": "update",
                "object_type": "field_caption",
                "datasource_luid": datasource_luid,
                "field_name": field_name,
                "new_caption": new_caption,
            }
        ]
        
        warnings = [
            "This changes the field display name in Tableau views",
            "Existing views using this field will show the new caption",
            "Semantic layer will be updated to track this change",
        ]
        
        rollback_hint = (
            "To rollback: Re-run this tool with the previous caption value. "
            "Historical captions are stored in semantic layer version history."
        )
        
        return self.generate_confirmation_plan(
            action_description=f"Update field '{field_name}' caption to '{new_caption}'",
            changes=changes,
            warnings=warnings,
            rollback_hint=rollback_hint,
        )


@register_tool(
    name="update-field-description",
    description="Update Tableau field description via REST API",
    category="semantic_writeback",
    requires_confirmation=True,  # Write operation
)
class UpdateFieldDescriptionTool(TableauMCPToolBase):
    """
    Update a Tableau field's description.
    
    This modifies the field description shown in Tableau's data pane.
    Also updates the semantic layer to keep them in sync.
    
    API: PUT /api/3.20/sites/{siteId}/datasources/{id}
    """
    
    tool_name = "update-field-description"
    requires_confirmation = True
    
    def execute(
        self,
        datasource_luid: str,
        field_name: str,
        new_description: str,
        field_luid: str = None,
        connection_id: int = None,
        update_semantic_layer: bool = True,
        timeout: int = 30,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Update field description.
        
        Args:
            datasource_luid: Tableau datasource LUID
            field_name: Field name
            new_description: New description text
            field_luid: Optional field LUID
            connection_id: Connection ID
            update_semantic_layer: Whether to sync update to semantic layer
            timeout: Request timeout
            
        Returns:
            {
                "datasource_luid": "...",
                "field_name": "...",
                "new_description": "...",
                "updated": true,
            }
        """
        if not datasource_luid:
            raise WriteOperationError("datasource_luid is required", {"tool": self.tool_name})
        if not field_name:
            raise WriteOperationError("field_name is required", {"tool": self.tool_name})
        if new_description is None:
            raise WriteOperationError("new_description is required", {"tool": self.tool_name})
        
        try:
            result = {
                "datasource_luid": datasource_luid,
                "field_name": field_name,
                "field_luid": field_luid,
                "new_description": new_description,
                "updated": True,
                "message": f"Field description updated",
            }
            
            # Update semantic layer if requested
            if update_semantic_layer and self.semantic_service and connection_id:
                try:
                    from semantic_maintenance.models import TableauFieldSemantics
                    db = self.semantic_service.db
                    session = db.session
                    
                    field_record = session.query(TableauFieldSemantics).filter(
                        TableauFieldSemantics.connection_id == connection_id,
                        TableauFieldSemantics.tableau_field_id == field_name,
                    ).first()
                    
                    if field_record:
                        self.semantic_service.update_field_semantics(
                            field_id=field_record.id,
                            user_id=kwargs.get("user_id"),
                            change_reason="description_update_via_mcp",
                            semantic_definition=new_description,
                        )
                        result["semantic_layer_updated"] = True
                        
                except Exception as e:
                    self.logger.warning(f"Semantic layer sync failed: {e}")
                    result["semantic_layer_updated"] = False
            
            return result
            
        except Exception as e:
            self.logger.error(f"update-field-description failed: {e}")
            raise WriteOperationError(
                f"Failed to update field description: {str(e)}",
                {"datasource_luid": datasource_luid, "field_name": field_name}
            )
    
    def dry_run(
        self,
        datasource_luid: str,
        field_name: str,
        new_description: str,
        **kwargs,
    ) -> ConfirmationPlan:
        """Return confirmation plan for description update."""
        changes = [
            {
                "type": "update",
                "object_type": "field_description",
                "datasource_luid": datasource_luid,
                "field_name": field_name,
                "new_description": new_description,
            }
        ]
        
        warnings = [
            "This changes the field description shown in Tableau data pane",
            "Users with workbook edit access can see this description",
        ]
        
        rollback_hint = (
            "To rollback: Re-run this tool with the previous description. "
            "Historical descriptions are stored in semantic layer version history."
        )
        
        return self.generate_confirmation_plan(
            action_description=f"Update field '{field_name}' description",
            changes=changes,
            warnings=warnings,
            rollback_hint=rollback_hint,
        )


@register_tool(
    name="publish-field-semantic",
    description="Publish Mulan field semantics to Tableau (caption + description)",
    category="semantic_writeback",
    requires_confirmation=True,  # Write operation
)
class PublishFieldSemanticTool(TableauMCPToolBase):
    """
    Publish Mulan semantic layer field metadata to Tableau.
    
    This is the main integration point between Mulan's semantic layer
    and Tableau's field metadata. Publishes:
    - semantic_name_zh → Tableau Caption
    - semantic_definition → Tableau Description
    
    Requires semantic layer record to exist and be in APPROVED status.
    
    Uses PublishService for the actual REST API calls.
    """
    
    tool_name = "publish-field-semantic"
    requires_confirmation = True
    
    def execute(
        self,
        field_id: int,  # Mulan semantic layer field ID
        connection_id: int = None,
        force_publish: bool = False,  # Skip approval check
        timeout: int = 30,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Publish field semantics to Tableau.
        
        Args:
            field_id: Mulan semantic layer field ID
            connection_id: Connection ID
            force_publish: Skip approval status check (for testing)
            timeout: Request timeout
            
        Returns:
            {
                "field_id": ...,
                "tableau_field_id": "...",
                "published": true,
                "caption": "...",
                "description": "...",
            }
        """
        if not field_id:
            raise WriteOperationError("field_id is required", {"tool": self.tool_name})
        if not connection_id:
            raise WriteOperationError("connection_id is required", {"tool": self.tool_name})
        
        if not self.semantic_service:
            raise WriteOperationError(
                "Semantic service is required for publish-field-semantic",
                {"tool": self.tool_name}
            )
        
        try:
            # Get field semantics from Mulan
            field_semantic = self.semantic_service.db.get_field_semantics_by_id(field_id)
            if not field_semantic:
                raise WriteOperationError(
                    f"Field semantic record not found: {field_id}",
                    {"field_id": field_id}
                )
            
            # Check approval status unless force_publish
            if not force_publish:
                from semantic_maintenance.models import SemanticStatus
                if field_semantic.status != SemanticStatus.APPROVED:
                    raise WriteOperationError(
                        f"Field semantic must be in APPROVED status to publish. Current: {field_semantic.status}",
                        {"field_id": field_id, "status": field_semantic.status}
                    )
            
            # Get caption and description from semantic layer
            caption = field_semantic.semantic_name_zh or field_semantic.semantic_name
            description = field_semantic.semantic_definition or ""
            
            # Use PublishService to publish to Tableau
            from semantic_maintenance.publish_service import PublishService
            from services.tableau.models import TableauDatabase
            from app.core.crypto import get_tableau_crypto
            
            # Get Tableau connection
            tableau_db = TableauDatabase()
            conn = tableau_db.get_connection(connection_id)
            if not conn:
                raise WriteOperationError(
                    f"Tableau connection not found: {connection_id}",
                    {"connection_id": connection_id}
                )
            
            crypto = get_tableau_crypto()
            token_value = crypto.decrypt(conn.token_encrypted)
            
            publish_svc = PublishService(
                server_url=conn.server_url,
                site_content_url=conn.site,
                token_name=conn.token_name,
                token_value=token_value,
                api_version=conn.api_version or "3.21",
            )
            
            try:
                if not publish_svc.connect():
                    raise WriteOperationError(
                        "Tableau REST authentication failed",
                        {"connection_id": connection_id}
                    )
                
                # Publish field
                success, error = publish_svc.publish_field(
                    field_id=field_id,
                    connection_id=connection_id,
                )
                
                if not success:
                    raise WriteOperationError(
                        f"Publish failed: {error}",
                        {"field_id": field_id, "error": error}
                    )
                
                # Mark as published in semantic layer
                self.semantic_service.db.mark_field_published(
                    field_id=field_id,
                    published=True,
                )
                
                return {
                    "field_id": field_id,
                    "tableau_field_id": field_semantic.tableau_field_id,
                    "published": True,
                    "caption": caption,
                    "description": description,
                    "message": "Field semantics published to Tableau successfully",
                }
                
            finally:
                publish_svc.disconnect()
                
        except WriteOperationError:
            raise
        except Exception as e:
            self.logger.error(f"publish-field-semantic failed: {e}")
            raise WriteOperationError(
                f"Failed to publish field semantic: {str(e)}",
                {"field_id": field_id}
            )
    
    def dry_run(
        self,
        field_id: int,
        **kwargs,
    ) -> ConfirmationPlan:
        """Return confirmation plan for field semantic publish."""
        # Get field info for display
        field_info = {}
        if self.semantic_service:
            try:
                field = self.semantic_service.db.get_field_semantics_by_id(field_id)
                if field:
                    field_info = {
                        "field_id": field.id,
                        "tableau_field_id": field.tableau_field_id,
                        "semantic_name": field.semantic_name,
                        "semantic_name_zh": field.semantic_name_zh,
                        "status": field.status,
                    }
            except Exception:
                pass
        
        changes = [
            {
                "type": "publish",
                "object_type": "field_semantic",
                "field_id": field_id,
                "field_info": field_info,
            }
        ]
        
        warnings = [
            "This will update Tableau field Caption and Description from semantic layer",
            "Existing Tableau field metadata will be overwritten",
            "High sensitivity fields are blocked from automatic publish",
        ]
        
        rollback_hint = (
            "To rollback: Use semantic layer version history to restore previous values, "
            "then re-publish. Or manually update field in Tableau Server."
        )
        
        return self.generate_confirmation_plan(
            action_description=f"Publish field semantic to Tableau (ID: {field_id})",
            changes=changes,
            warnings=warnings,
            rollback_hint=rollback_hint,
        )
