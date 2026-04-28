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
                result = self.mcp_client.query_datasource(
                    datasource_luid=datasource_luid,
                    query=vizql_json,
                    limit=limit,
                    timeout=timeout,
                    connection_id=connection_id,
                )
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
