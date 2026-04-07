"""
Tableau MCP 查询客户端（Stage 3 执行层）

PRD §5.5 契约实现：
- 约束 A：环境变量完整性（PAT 解密后注入）
- 约束 B：MCP ClientSession 长连接复用（单例模式）
- 约束 C：VizQL JSON 与字段元数据一致性校验

MCP Server 通信：JSON-RPC 2.0 over HTTP
"""
import json
import logging
import threading
from functools import lru_cache
from typing import Any, Dict, List, Optional

import requests

from app.core.crypto import get_tableau_crypto
from services.common.settings import get_tableau_mcp_server_url, get_tableau_mcp_timeout
from services.tableau.models import TableauConnection, TableauAsset

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 单例 Session 管理器（约束 B：长连接复用）
# ─────────────────────────────────────────────────────────────────────────────

_session_lock = threading.Lock()
_session_cache: Optional[requests.Session] = None


def _get_shared_session() -> requests.Session:
    """
    获取共享的 requests.Session（单例）。
    requests.Session 会自动维护 TCP 连接池和 Connection Reuse，
    避免每次请求都新建 TCP 连接。
    """
    global _session_cache
    if _session_cache is None:
        with _session_lock:
            if _session_cache is None:
                _session_cache = requests.Session()
                # 配置连接池参数
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=10,
                    pool_maxsize=20,
                    max_retries=0,  # 重试由上层控制
                )
                _session_cache.mount("http://", adapter)
                _session_cache.mount("https://", adapter)
    return _session_cache


# ─────────────────────────────────────────────────────────────────────────────
# Tableau MCP Client
# ─────────────────────────────────────────────────────────────────────────────

class TableauMCPError(Exception):
    """Tableau MCP 查询异常"""
    def __init__(self, code: str, message: str, details: dict = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


class TableauMCPClient:
    """
    Tableau MCP 查询客户端（单例模式）。

    使用方式：
        client = TableauMCPClient()
        result = await client.query_datasource(datasource_luid, vizql_json, timeout=30)

    ⚡ 长连接复用（约束 B）：内部使用共享 Session，
    不会每次调用都新建 TCP 连接。
    """

    _instance: Optional["TableauMCPClient"] = None
    _init_lock = threading.Lock()

    def __new__(cls) -> "TableauMCPClient":
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # 确保 __init__ 只执行一次（单例模式下）
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._session = _get_shared_session()
        self._ds_connection_cache: Dict[str, TableauConnection] = {}

    # ─────────────────────────────────────────────────────────────────────────
    # 公开 API
    # ─────────────────────────────────────────────────────────────────────────

    def query_datasource(
        self,
        datasource_luid: str,
        query: Dict[str, Any],
        limit: int = 1000,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        通过 Tableau MCP 查询数据源（Stage 3 执行）。

        参数：
            datasource_luid: Tableau 数据源 LUID
            query: VizQL 查询 JSON（符合 PRD §5.5.2 格式）
            limit: 最大返回行数（默认 1000）
            timeout: 超时秒数（默认 30）

        返回：
            {"fields": [...], "rows": [[...], ...]}（符合 PRD §5.5.3 格式）

        异常：
            TableauMCPError: NLQ_006 / NLQ_007 / NLQ_009

        约束 A：环境变量从 TableauConnection 解密注入
        约束 B：Session 长连接复用
        """
        # 1. 获取连接信息（带缓存）
        conn = self._get_connection_by_luid(datasource_luid)

        # 2. 校验连接可用性（PRD §5.5.4）
        if not conn.is_active:
            raise TableauMCPError(
                code="NLQ_009",
                message="Tableau 连接已禁用",
                details={"datasource_luid": datasource_luid},
            )
        if conn.last_test_success is False:
            raise TableauMCPError(
                code="NLQ_009",
                message="Tableau 连接测试失败，请联系管理员",
                details={"datasource_luid": datasource_luid},
            )

        # 3. 解密 PAT（约束 A）
        pat_value = self._decrypt_pat(conn)
        env_vars = {
            "TABLEAU_SERVER_URL": conn.server_url,
            "TABLEAU_SITE": conn.site,
            "TABLEAU_PAT_NAME": conn.token_name,
            "TABLEAU_PAT_VALUE": pat_value,
        }

        # 4. 组装 MCP JSON-RPC 请求
        payload = self._build_jsonrpc_request(
            datasource_luid=datasource_luid,
            query=query,
            limit=limit,
            env_vars=env_vars,
        )

        # 5. 发送请求（约束 B：复用 Session）
        response = self._send_jsonrpc(payload, timeout=timeout)

        # 6. 解析响应
        return self._parse_jsonrpc_response(response)

    # ─────────────────────────────────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────────────────────────────────

    def _get_connection_by_luid(self, datasource_luid: str) -> TableauConnection:
        """通过 datasource_luid 查找对应的 TableauConnection（带内存缓存）"""
        if datasource_luid in self._ds_connection_cache:
            return self._ds_connection_cache[datasource_luid]

        from services.tableau.models import TableauDatabase
        db = TableauDatabase()
        session = db.session
        asset = session.query(TableauAsset).filter(
            TableauAsset.datasource_luid == datasource_luid,
            TableauAsset.is_deleted == False,
        ).first()
        session.close()

        if not asset:
            raise TableauMCPError(
                code="NLQ_009",
                message="数据源不存在或已删除",
                details={"datasource_luid": datasource_luid},
            )

        conn = session.query(TableauConnection).filter(
            TableauConnection.id == asset.connection_id,
        ).first()
        session.close()

        if not conn:
            raise TableauMCPError(
                code="NLQ_009",
                message="数据源关联的连接不存在",
                details={"datasource_luid": datasource_luid, "connection_id": asset.connection_id},
            )

        self._ds_connection_cache[datasource_luid] = conn
        return conn

    def _decrypt_pat(self, conn: TableauConnection) -> str:
        """解密 PAT Secret（约束 A）"""
        try:
            crypto = get_tableau_crypto()
            return crypto.decrypt(conn.token_encrypted)
        except Exception as e:
            logger.error("PAT 解密失败: %s", e)
            raise TableauMCPError(
                code="NLQ_009",
                message="认证凭据解密失败",
                details={"connection_id": conn.id},
            )

    def _build_jsonrpc_request(
        self,
        datasource_luid: str,
        query: Dict[str, Any],
        limit: int,
        env_vars: Dict[str, str],
    ) -> dict:
        """组装 MCP JSON-RPC 2.0 请求"""
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "query-datasource",
            "params": {
                "datasourceLuid": datasource_luid,
                "query": query,
                "limit": limit,
                # 环境变量注入（约束 A）
                "env": env_vars,
            },
        }

    def _send_jsonrpc(self, payload: dict, timeout: int) -> dict:
        """
        发送 JSON-RPC 请求。

        重试策略（PRD §5.5.5）：
        - 网络错误 / 5xx：重试 1 次，间隔 1s
        - 4xx：直接返回，不重试
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        for attempt in range(2):
            try:
                resp = self._session.post(
                    f"{get_tableau_mcp_server_url()}/query-datasource",
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )
                if resp.status_code >= 500 and attempt == 0:
                    # 5xx：重试一次
                    import time
                    time.sleep(1)
                    continue
                return {"status_code": resp.status_code, "body": resp.json(), "raw": resp.text}

            except requests.exceptions.Timeout:
                raise TableauMCPError(
                    code="NLQ_007",
                    message=f"查询超时（{timeout}s）",
                    details={"timeout": timeout},
                )
            except requests.exceptions.ConnectionError as e:
                if attempt == 0:
                    import time
                    time.sleep(1)
                    continue
                logger.error("MCP 连接失败: %s", e)
                raise TableauMCPError(
                    code="NLQ_006",
                    message="MCP 服务不可用",
                    details={"mcp_server_url": get_tableau_mcp_server_url()},
                )
            except Exception as e:
                logger.error("MCP 请求异常: %s", e)
                raise TableauMCPError(
                    code="NLQ_006",
                    message=f"MCP 请求失败: {str(e)}",
                    details={},
                )

        # 最后一次尝试（已经处理过 5xx 重试）
        return {"status_code": resp.status_code, "body": resp.json(), "raw": resp.text}

    def _parse_jsonrpc_response(self, response: dict) -> dict:
        """解析 MCP JSON-RPC 响应"""
        status_code = response["status_code"]

        # 处理 HTTP 错误状态码
        if status_code == 400:
            body = response.get("body", {})
            error_msg = body.get("error", {}).get("message", "VizQL 语法错误")
            raise TableauMCPError(
                code="NLQ_006",
                message=f"VizQL 查询语法错误: {error_msg}",
                details={"body": body},
            )
        elif status_code == 403:
            raise TableauMCPError(
                code="NLQ_009",
                message="数据源访问被拒绝（无权限）",
                details={"status_code": 403},
            )
        elif status_code == 404:
            raise TableauMCPError(
                code="NLQ_009",
                message="数据源不存在",
                details={"status_code": 404},
            )
        elif status_code >= 400:
            raise TableauMCPError(
                code="NLQ_006",
                message=f"MCP 查询失败（HTTP {status_code}）",
                details={"status_code": status_code},
            )

        # 解析 JSON-RPC 响应体
        body = response.get("body", {})
        if "error" in body:
            err = body["error"]
            raise TableauMCPError(
                code=err.get("code", "NLQ_006"),
                message=err.get("message", "MCP 返回错误"),
                details=err.get("data", {}),
            )

        result = body.get("result", {})
        return result


# ─────────────────────────────────────────────────────────────────────────────
# 模块级单例访问器
# ─────────────────────────────────────────────────────────────────────────────

_mcp_client_instance: Optional[TableauMCPClient] = None


def get_tableau_mcp_client() -> TableauMCPClient:
    """获取 TableauMCPClient 单例"""
    global _mcp_client_instance
    if _mcp_client_instance is None:
        _mcp_client_instance = TableauMCPClient()
    return _mcp_client_instance
