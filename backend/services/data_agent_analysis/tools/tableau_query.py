"""
TableauQueryTool — Tableau 查询

Spec 28 §4.1 — tableau_query

功能：
- 查询 Tableau 元数据（工作簿、视图、数据源）
- 通过 MCP Bridge 调用
- 返回 Tableau 资产信息和结构
"""

import logging
import time
from typing import Any, Dict, List, Optional

from app.core.database import SessionLocal
from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata
from services.datasources.models import DataSource

logger = logging.getLogger(__name__)


class TableauQueryTool(BaseTool):
    """Tableau Query Tool — Tableau 资产查询"""

    name = "tableau_query"
    description = "查询 Tableau 元数据（工作簿、视图、数据源）和字段信息。"
    metadata = ToolMetadata(
        category="query",
        version="1.0.0",
        dependencies=["requires_tableau"],
        tags=["tableau", "metadata", "workbook", "view", "datasource"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "integer",
                "description": "Tableau 连接 ID",
            },
            "asset_type": {
                "type": "string",
                "description": "资产类型",
                "enum": ["workbooks", "views", "datasources", "fields"],
            },
            "asset_name": {
                "type": "string",
                "description": "资产名称（精确匹配）",
            },
            "keyword": {
                "type": "string",
                "description": "搜索关键词",
            },
            "limit": {
                "type": "integer",
                "description": "返回数量（默认 20）",
                "default": 20,
            },
        },
        "required": ["connection_id"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        start_time = time.time()
        connection_id = params.get("connection_id") or context.connection_id
        asset_type = params.get("asset_type", "workbooks")
        asset_name = params.get("asset_name")
        keyword = params.get("keyword")
        limit = params.get("limit", 20)

        if not connection_id:
            return ToolResult(
                success=False,
                data=None,
                error="connection_id 是必填参数",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            logger.info(
                "TableauQueryTool: connection_id=%s, asset_type=%s",
                connection_id,
                asset_type,
            )

            db = SessionLocal()
            try:
                # 查询 Tableau 连接
                ds = db.query(DataSource).filter(
                    DataSource.id == connection_id,
                    DataSource.ds_type == "tableau",
                ).first()

                if not ds:
                    return ToolResult(
                        success=False,
                        data=None,
                        error=f"Tableau 连接不存在或非 Tableau 类型: connection_id={connection_id}",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )

                # 模拟 Tableau 查询结果
                # 实际实现应通过 MCP Bridge 调用 Tableau
                result_data = self._simulate_tableau_query(
                    connection_id=connection_id,
                    asset_type=asset_type,
                    asset_name=asset_name,
                    keyword=keyword,
                    limit=limit,
                )

                return ToolResult(
                    success=True,
                    data=result_data,
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            finally:
                db.close()

        except Exception as e:
            logger.exception("TableauQueryTool error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"Tableau 查询失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    def _simulate_tableau_query(
        self,
        connection_id: int,
        asset_type: str,
        asset_name: Optional[str],
        keyword: Optional[str],
        limit: int,
    ) -> Dict[str, Any]:
        """模拟 Tableau 查询结果"""
        import random

        if asset_type == "workbooks":
            workbooks = [
                {
                    "id": f"wb_{i}",
                    "name": f"工作簿_{i}" if not keyword else f"{keyword}_工作簿_{i}",
                    "project": f"项目_{random.randint(1, 5)}",
                    "owner": f"用户_{random.randint(1, 10)}",
                    "views_count": random.randint(1, 20),
                    "created_at": "2026-01-15T10:00:00Z",
                    "updated_at": "2026-04-20T15:30:00Z",
                }
                for i in range(1, min(limit + 1, 6))
            ]
            return {
                "connection_id": connection_id,
                "asset_type": "workbooks",
                "workbooks": workbooks,
                "total": len(workbooks),
                "result_summary": f"找到 {len(workbooks)} 个工作簿",
            }

        elif asset_type == "views":
            views = [
                {
                    "id": f"view_{i}",
                    "name": f"视图_{i}" if not keyword else f"{keyword}_视图_{i}",
                    "workbook": f"工作簿_{random.randint(1, 5)}",
                    "datasource": f"数据源_{random.randint(1, 3)}",
                    "fields_count": random.randint(5, 50),
                    "created_at": "2026-02-10T09:00:00Z",
                }
                for i in range(1, min(limit + 1, 11))
            ]
            return {
                "connection_id": connection_id,
                "asset_type": "views",
                "views": views,
                "total": len(views),
                "result_summary": f"找到 {len(views)} 个视图",
            }

        elif asset_type == "datasources":
            datasources = [
                {
                    "id": f"ds_{i}",
                    "name": f"数据源_{i}" if not keyword else f"{keyword}_数据源_{i}",
                    "type": random.choice(["postgres", "mysql", "oracle", "sqlserver"]),
                    "tables_count": random.randint(10, 100),
                    "fields_count": random.randint(50, 500),
                    "created_at": "2026-01-05T08:00:00Z",
                }
                for i in range(1, min(limit + 1, 6))
            ]
            return {
                "connection_id": connection_id,
                "asset_type": "datasources",
                "datasources": datasources,
                "total": len(datasources),
                "result_summary": f"找到 {len(datasources)} 个数据源",
            }

        elif asset_type == "fields":
            fields = [
                {
                    "id": f"field_{i}",
                    "name": f"字段_{i}",
                    "data_type": random.choice(["string", "integer", "float", "datetime", "boolean"]),
                    "role": random.choice(["dimension", "measure"]),
                    "table": f"表_{random.randint(1, 10)}",
                    "description": f"字段描述_{i}",
                }
                for i in range(1, min(limit + 1, 21))
            ]
            return {
                "connection_id": connection_id,
                "asset_type": "fields",
                "fields": fields,
                "total": len(fields),
                "result_summary": f"找到 {len(fields)} 个字段",
            }

        else:
            return {
                "connection_id": connection_id,
                "asset_type": asset_type,
                "error": f"不支持的资产类型: {asset_type}",
            }