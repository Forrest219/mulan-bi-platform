"""
Tableau MCP Write Operations Tools - Field Resolution Tools (Spec 26 §4.1)

Tools:
- get-field-schema: Get complete field schema (role/dataType/formula)
- resolve-field-name: Fuzzy field name → precise field match via semantic layer
- get-datasource-fields-summary: Get all fields summary for LLM field selection
"""
from typing import Any, Dict, List, Optional
import json

from .base import TableauMCPToolBase, FieldResolutionError
from .registry import register_tool, MCPToolRegistry, get_tool_registry


@register_tool(
    name="get-field-schema",
    description="Get complete field schema including role, dataType, formula, and aggregation",
    category="field_resolution",
    requires_confirmation=False,  # Read-only operation
)
class GetFieldSchemaTool(TableauMCPToolBase):
    """
    Get complete field schema for a datasource field.
    
    Returns extended metadata including:
    - name, fullyQualifiedName
    - dataType (STRING/INTEGER/REAL/BOOLEAN/DATE)
    - role (DIMENSION/MEASURE)
    - dataCategory (NOMINAL/ORDINAL/QUANTITATIVE)
    - isHidden
    - formula (for calculated fields)
    - defaultAggregation (SUM/AVG/COUNT for measures)
    """
    
    tool_name = "get-field-schema"
    requires_confirmation = False
    
    def execute(
        self,
        datasource_luid: str,
        field_name: str = None,
        field_luid: str = None,
        connection_id: int = None,
        timeout: int = 30,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Get field schema.
        
        Args:
            datasource_luid: Tableau datasource LUID
            field_name: Field name (mutually exclusive with field_luid)
            field_luid: Field LUID (mutually exclusive with field_name)
            connection_id: Connection ID for routing
            timeout: Request timeout
            
        Returns:
            Field schema dict with extended metadata
        """
        if not field_name and not field_luid:
            raise FieldResolutionError(
                "Either field_name or field_luid must be provided",
                {"datasource_luid": datasource_luid}
            )
        
        # If field_name provided, first resolve to LUID
        if field_name and not field_luid:
            resolution = self.resolve_field_name(
                field_name=field_name,
                datasource_luid=datasource_luid,
                connection_id=connection_id,
            )
            candidates = resolution.get("candidates", [])
            if not candidates:
                raise FieldResolutionError(
                    f"Could not resolve field name: {field_name}",
                    {"datasource_luid": datasource_luid, "field_name": field_name}
                )
            # Use the highest confidence match
            field_luid = candidates[0]["tableau_field_id"]
        
        # Build GraphQL query for extended field schema
        query = {
            "query": """
                query GetFieldSchema($datasourceLuid: String!) {
                    publishedDatasourcesConnection(filter: {luid: $datasourceLuid}) {
                        nodes {
                            luid
                            name
                            fields {
                                name
                                fullyQualifiedName
                                description
                                dataType
                                role
                                dataCategory
                                isHidden
                                formula
                                defaultAggregation
                            }
                        }
                    }
                }
            """,
            "variables": {"datasourceLuid": datasource_luid},
        }
        
        # Execute via MCP client
        try:
            result = self.mcp_client.get_datasource_metadata(
                datasource_luid=datasource_luid,
                timeout=timeout,
            )
            
            # Find the matching field
            fields = result.get("fields", [])
            for field in fields:
                # Match by name or LUID
                if field.get("fieldName") == field_luid or field.get("fieldName") == field_name:
                    return {
                        "datasource_luid": datasource_luid,
                        "field": {
                            "name": field.get("fieldName"),
                            "fullyQualifiedName": field.get("fullyQualifiedName"),
                            "dataType": field.get("dataType"),
                            "role": field.get("role"),
                            "dataCategory": field.get("dataCategory"),
                            "isHidden": field.get("isHidden"),
                            "formula": field.get("formula"),
                            "defaultAggregation": field.get("aggregation"),
                            "description": field.get("description"),
                        },
                        "resolved_via": "semantic_layer" if field_name else "direct",
                    }
            
            raise FieldResolutionError(
                f"Field not found: {field_luid or field_name}",
                {"datasource_luid": datasource_luid, "field_id": field_luid or field_name}
            )
            
        except Exception as e:
            self.logger.error(f"get-field-schema failed: {e}")
            raise FieldResolutionError(
                f"Failed to get field schema: {str(e)}",
                {"datasource_luid": datasource_luid}
            )
    
    def dry_run(self, **kwargs) -> Dict[str, Any]:
        """Read-only, no confirmation needed"""
        return self.execute(**kwargs)


@register_tool(
    name="resolve-field-name",
    description="Resolve a fuzzy field name to precise field matches using semantic layer vector search",
    category="field_resolution",
    requires_confirmation=False,  # Read-only operation
)
class ResolveFieldNameTool(TableauMCPToolBase):
    """
    Resolve fuzzy field names to precise field matches.
    
    Uses semantic layer embedding similarity to find candidate fields.
    Supports:
    - Exact match on semantic_name
    - Exact match on synonyms_json
    - Embedding cosine similarity > 0.85
    - Fuzzy string match > 80%
    
    Returns ranked candidates with confidence scores.
    """
    
    tool_name = "resolve-field-name"
    requires_confirmation = False
    
    def execute(
        self,
        field_name: str,
        datasource_luid: str = None,
        connection_id: int = None,
        required_role: str = None,  # DIMENSION or MEASURE
        max_candidates: int = 5,
        timeout: int = 30,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Resolve field name to candidates.
        
        Args:
            field_name: Fuzzy field name (e.g., "region", "the dimension called 'region'")
            datasource_luid: Optional to scope search to a specific datasource
            connection_id: Connection ID
            required_role: Optional filter for DIMENSION or MEASURE
            max_candidates: Maximum number of candidates to return
            timeout: Request timeout
            
        Returns:
            {
                "candidates": [
                    {
                        "tableau_field_id": "...",
                        "datasource_luid": "...",
                        "semantic_name": "...",
                        "semantic_name_zh": "...",
                        "role": "DIMENSION",
                        "data_type": "STRING",
                        "confidence": 0.95,
                    }, ...
                ],
                "confidence": 0.95,
                "method": "semantic_layer|exact_match|fuzzy_match",
            }
        """
        if not field_name:
            raise FieldResolutionError("field_name is required", {})
        
        if not connection_id:
            raise FieldResolutionError("connection_id is required", {})
        
        # Use semantic layer to resolve
        resolution = self.resolve_field_name(
            field_name=field_name,
            datasource_luid=datasource_luid or "",
            connection_id=connection_id,
            required_role=required_role,
        )
        
        candidates = resolution.get("candidates", [])[:max_candidates]
        confidence = resolution.get("confidence", 0.0)
        method = resolution.get("method", "unknown")
        
        # If no semantic layer matches, try direct MCP query
        if not candidates and datasource_luid:
            candidates = self._direct_search(
                datasource_luid=datasource_luid,
                search_term=field_name,
                required_role=required_role,
            )
            if candidates:
                method = "direct_search"
                confidence = candidates[0].get("confidence", 0.7)
        
        return {
            "candidates": candidates,
            "confidence": confidence,
            "method": method,
            "search_term": field_name,
            "required_role": required_role,
        }
    
    def _direct_search(
        self,
        datasource_luid: str,
        search_term: str,
        required_role: str = None,
    ) -> List[Dict[str, Any]]:
        """Direct search when semantic layer has no matches"""
        try:
            result = self.mcp_client.get_datasource_metadata(
                datasource_luid=datasource_luid,
                timeout=30,
            )
            
            candidates = []
            search_lower = search_term.lower()
            
            for field in result.get("fields", []):
                name = field.get("fieldName", "")
                caption = field.get("fieldCaption", name)
                
                # Simple string matching
                if search_lower in name.lower() or search_lower in caption.lower():
                    role = field.get("role", "")
                    if required_role and role.upper() != required_role.upper():
                        continue
                    
                    candidates.append({
                        "tableau_field_id": name,
                        "datasource_luid": datasource_luid,
                        "semantic_name": caption,
                        "semantic_name_zh": "",
                        "role": role,
                        "data_type": field.get("dataType"),
                        "confidence": 0.6,  # Lower confidence for direct search
                    })
            
            return candidates
            
        except Exception as e:
            self.logger.warning(f"Direct search failed: {e}")
            return []
    
    def dry_run(self, **kwargs) -> Dict[str, Any]:
        """Read-only, no confirmation needed"""
        return self.execute(**kwargs)


@register_tool(
    name="get-datasource-fields-summary",
    description="Get all fields summary for a datasource (name + role + dataType) for LLM field selection",
    category="field_resolution",
    requires_confirmation=False,  # Read-only operation
)
class GetDatasourceFieldsSummaryTool(TableauMCPToolBase):
    """
    Get summary of all fields in a datasource.
    
    Returns lightweight field list suitable for LLM prompt context:
    - field name
    - role (DIMENSION/MEASURE)
    - data type
    - isHidden flag
    
    Does NOT return full schema (use get-field-schema for that).
    """
    
    tool_name = "get-datasource-fields-summary"
    requires_confirmation = False
    
    def execute(
        self,
        datasource_luid: str,
        connection_id: int = None,
        include_hidden: bool = False,
        timeout: int = 30,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Get datasource fields summary.
        
        Args:
            datasource_luid: Tableau datasource LUID
            connection_id: Connection ID
            include_hidden: Whether to include hidden fields
            timeout: Request timeout
            
        Returns:
            {
                "datasource_luid": "...",
                "fields": [
                    {
                        "name": "Region",
                        "role": "DIMENSION",
                        "dataType": "STRING",
                        "isHidden": false,
                    }, ...
                ],
                "total_count": 50,
                "dimension_count": 30,
                "measure_count": 20,
            }
        """
        try:
            result = self.mcp_client.get_datasource_metadata(
                datasource_luid=datasource_luid,
                timeout=timeout,
            )
            
            fields = result.get("fields", [])
            
            # Filter and transform
            summary_fields = []
            dimension_count = 0
            measure_count = 0
            
            for field in fields:
                is_hidden = field.get("isHidden", False)
                if is_hidden and not include_hidden:
                    continue
                
                role = field.get("role", "")
                if role.upper() == "DIMENSION":
                    dimension_count += 1
                elif role.upper() == "MEASURE":
                    measure_count += 1
                
                summary_fields.append({
                    "name": field.get("fieldName"),
                    "role": role,
                    "dataType": field.get("dataType"),
                    "isHidden": is_hidden,
                })
            
            return {
                "datasource_luid": datasource_luid,
                "fields": summary_fields,
                "total_count": len(summary_fields),
                "dimension_count": dimension_count,
                "measure_count": measure_count,
            }
            
        except Exception as e:
            self.logger.error(f"get-datasource-fields-summary failed: {e}")
            raise FieldResolutionError(
                f"Failed to get fields summary: {str(e)}",
                {"datasource_luid": datasource_luid}
            )
    
    def dry_run(self, **kwargs) -> Dict[str, Any]:
        """Read-only, no confirmation needed"""
        return self.execute(**kwargs)
