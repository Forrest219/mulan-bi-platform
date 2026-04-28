"""
SchemaLookupTool — 元数据查询

Spec 28 §4.1 — schema_lookup

功能：
- 查询表结构、字段语义、血缘关系
- 返回表名、字段名、类型、描述等
"""

import asyncio
import logging
import time
import urllib.parse
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text

from app.core.crypto import get_datasource_crypto
from app.core.database import SessionLocal
from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata
from services.datasources.models import DataSource

logger = logging.getLogger(__name__)


class SchemaLookupTool(BaseTool):
    """Schema Lookup Tool — 查询数据源表结构"""

    name = "schema_lookup"
    description = "查询数据源的表结构、字段信息及血缘关系。当需要了解有哪些表、某表包含哪些字段、数据血缘时使用。"
    metadata = ToolMetadata(
        category="query",
        version="1.0.0",
        dependencies=["requires_database"],
        tags=["schema", "metadata", "table_structure", "lineage"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "integer",
                "description": "数据源连接 ID",
            },
            "table_name": {
                "type": "string",
                "description": "指定表名，查询该表的字段结构（可选，不填则返回所有表）",
            },
            "include_lineage": {
                "type": "boolean",
                "description": "是否包含血缘信息（默认 false）",
                "default": False,
            },
            "limit": {
                "type": "integer",
                "description": "返回的表数量上限（默认 100）",
                "default": 100,
            },
        },
        "required": ["connection_id"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        start_time = time.time()
        connection_id = params.get("connection_id") or context.connection_id
        table_name = params.get("table_name")
        include_lineage = params.get("include_lineage", False)
        limit = params.get("limit", 100)

        if not connection_id:
            return ToolResult(
                success=False,
                data=None,
                error="connection_id 是必填参数",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            logger.info(
                "SchemaLookupTool: connection_id=%s, table_name=%s",
                connection_id,
                table_name,
            )

            db = SessionLocal()
            try:
                ds = db.query(DataSource).filter(DataSource.id == connection_id).first()
                if not ds:
                    return ToolResult(
                        success=False,
                        data=None,
                        error=f"数据源不存在: connection_id={connection_id}",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )

                crypto = get_datasource_crypto()
                password = crypto.decrypt(ds.password_encrypted)

                if ds.db_type == "postgresql":
                    result = await self._query_postgresql(ds, password, table_name, limit)
                elif ds.db_type in ("mysql", "mariadb"):
                    result = await self._query_mysql(ds, password, table_name, limit)
                elif ds.db_type == "sqlserver":
                    result = await self._query_sqlserver(ds, password, table_name, limit)
                else:
                    result = await self._query_postgresql(ds, password, table_name, limit)

                return ToolResult(
                    success=True,
                    data=result,
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            finally:
                db.close()

        except Exception as e:
            logger.exception("SchemaLookupTool error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"查询表结构失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    def _query_postgresql_sync(
        self, ds: DataSource, password: str, table_name: Optional[str], limit: int
    ) -> Dict[str, Any]:
        db_url = (
            f"postgresql://{ds.username}:{urllib.parse.quote_plus(password)}@"
            f"{ds.host}:{ds.port}/{ds.database_name}"
        )
        engine = create_engine(db_url, pool_pre_ping=True, pool_size=1)
        conn = engine.connect()

        try:
            if table_name:
                tables_query = text("""
                    SELECT table_name, table_type
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = :table_name
                    ORDER BY table_name LIMIT :limit
                """)
            else:
                tables_query = text("""
                    SELECT table_name, table_type
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    ORDER BY table_name LIMIT :limit
                """)

            tables_result = conn.execute(tables_query, {"table_name": table_name or "", "limit": limit})
            tables = [{"name": row[0], "type": row[1]} for row in tables_result]

            fields = {}
            if table_name:
                columns_query = text("""
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = :table_name
                    ORDER BY ordinal_position
                """)
                columns_result = conn.execute(columns_query, {"table_name": table_name})
                fields[table_name] = [
                    {
                        "name": row[0],
                        "data_type": row[1],
                        "nullable": row[2] == "YES",
                        "default": row[3],
                    }
                    for row in columns_result
                ]

            return {
                "connection_id": ds.id,
                "datasource_name": ds.name,
                "db_type": ds.db_type,
                "tables": tables,
                "fields": fields,
            }
        finally:
            conn.close()
            engine.dispose()

    async def _query_postgresql(self, ds, password, table_name, limit):
        return await asyncio.to_thread(self._query_postgresql_sync, ds, password, table_name, limit)

    def _query_mysql_sync(
        self, ds: DataSource, password: str, table_name: Optional[str], limit: int
    ) -> Dict[str, Any]:
        db_url = (
            f"mysql+pymysql://{ds.username}:{urllib.parse.quote_plus(password)}@"
            f"{ds.host}:{ds.port}/{ds.database_name}"
        )
        engine = create_engine(db_url, pool_pre_ping=True, pool_size=1)
        conn = engine.connect()

        try:
            schema = ds.database_name

            if table_name:
                tables_query = text("""
                    SELECT table_name, table_type
                    FROM information_schema.tables
                    WHERE table_schema = :schema AND table_name = :table_name
                    ORDER BY table_name LIMIT :limit
                """)
            else:
                tables_query = text("""
                    SELECT table_name, table_type
                    FROM information_schema.tables
                    WHERE table_schema = :schema
                    ORDER BY table_name LIMIT :limit
                """)

            tables_result = conn.execute(
                tables_query, {"schema": schema, "table_name": table_name or "", "limit": limit}
            )
            tables = [{"name": row[0], "type": row[1]} for row in tables_result]

            fields = {}
            if table_name:
                columns_query = text("""
                    SELECT column_name, data_type, is_nullable, column_default, column_key
                    FROM information_schema.columns
                    WHERE table_schema = :schema AND table_name = :table_name
                    ORDER BY ordinal_position
                """)
                columns_result = conn.execute(
                    columns_query, {"schema": schema, "table_name": table_name}
                )
                fields[table_name] = [
                    {
                        "name": row[0],
                        "data_type": row[1],
                        "nullable": row[2] == "YES",
                        "default": row[3],
                        "key": row[4],
                    }
                    for row in columns_result
                ]

            return {
                "connection_id": ds.id,
                "datasource_name": ds.name,
                "db_type": ds.db_type,
                "tables": tables,
                "fields": fields,
            }
        finally:
            conn.close()
            engine.dispose()

    async def _query_mysql(self, ds, password, table_name, limit):
        return await asyncio.to_thread(self._query_mysql_sync, ds, password, table_name, limit)

    def _query_sqlserver_sync(
        self, ds: DataSource, password: str, table_name: Optional[str], limit: int
    ) -> Dict[str, Any]:
        db_url = (
            f"mssql+pyodbc://{ds.username}:{urllib.parse.quote_plus(password)}@"
            f"{ds.host}:{ds.port}/{ds.database_name}?driver=ODBC+Driver+17+for+SQL+Server"
        )
        engine = create_engine(db_url, pool_pre_ping=True, pool_size=1)
        conn = engine.connect()

        try:
            if table_name:
                tables_query = text("""
                    SELECT TABLE_NAME, TABLE_TYPE
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = :table_name
                    ORDER BY TABLE_NAME
                """)
            else:
                tables_query = text("""
                    SELECT TOP(:limit) TABLE_NAME, TABLE_TYPE
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = 'dbo'
                    ORDER BY TABLE_NAME
                """)

            tables_result = conn.execute(
                tables_query, {"table_name": table_name or "", "limit": limit}
            )
            tables = [{"name": row[0], "type": row[1]} for row in tables_result]

            fields = {}
            if table_name:
                columns_query = text("""
                    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = :table_name
                    ORDER BY ORDINAL_POSITION
                """)
                columns_result = conn.execute(
                    columns_query, {"table_name": table_name}
                )
                fields[table_name] = [
                    {
                        "name": row[0],
                        "data_type": row[1],
                        "nullable": row[2] == "YES",
                        "default": row[3],
                    }
                    for row in columns_result
                ]

            return {
                "connection_id": ds.id,
                "datasource_name": ds.name,
                "db_type": ds.db_type,
                "tables": tables,
                "fields": fields,
            }
        finally:
            conn.close()
            engine.dispose()

    async def _query_sqlserver(self, ds, password, table_name, limit):
        return await asyncio.to_thread(self._query_sqlserver_sync, ds, password, table_name, limit)