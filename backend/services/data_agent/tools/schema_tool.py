"""
SchemaTool — Phase 2: Tableau schema/资产结构查询

Spec: docs/specs/36-data-agent-architecture-spec.md §3.1 ToolRegistry + §9.2 downstream
"""

import logging
import time
from typing import Any, Dict, List, Optional

from app.core.crypto import get_tableau_crypto
from app.core.database import SessionLocal
from services.data_agent.tool_base import BaseTool, ToolContext, ToolMetadata, ToolResult
from services.data_agent.tools.query_tool import _get_mcp_queryable_field_candidates
from services.tableau.models import TableauAsset, TableauConnection, TableauDatabase, TableauDatasourceField
from services.tableau.sync_service import TableauRestSyncService

logger = logging.getLogger(__name__)


class SchemaTool(BaseTool):
    """
    Phase 2 Data Agent Tool: Schema / Table Structure Query.

    Queries Tableau asset structures and field metadata.
    Used when user asks "what tables exist", "what fields does X table have",
    "show me the schema/data structure".

    Tool name: "schema"
    """

    name = "schema"
    description = "查询数据源的表结构、字段信息。当用户询问「有哪些表」「某表的字段是什么」「数据结构」时使用。"
    metadata = ToolMetadata(
        category="query",
        version="1.0.0",
        dependencies=["requires_tableau"],
        tags=["schema", "metadata", "table-structure"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "integer",
                "description": "数据源连接 ID（可选，默认使用 context.connection_id）",
            },
            "table_name": {
                "type": "string",
                "description": "指定表名，查询该表的字段结构（可选，不填则返回所有表）",
            },
            "limit": {
                "type": "integer",
                "description": "返回的表数量上限（默认 100）",
                "default": 100,
            },
            "include_all_asset_types": {
                "type": "boolean",
                "description": "是否返回 view/workbook 等非 Published Datasource 资产；默认 false",
                "default": False,
            },
        },
        "required": [],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """
        Execute a Tableau schema query.

        Pipeline:
        1. Resolve connection_id (param overrides context)
        2. Fetch active TableauConnection
        3. Return Tableau asset/field metadata

        Args:
            params: {"connection_id"?: int, "table_name"?: str, "limit"?: int}
            context: ToolContext with session_id, user_id, connection_id

        Returns:
            ToolResult with success=True and data={tables: [...], fields: {...}}
            On error: ToolResult with success=False, error
        """
        start_time = time.time()
        connection_id = params.get("connection_id") or context.connection_id
        table_name = params.get("table_name")
        limit = params.get("limit", 100)
        include_all_asset_types = bool(params.get("include_all_asset_types", False))

        if not connection_id:
            return ToolResult(
                success=False,
                data=None,
                error="connection_id is required (provide via param or context)",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            logger.info(
                "SchemaTool.execute: connection_id=%s, table_name=%s, trace=%s",
                connection_id,
                table_name,
                context.trace_id,
            )

            db = SessionLocal()
            try:
                tc = db.query(TableauConnection).filter(
                    TableauConnection.id == connection_id,
                    TableauConnection.is_active == True,
                ).first()

                if not tc:
                    return ToolResult(
                        success=False,
                        data=None,
                        error="Tableau 连接不存在或已停用",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )

                result = self._query_tableau_schema(
                    db,
                    tc,
                    table_name,
                    limit,
                    include_all_asset_types=include_all_asset_types,
                )
            finally:
                db.close()

            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.info(
                "SchemaTool success: connection_id=%s, tables=%d, time=%dms",
                connection_id,
                len(result.get("tables", [])),
                execution_time_ms,
            )

            return ToolResult(
                success=True,
                data=result,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            logger.exception("SchemaTool unexpected error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error="查询表结构失败，请稍后重试",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    def _query_tableau_schema(
        self,
        db,
        tc: "TableauConnection",
        table_name: Optional[str],
        limit: int,
        *,
        include_all_asset_types: bool = False,
    ) -> Dict[str, Any]:
        """Query Tableau assets and fields as the schema for a Tableau connection."""
        asset_query = db.query(TableauAsset).filter(
            TableauAsset.connection_id == tc.id,
            TableauAsset.is_deleted == False,
        )
        if not include_all_asset_types:
            asset_query = asset_query.filter(TableauAsset.asset_type == "datasource")
        assets = asset_query.order_by(TableauAsset.asset_type, TableauAsset.name).limit(limit).all()

        asset_types = {}
        for asset in assets:
            asset_types.setdefault(asset.asset_type, []).append({
                "name": asset.name,
                "project": asset.project_name,
                "tableau_id": asset.tableau_id,
                "web_url": asset.web_url,
            })

        tables = [
            {
                "name": asset.name,
                "type": asset.asset_type,
                "project": asset.project_name,
                "web_url": asset.web_url,
            }
            for asset in assets
        ]

        fields: Dict[str, Any] = {}
        matched_asset = None
        matched_table = None
        field_count = 0
        warning = None
        if table_name:
            target_asset = self._find_tableau_asset(db, tc.id, table_name)
            if target_asset:
                matched_asset = self._serialize_tableau_asset(target_asset)
                matched_table = {
                    "name": target_asset.name,
                    "type": target_asset.asset_type,
                    "project": target_asset.project_name,
                    "web_url": target_asset.web_url,
                }
                field_records = db.query(TableauDatasourceField).filter(
                    TableauDatasourceField.asset_id == target_asset.id,
                ).all()
                if not field_records:
                    sync_result = self._sync_missing_tableau_fields(db, tc, target_asset)
                    if sync_result.get("synced", 0) > 0:
                        field_records = db.query(TableauDatasourceField).filter(
                            TableauDatasourceField.asset_id == target_asset.id,
                        ).all()
                metadata_field_rows = self._serialize_tableau_fields(field_records)
                queryable_field_names = self._get_queryable_field_names(
                    target_asset.tableau_id,
                    tc.id,
                )
                queryable_field_rows = self._build_queryable_field_rows(
                    queryable_field_names,
                    metadata_field_rows,
                )

                fields[target_asset.name] = queryable_field_rows
                field_count = len(fields[target_asset.name])
                metadata_field_count = len(metadata_field_rows)
                if field_count == 0 and metadata_field_count == 0:
                    sync_error = sync_result.get("error") if "sync_result" in locals() else None
                    warning = (
                        f"已匹配到 Tableau 资产，但自动同步字段元数据未返回字段：{sync_error}"
                        if sync_error
                        else "已匹配到 Tableau 资产，但 Tableau 未返回字段元数据"
                    )
                elif field_count == 0:
                    warning = (
                        "已匹配到 Tableau 资产，但 Tableau MCP 未返回当前可查询字段；"
                        "为避免把资产元数据字段误认为可查询字段，本次不展示 API 同步字段。"
                    )

        result: Dict[str, Any] = {
            "connection_id": tc.id,
            "datasource_name": tc.name,
            "db_type": "tableau",
            "server_url": tc.server_url,
            "site": tc.site,
        }
        if table_name:
            result.update({
                "requested_table_name": table_name,
                "matched_asset": matched_asset,
                "field_count": field_count,
                "queryable_field_count": field_count,
                "metadata_field_count": metadata_field_count if "metadata_field_count" in locals() else 0,
                "field_source": "mcp_queryable_fields",
                "fields": fields,
                "metadata_fields": (
                    {target_asset.name: metadata_field_rows}
                    if "target_asset" in locals() and target_asset and "metadata_field_rows" in locals()
                    else {}
                ),
                "tables": [matched_table] if matched_table else [],
            })
            if warning:
                result["warning"] = warning
        else:
            result.update({
                "tables": tables,
                "fields": fields,
                "asset_summary": {
                    asset_type: len(items)
                    for asset_type, items in asset_types.items()
                },
            })

        return result

    def _get_queryable_field_names(self, datasource_luid: str, connection_id: int) -> List[str]:
        """Return fields Tableau MCP says are currently queryable for a datasource."""
        return _get_mcp_queryable_field_candidates(datasource_luid, connection_id)

    def _serialize_tableau_fields(self, field_records: List["TableauDatasourceField"]) -> List[Dict[str, Any]]:
        return [
            {
                "name": field.field_name,
                "caption": field.field_caption,
                "data_type": field.data_type,
                "role": field.role,
                "is_calculated": field.is_calculated,
            }
            for field in field_records
        ]

    def _build_queryable_field_rows(
        self,
        queryable_field_names: List[str],
        metadata_field_rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Map MCP queryable names onto metadata rows when possible for type/role hints."""
        metadata_by_key: Dict[str, Dict[str, Any]] = {}
        for field in metadata_field_rows:
            for value in (field.get("caption"), field.get("name")):
                key = self._compact_field_name(value)
                if key and key not in metadata_by_key:
                    metadata_by_key[key] = field

        rows: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for field_name in queryable_field_names:
            display_name = str(field_name or "").strip()
            key = self._compact_field_name(display_name)
            if not display_name or key in seen:
                continue
            seen.add(key)
            metadata = metadata_by_key.get(key)
            if metadata:
                row = dict(metadata)
                row["name"] = display_name
                if not row.get("caption"):
                    row["caption"] = display_name
            else:
                row = {
                    "name": display_name,
                    "caption": display_name,
                    "data_type": "",
                    "role": "",
                    "is_calculated": False,
                }
            row["mcp_queryable"] = True
            rows.append(row)
        return rows

    @staticmethod
    def _compact_field_name(value: Any) -> str:
        return str(value or "").strip().lower().replace(" ", "").replace(" ", "")

    def _sync_missing_tableau_fields(
        self,
        db,
        tc: "TableauConnection",
        asset: "TableauAsset",
    ) -> Dict[str, Any]:
        """Fetch and cache fields for a matched Tableau datasource on demand."""
        try:
            token_value = get_tableau_crypto().decrypt(tc.token_encrypted)
        except Exception as e:
            logger.warning("SchemaTool field sync skipped: token decrypt failed for connection_id=%s", tc.id)
            return {"synced": 0, "error": f"Token 解密失败: {e}"}

        service = TableauRestSyncService(
            server_url=tc.server_url,
            site=tc.site,
            token_name=tc.token_name,
            token_value=token_value,
            api_version=tc.api_version or "3.21",
        )
        try:
            if not service.connect():
                return {"synced": 0, "error": "Tableau REST API 认证失败"}

            raw_fields = service._get_datasource_fields(asset.tableau_id)
            parsed_fields = [
                service._parse_field_metadata(field)
                for field in raw_fields
            ]
            parsed_fields = [
                field
                for field in parsed_fields
                if field.get("field_name") or field.get("field_caption")
            ]
            if not parsed_fields:
                return {"synced": 0, "error": "Tableau 未返回字段列表"}

            TableauDatabase(session=db).upsert_datasource_fields(
                asset.id,
                asset.tableau_id,
                parsed_fields,
            )
            asset.field_count = len(parsed_fields)
            db.commit()
            logger.info(
                "SchemaTool auto-synced %d fields for Tableau asset_id=%s datasource=%s",
                len(parsed_fields),
                asset.id,
                asset.name,
            )
            return {"synced": len(parsed_fields)}
        except Exception as e:
            logger.warning(
                "SchemaTool auto field sync failed for asset_id=%s datasource=%s: %s",
                asset.id,
                asset.name,
                e,
                exc_info=True,
            )
            return {"synced": 0, "error": str(e)}
        finally:
            service.disconnect()

    def _find_tableau_asset(
        self, db, connection_id: int, table_name: str
    ) -> Optional["TableauAsset"]:
        """Find a Tableau asset by exact name first, then by case-insensitive containment."""
        target_asset = db.query(TableauAsset).filter(
            TableauAsset.connection_id == connection_id,
            TableauAsset.is_deleted == False,
            TableauAsset.asset_type == "datasource",
            TableauAsset.name == table_name,
        ).first()
        if target_asset:
            return target_asset

        normalized_table_name = table_name.casefold()
        candidates = db.query(TableauAsset).filter(
            TableauAsset.connection_id == connection_id,
            TableauAsset.is_deleted == False,
            TableauAsset.asset_type == "datasource",
        ).order_by(TableauAsset.asset_type, TableauAsset.name).all()

        for asset in candidates:
            asset_name = (asset.name or "").casefold()
            if asset_name == normalized_table_name:
                return asset

        for asset in candidates:
            asset_name = (asset.name or "").casefold()
            if normalized_table_name in asset_name or asset_name in normalized_table_name:
                return asset

        return None

    def _serialize_tableau_asset(self, asset: "TableauAsset") -> Dict[str, Any]:
        return {
            "asset_id": asset.id,
            "name": asset.name,
            "type": asset.asset_type,
            "project": asset.project_name,
            "tableau_id": asset.tableau_id,
            "web_url": asset.web_url,
        }
