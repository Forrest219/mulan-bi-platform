"""
SqlExecuteTool — SQL 执行

Spec 28 §4.1 — sql_execute

功能：
- 通过 HTTP API 调用 SQL Agent
- 携带 X-Forward-User-JWT（用户发起）或 X-Scan-Service-JWT（调度扫描）
- 解析 result_summary + result_metadata
"""

import logging
import time
from typing import Any, Dict, Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata
from services.data_agent_analysis.sql_agent_client import SQLAgentClient, SQLAgentError

logger = logging.getLogger(__name__)


class SqlExecuteTool(BaseTool):
    """SQL Execute Tool — 通过 HTTP API 调用 SQL Agent"""

    name = "sql_execute"
    description = "通过 SQL Agent HTTP API 执行数据查询。返回结构化的查询结果和元数据。"
    metadata = ToolMetadata(
        category="query",
        version="1.0.0",
        dependencies=["requires_database", "requires_sql_agent"],
        tags=["sql", "query", "http_api", "sql_agent"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "natural_language_intent": {
                "type": "string",
                "description": "自然语言查询意图",
            },
            "actor": {
                "type": "object",
                "description": "参与者信息",
                "properties": {
                    "user_id": {"type": "integer"},
                    "roles": {"type": "array", "items": {"type": "string"}},
                    "allowed_datasources": {"type": "array", "items": {"type": "integer"}},
                    "allowed_metrics": {"type": "array", "items": {"type": "string"}},
                    "allowed_dimensions": {"type": "array", "items": {"type": "string"}},
                },
            },
            "schema_context": {
                "type": "object",
                "description": "Schema 上下文",
                "properties": {
                    "available_tables": {"type": "array", "items": {"type": "string"}},
                    "metric_definitions": {"type": "object"},
                },
            },
            "session_id": {
                "type": "string",
                "description": "分析会话 ID（用于上下文关联）",
            },
            "metric": {
                "type": "string",
                "description": "指标名（简化参数）",
            },
            "time_range": {
                "type": "object",
                "description": "时间范围",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                },
            },
            "dimensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "维度列表（简化参数）",
            },
            "max_rows": {
                "type": "integer",
                "description": "最大返回行数（默认 10000）",
                "default": 10000,
            },
            "query_timeout_seconds": {
                "type": "integer",
                "description": "查询超时时间（秒，默认 30）",
                "default": 30,
            },
            "user_jwt": {
                "type": "string",
                "description": "X-Forward-User-JWT（用户发起时）",
            },
            "scan_service_jwt": {
                "type": "string",
                "description": "X-Scan-Service-JWT（调度扫描时）",
            },
        },
        "required": ["natural_language_intent"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        start_time = time.time()
        natural_language_intent = params.get("natural_language_intent", "")
        actor = params.get("actor", {})
        schema_context = params.get("schema_context", {})
        session_id = params.get("session_id") or context.session_id
        metric = params.get("metric", "")
        time_range = params.get("time_range", {})
        dimensions = params.get("dimensions", [])
        max_rows = params.get("max_rows", 10000)
        query_timeout_seconds = params.get("query_timeout_seconds", 30)
        user_jwt = params.get("user_jwt")
        scan_service_jwt = params.get("scan_service_jwt")

        if not natural_language_intent:
            return ToolResult(
                success=False,
                data=None,
                error="natural_language_intent 是必填参数",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            logger.info(
                "SqlExecuteTool: natural_language_intent=%s, session_id=%s",
                natural_language_intent[:100],
                session_id,
            )

            # 如果没有提供 actor，使用 context 中的信息构建
            if not actor:
                actor = {
                    "user_id": context.user_id if hasattr(context, "user_id") else 0,
                    "roles": [],
                    "allowed_datasources": [context.connection_id] if context.connection_id else [],
                    "allowed_metrics": [metric] if metric else [],
                    "allowed_dimensions": dimensions,
                }

            # 如果没有提供 schema_context，构建基本的
            if not schema_context and metric:
                schema_context = {
                    "available_tables": [],
                    "metric_definitions": {metric: f"指标 {metric}"},
                }

            async with SQLAgentClient() as client:
                result = await client.query(
                    natural_language_intent=natural_language_intent,
                    actor=actor,
                    schema_context=schema_context,
                    session_id=session_id,
                    max_rows=max_rows,
                    query_timeout_seconds=query_timeout_seconds,
                    user_jwt=user_jwt,
                    scan_service_jwt=scan_service_jwt,
                )

            execution_time_ms = result.get("execution_time_ms", int((time.time() - start_time) * 1000))

            return ToolResult(
                success=True,
                data={
                    "sql": result.get("sql", ""),
                    "result_summary": result.get("result_summary", ""),
                    "result_metadata": result.get("result_metadata", {}),
                    "execution_time_ms": execution_time_ms,
                },
                execution_time_ms=execution_time_ms,
            )

        except SQLAgentError as e:
            logger.warning("SqlExecuteTool SQLAgentError: code=%s, message=%s", e.code, e.message)
            return ToolResult(
                success=False,
                data=None,
                error=f"[{e.code}] {e.message}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        except Exception as e:
            logger.exception("SqlExecuteTool error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"SQL 执行失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )