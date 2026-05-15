"""
查询执行器（Spec 14 §5.5）

Stage 3：查询执行。
通过 Tableau MCP query-datasource 执行 VizQL JSON。

约束 A：动态凭据传递（contextvars，禁止 os.environ）
约束 B：MCP ClientSession 长连接复用（单例）
约束 C：VizQL JSON 的 fieldCaption 须与阶段2 resolved_fields 对齐
"""
import asyncio
import logging
from contextvars import ContextVar
from typing import Dict, Any, Optional

from services.data_agent.mcp_args_guardrail import (
    DEFAULT_LIMIT as DEFAULT_GUARDRAIL_LIMIT,
    McpArgsGuardrailRejected,
    execute_query_datasource_with_guardrail,
    extract_queryable_fields_from_metadata,
)
from services.tableau.mcp_client import get_tableau_mcp_client, TableauMCPError
from services.llm.nlq_service import get_wrapper, get_principal

logger = logging.getLogger(__name__)

# contextvars 传递 Tableau PAT 凭据（Spec 14 §5.5.7 约束 A）
_tableau_creds: ContextVar[Dict[str, str]] = ContextVar("tableau_creds")


class QueryExecutorError(Exception):
    """查询执行器错误"""

    def __init__(self, code: str, message: str, details: dict = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


def set_tableau_creds(creds: Dict[str, str]):
    """
    设置当前请求的 Tableau 凭据（contextvars）。

    Args:
        creds: 包含 server_url, site, token_name, token_value 的字典
    """
    _tableau_creds.set(creds)


def get_tableau_creds() -> Optional[Dict[str, str]]:
    """获取当前请求的 Tableau 凭据"""
    try:
        return _tableau_creds.get()
    except LookupError:
        return None


def clear_tableau_creds():
    """清除当前请求的 Tableau 凭据"""
    try:
        _tableau_creds.set({})
    except LookupError:
        pass


class QueryExecutor:
    """
    查询执行器。

    通过 Tableau MCP query-datasource 执行 VizQL JSON 查询。
    """

    def __init__(self, mcp_client=None):
        """
        Args:
            mcp_client: Tableau MCP 客户端单例（可选）
        """
        self.mcp_client = mcp_client

    def execute(
        self,
        datasource_luid: str,
        vizql_json: Dict[str, Any],
        limit: int = 1000,
        timeout: int = 30,
        connection_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        执行查询（Spec 14 §5.5）。

        Args:
            datasource_luid: Tableau 数据源 LUID
            vizql_json: VizQL 查询 JSON
            limit: 最大返回行数
            timeout: 超时秒数
            connection_id: 连接 ID（必填）

        Returns:
            {"fields": [...], "rows": [[...], ...]}

        Raises:
            QueryExecutorError: NLQ_006 / NLQ_007 / NLQ_009
        """
        # T1.3: 通过 wrapper.invoke("query_metric") 包装 MCP 调用（fallback 保持兼容）
        wrapper = get_wrapper()
        principal = get_principal() or {"id": 0, "role": "analyst"}
        if wrapper is not None:
            # wrapper.invoke 是 async，但 execute() 是 sync，用 asyncio.run 桥接
            cap_result = asyncio.run(wrapper.invoke(
                principal=principal,
                capability_name="query_metric",
                params={
                    "datasource_luid": datasource_luid,
                    "vizql_json": vizql_json,
                    "limit": limit,
                    "timeout": timeout,
                    "connection_id": connection_id,
                },
            ))
            result = cap_result.data if hasattr(cap_result, "data") else cap_result
        else:
            # Fallback: 直接 MCP 调用
            if self.mcp_client is None:
                self.mcp_client = get_tableau_mcp_client(connection_id=connection_id)
            try:
                queryable_fields = _load_mcp_queryable_fields(
                    self.mcp_client,
                    datasource_luid,
                    timeout,
                )
                result = execute_query_datasource_with_guardrail(
                    question="",
                    datasource_luid=datasource_luid,
                    query=vizql_json or {},
                    limit=limit,
                    timeout=timeout,
                    connection_id=connection_id,
                    queryable_fields=queryable_fields,
                    current_datasource={"luid": datasource_luid, "connection_id": connection_id},
                    user_context={
                        "accessible_datasource_luids": [datasource_luid],
                        "accessible_connection_ids": [connection_id] if connection_id is not None else [],
                        "connection_id": connection_id,
                    },
                    execute=lambda safe_args: self.mcp_client.query_datasource(
                        datasource_luid=str(safe_args.get("datasourceLuid") or ""),
                        query=safe_args.get("query") or {},
                        limit=int(safe_args.get("limit") or DEFAULT_GUARDRAIL_LIMIT),
                        timeout=int(safe_args.get("timeout") or timeout),
                        connection_id=safe_args.get("connection_id"),
                    ),
                    chain_mode="query_executor",
                )
            except McpArgsGuardrailRejected as e:
                raise QueryExecutorError(
                    code=e.result.reject_code or "MCP_ARGS_REJECTED",
                    message=e.result.message,
                    details=e.result.to_dict(),
                ) from e
            except TableauMCPError as e:
                # TableauMCPError → NLQError 统一映射
                code_map = {
                    "NLQ_006": "NLQ_006",
                    "NLQ_007": "NLQ_007",
                    "NLQ_009": "NLQ_009",
                }
                nlq_code = code_map.get(e.code, "NLQ_006")
                raise QueryExecutorError(
                    code=nlq_code,
                    message=e.message,
                    details=e.details,
                )
            return result
        return result

    def execute_with_creds(
        self,
        datasource_luid: str,
        vizql_json: Dict[str, Any],
        creds: Dict[str, str],
        limit: int = 1000,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        使用指定凭据执行查询（contextvars 方式）。

        Args:
            datasource_luid: 数据源 LUID
            vizql_json: VizQL JSON
            creds: 凭据字典
            limit: 最大返回行数
            timeout: 超时秒数

        Returns:
            查询结果
        """
        token = _tableau_creds.set(creds)
        try:
            return self.execute(
                datasource_luid=datasource_luid,
                vizql_json=vizql_json,
                limit=limit,
                timeout=timeout,
                connection_id=None,
            )
        finally:
            _tableau_creds.reset(token)


def execute_query(
    datasource_luid: str,
    vizql_json: Dict[str, Any],
    limit: int = 1000,
    timeout: int = 30,
    connection_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    执行查询的便捷函数。

    入口函数，供 nlq_service.py 调用。

    Returns:
        {"fields": [...], "rows": [[...], ...]}

    Raises:
        QueryExecutorError: NLQ_006 / NLQ_007 / NLQ_009
    """
    executor = QueryExecutor()
    return executor.execute(
        datasource_luid=datasource_luid,
        vizql_json=vizql_json,
        limit=limit,
        timeout=timeout,
        connection_id=connection_id,
    )


def _load_mcp_queryable_fields(client, datasource_luid: str, timeout: int) -> list[str]:
    try:
        metadata = client.get_datasource_metadata(datasource_luid, timeout=min(timeout, 30))
        return extract_queryable_fields_from_metadata(metadata)
    except Exception as exc:
        logger.warning("QueryExecutor guardrail metadata lookup failed: datasource=%s error=%s", datasource_luid, exc)
        return []
