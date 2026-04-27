"""
QueryTool — Phase 1 tool wrapping NLQ Service + SQL Agent

Spec: docs/specs/36-data-agent-architecture-spec.md §3.1 ToolRegistry + §9.2 downstream
Spec: docs/specs/14-nl-to-query-pipeline-spec.md — NLQ Service
Spec: docs/specs/29-sql-agent-spec.md — SQL Agent
"""

import logging
import time
from typing import Any, Optional

from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata
from services.llm.nlq_service import one_pass_llm, execute_query, route_datasource, NLQError

logger = logging.getLogger(__name__)


class QueryTool(BaseTool):
    """
    Phase 1 Data Agent Tool: Natural Language Query Tool.
    
    Wraps:
    - NLQ Service (Spec 14): one_pass_llm → route_datasource → resolve_fields
    - SQL Agent (Spec 29): execute_query via Tableau MCP
    
    Tool name: "query"
    """

    name = "query"
    description = "执行自然语言数据查询。将用户问题转换为 Tableau VizQL 查询并返回结构化数据结果。适用于询问销售额、数量、统计数据等。"
    metadata = ToolMetadata(
        category="query",
        version="1.0.0",
        dependencies=["requires_database", "requires_tableau"],
        tags=["nlq", "vizql", "data-query"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "用户的自然语言问题，如 'Q4销售额是多少'",
            },
            "connection_id": {
                "type": "integer",
                "description": "数据源连接 ID（可选，默认使用系统默认连接）",
            },
        },
        "required": ["question"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """
        Execute a natural language query.
        
        Pipeline:
        1. route_datasource — find the right Tableau datasource
        2. one_pass_llm — convert NL to VizQL JSON
        3. execute_query — run via Tableau MCP
        
        Args:
            params: {"question": str, "connection_id"?: int}
            context: ToolContext with session_id, user_id, connection_id
            
        Returns:
            ToolResult with success=True and data={fields, rows, ...}
        """
        start_time = time.time()
        question = params.get("question", "")
        connection_id = params.get("connection_id") or context.connection_id

        if not question:
            return ToolResult(
                success=False,
                data=None,
                error="question cannot be empty",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            logger.info(
                "QueryTool.execute: question=%s, connection_id=%s, trace=%s",
                question,
                connection_id,
                context.trace_id,
            )

            # ── Stage 1: Route to datasource ───────────────────────────────────
            ds_info = route_datasource(question, connection_id=connection_id)
            if not ds_info:
                return ToolResult(
                    success=False,
                    data=None,
                    error="无法找到匹配的数据源，请明确指定数据源或使用正确的术语",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            datasource_luid = ds_info["luid"]
            datasource_name = ds_info.get("name", datasource_luid)
            fields_with_types = ds_info.get("fields_with_types", "")
            term_mappings = ds_info.get("term_mappings", "")

            # ── Stage 2: NL → VizQL via one_pass_llm ──────────────────────────
            try:
                parsed = await one_pass_llm(
                    question=question,
                    datasource_luid=datasource_luid,
                    datasource_name=datasource_name,
                    fields_with_types=fields_with_types,
                    term_mappings=term_mappings,
                )
            except NLQError as e:
                logger.warning("QueryTool NLQ failed: code=%s, message=%s", e.code, e.message)
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"[{e.code}] {e.message}",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            vizql_json = parsed.get("vizql_json", {})
            if not vizql_json:
                return ToolResult(
                    success=False,
                    data=None,
                    error="NLQ 返回的 VizQL JSON 为空",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            # ── Stage 3: Execute query ────────────────────────────────────────
            try:
                result = execute_query(
                    datasource_luid=datasource_luid,
                    vizql_json=vizql_json,
                    limit=1000,
                    connection_id=connection_id,
                )
            except NLQError as e:
                logger.warning("QueryTool execute_query failed: code=%s, message=%s", e.code, e.message)
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"[{e.code}] {e.message}",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.info(
                "QueryTool success: datasource=%s, rows=%d, time=%dms",
                datasource_luid,
                len(result.get("rows", [])),
                execution_time_ms,
            )

            return ToolResult(
                success=True,
                data={
                    "fields": result.get("fields", []),
                    "rows": result.get("rows", []),
                    "intent": parsed.get("intent"),
                    "confidence": parsed.get("confidence"),
                    "datasource_name": datasource_name,
                },
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            logger.exception("QueryTool unexpected error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error="数据查询服务暂时不可用，请稍后重试",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )