"""
SchemaTool — Phase 2: 数据源 schema/表结构查询

Spec: docs/specs/36-data-agent-architecture-spec.md §3.1 ToolRegistry + §9.2 downstream
"""

import asyncio
import logging
import time
import urllib.parse
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text

from app.core.crypto import get_datasource_crypto
from app.core.database import SessionLocal
from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext
from services.datasources.models import DataSource

logger = logging.getLogger(__name__)


class SchemaTool(BaseTool):
    """
    Phase 2 Data Agent Tool: Schema / Table Structure Query.

    Queries table structures, field metadata from data sources.
    Used when user asks "what tables exist", "what fields does X table have",
    "show me the schema/data structure".

    Tool name: "schema"
    """

    name = "schema"
    description = "查询数据源的表结构、字段信息。当用户询问「有哪些表」「某表的字段是什么」「数据结构」时使用。"
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
        },
        "required": [],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """
        Execute a schema query.

        Pipeline:
        1. Resolve connection_id (param overrides context)
        2. Fetch DataSource from bi_data_sources
        3. Query INFORMATION_SCHEMA for table/column metadata
        4. Return structured table/field info

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

            # ── Stage 1: Fetch DataSource ──────────────────────────────────────
            db = SessionLocal()
            try:
                ds: Optional[DataSource] = db.query(DataSource).filter(
                    DataSource.id == connection_id
                ).first()

                if not ds:
                    return ToolResult(
                        success=False,
                        data=None,
                        error=f"Data source not found: connection_id={connection_id}",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )

                crypto = get_datasource_crypto()
                password = crypto.decrypt(ds.password_encrypted)

                # ── Stage 2: Query INFORMATION_SCHEMA ──────────────────────────
                if ds.db_type == "postgresql":
                    result = await self._query_postgresql_schema(ds, password, table_name, limit)
                elif ds.db_type in ("mysql", "mariadb"):
                    result = await self._query_mysql_schema(ds, password, table_name, limit)
                elif ds.db_type == "sqlserver":
                    result = await self._query_sqlserver_schema(ds, password, table_name, limit)
                else:
                    result = await self._query_postgresql_schema(ds, password, table_name, limit)
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

    def _query_postgresql_schema_sync(
        self, ds: DataSource, password: str, table_name: Optional[str], limit: int
    ) -> Dict[str, Any]:
        """Query PostgreSQL INFORMATION_SCHEMA for table/column metadata."""
        db_url = (
            f"postgresql://{ds.username}:{urllib.parse.quote_plus(password)}@"
            f"{ds.host}:{ds.port}/{ds.database_name}"
        )

        remote_engine = create_engine(db_url, pool_pre_ping=True, pool_size=1)
        remote_conn = remote_engine.connect()

        try:
            if table_name:
                tables_query = text("""
                    SELECT table_name, table_type, is_insertable_into
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = :table_name
                    ORDER BY table_name
                    LIMIT :limit
                """)
            else:
                tables_query = text("""
                    SELECT table_name, table_type, is_insertable_into
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                    LIMIT :limit
                """)

            tables_result = remote_conn.execute(tables_query, {"table_name": table_name or "", "limit": limit})
            tables = [
                {
                    "name": row[0],
                    "type": row[1],
                    "is_insertable": row[2],
                }
                for row in tables_result
            ]

            fields = {}
            if table_name:
                columns_query = text("""
                    SELECT
                        c.column_name,
                        c.data_type,
                        c.character_maximum_length,
                        c.is_nullable,
                        c.column_default,
                        c.identity_generation
                    FROM information_schema.columns c
                    WHERE c.table_schema = 'public' AND c.table_name = :table_name
                    ORDER BY c.ordinal_position
                """)
                columns_result = remote_conn.execute(columns_query, {"table_name": table_name})
                fields[table_name] = [
                    {
                        "name": row[0],
                        "data_type": row[1],
                        "max_length": row[2],
                        "nullable": row[3] == "YES",
                        "default": row[4],
                        "identity": row[5],
                    }
                    for row in columns_result
                ]

            if table_name:
                pk_query = text("""
                    SELECT kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                      AND tc.table_schema = kcu.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                      AND tc.table_schema = 'public'
                      AND tc.table_name = :table_name
                """)
                pk_result = remote_conn.execute(pk_query, {"table_name": table_name})
                pk_columns = [row[0] for row in pk_result]
                if table_name in fields:
                    for f in fields[table_name]:
                        f["is_primary_key"] = f["name"] in pk_columns

            return {
                "connection_id": ds.id,
                "datasource_name": ds.name,
                "db_type": ds.db_type,
                "tables": tables,
                "fields": fields,
            }
        finally:
            remote_conn.close()
            remote_engine.dispose()

    async def _query_postgresql_schema(
        self, ds: DataSource, password: str, table_name: Optional[str], limit: int
    ) -> Dict[str, Any]:
        """Query PostgreSQL INFORMATION_SCHEMA for table/column metadata."""
        return await asyncio.to_thread(
            self._query_postgresql_schema_sync, ds, password, table_name, limit
        )

    def _query_mysql_schema_sync(
        self, ds: DataSource, password: str, table_name: Optional[str], limit: int
    ) -> Dict[str, Any]:
        """Query MySQL INFORMATION_SCHEMA for table/column metadata."""
        db_url = (
            f"mysql+pymysql://{ds.username}:{urllib.parse.quote_plus(password)}@"
            f"{ds.host}:{ds.port}/{ds.database_name}"
        )

        remote_engine = create_engine(db_url, pool_pre_ping=True, pool_size=1)
        remote_conn = remote_engine.connect()

        try:
            schema = ds.database_name

            if table_name:
                tables_query = text("""
                    SELECT table_name, table_type
                    FROM information_schema.tables
                    WHERE table_schema = :schema AND table_name = :table_name
                    ORDER BY table_name
                    LIMIT :limit
                """)
            else:
                tables_query = text("""
                    SELECT table_name, table_type
                    FROM information_schema.tables
                    WHERE table_schema = :schema
                    ORDER BY table_name
                    LIMIT :limit
                """)

            tables_result = remote_conn.execute(
                tables_query, {"schema": schema, "table_name": table_name or "", "limit": limit}
            )
            tables = [
                {"name": row[0], "type": row[1]}
                for row in tables_result
            ]

            fields = {}
            if table_name:
                columns_query = text("""
                    SELECT
                        column_name, data_type, character_maximum_length,
                        is_nullable, column_default, column_key
                    FROM information_schema.columns
                    WHERE table_schema = :schema AND table_name = :table_name
                    ORDER BY ordinal_position
                """)
                columns_result = remote_conn.execute(
                    columns_query, {"schema": schema, "table_name": table_name}
                )
                fields[table_name] = [
                    {
                        "name": row[0],
                        "data_type": row[1],
                        "max_length": row[2],
                        "nullable": row[3] == "YES",
                        "default": row[4],
                        "key": row[5],
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
            remote_conn.close()
            remote_engine.dispose()

    async def _query_mysql_schema(
        self, ds: DataSource, password: str, table_name: Optional[str], limit: int
    ) -> Dict[str, Any]:
        """Query MySQL INFORMATION_SCHEMA for table/column metadata."""
        return await asyncio.to_thread(
            self._query_mysql_schema_sync, ds, password, table_name, limit
        )

    def _query_sqlserver_schema_sync(
        self, ds: DataSource, password: str, table_name: Optional[str], limit: int
    ) -> Dict[str, Any]:
        """Query SQL Server INFORMATION_SCHEMA for table/column metadata."""
        db_url = (
            f"mssql+pyodbc://{ds.username}:{urllib.parse.quote_plus(password)}@"
            f"{ds.host}:{ds.port}/{ds.database_name}?driver=ODBC+Driver+17+for+SQL+Server"
        )

        remote_engine = create_engine(db_url, pool_pre_ping=True, pool_size=1)
        remote_conn = remote_engine.connect()

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

            tables_result = remote_conn.execute(
                tables_query, {"table_name": table_name or "", "limit": limit}
            )
            tables = [
                {"name": row[0], "type": row[1]}
                for row in tables_result
            ]

            fields = {}
            if table_name:
                columns_query = text("""
                    SELECT
                        c.COLUMN_NAME, c.DATA_TYPE, c.CHARACTER_MAXIMUM_LENGTH,
                        c.IS_NULLABLE, c.COLUMN_DEFAULT,
                        COLUMNPROPERTY(OBJECT_ID(:schema_table), c.COLUMN_NAME, 'IsIdentity') as is_identity
                    FROM INFORMATION_SCHEMA.COLUMNS c
                    WHERE c.TABLE_SCHEMA = 'dbo' AND c.TABLE_NAME = :table_name
                    ORDER BY c.ORDINAL_POSITION
                """)
                columns_result = remote_conn.execute(
                    columns_query, {"table_name": table_name, "schema_table": f"dbo.{table_name}"}
                )
                fields[table_name] = [
                    {
                        "name": row[0],
                        "data_type": row[1],
                        "max_length": row[2],
                        "nullable": row[3] == "YES",
                        "default": row[4],
                        "identity": bool(row[5]) if row[5] is not None else False,
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
            remote_conn.close()
            remote_engine.dispose()

    async def _query_sqlserver_schema(
        self, ds: DataSource, password: str, table_name: Optional[str], limit: int
    ) -> Dict[str, Any]:
        """Query SQL Server INFORMATION_SCHEMA for table/column metadata."""
        return await asyncio.to_thread(
            self._query_sqlserver_schema_sync, ds, password, table_name, limit
        )